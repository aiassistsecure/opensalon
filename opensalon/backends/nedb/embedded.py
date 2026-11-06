"""Embedded NEDB: an in-process connection mode for this backend.

When enabled (env ``OPENSALON_NEDB_EMBEDDED=1`` or OPTIONS
``nedb_embedded``), the wrapper's ``get_new_connection`` returns an
:class:`EmbeddedConnection` whose cursors run statements through
``nedb._native.NedbCore`` -- the embedded v2 DAG core -- opened on
``NEDB_DATA_DIR/<db name>``. No daemon, no pgwire, no HTTP: one
store, opened by this process alone (the owner's rule is HTTP *or*
embedded on a data dir, never both at once). SQL goes to
``NedbCore.nesql``, the same SQL entry the daemon's wire front-end
feeds, so the compiler and catalog layers above this module neither
know nor care which mode a connection runs.

Creation/materialization in ``creation.py`` route through here too:
the sentinel put + tombstone runs on the core's doc API, and
drop/reset is a per-collection purge (``DELETE FROM <t>`` with no
WHERE -- the unfiltered form that applies in-process) instead of an
HTTP drop + recreate. That is what lets ``manage.py migrate``
complete with no daemon running anywhere.

Rowcount: ``nesql`` reports no affected-row count -- writes return
``[]`` -- but Django's save/update/delete paths require one (an
``update_fields`` save raises when it reads 0). The count is
therefore synthesized in :class:`EmbeddedCursor`:

* SELECT and other row-returning statements: ``len(rows)`` (exact).
* INSERT: ``len(rows)`` when the statement carries RETURNING (the
  ORM's insert shape), else the number of tuples in its VALUES
  list; exotic shapes (INSERT..SELECT, which the insert compiler
  never emits for this backend) fall back to 1.
* UPDATE / DELETE without RETURNING: a matched-rows
  ``SELECT COUNT(*)`` over the statement's own table and WHERE,
  taken immediately *before* the write executes. A pre-count is a
  pure read, so it can never double-apply a write the way a failed
  RETURNING rewrite could; and it is exact under the access this
  mode is built for -- one process holds the store. Predicates
  arrive table-qualified (the compiler's shape), which the engine
  requires anyway: a bare-column WHERE silently no-ops in the
  engine (probe-pinned, engine 12.15.16), so no code path here may
  introduce one.
"""

import datetime
import decimal
import json
import os
import re
import threading

_lock = threading.RLock()
_CORES = {}


# -- selection / paths -------------------------------------------------


def embedded_enabled(settings_dict=None):
    if os.environ.get("OPENSALON_NEDB_EMBEDDED", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    options = (settings_dict or {}).get("OPTIONS") or {}
    return bool(options.get("nedb_embedded"))


def data_root(settings_dict=None):
    root = os.environ.get("NEDB_DATA_DIR")
    if not root and settings_dict:
        root = (settings_dict.get("OPTIONS") or {}).get("nedb_data_dir")
    if not root:
        raise RuntimeError(
            "embedded NEDB mode requires NEDB_DATA_DIR (env or OPTIONS)"
        )
    return root


def db_dir(db_name, settings_dict=None):
    return os.path.join(data_root(settings_dict), db_name)


def core_for(db_name, settings_dict=None):
    """Process-wide NedbCore per database name (one store, one open)."""
    from nedb._native import NedbCore

    with _lock:
        core = _CORES.get(db_name)
        if core is None:
            path = db_dir(db_name, settings_dict)
            os.makedirs(path, exist_ok=True)
            core = NedbCore.open(path)
            _CORES[db_name] = core
        return core


def database_exists(db_name, settings_dict=None):
    path = db_dir(db_name, settings_dict)
    return os.path.isdir(path) and bool(os.listdir(path))


def purge_database(db_name, settings_dict=None):
    """Embedded drop: tombstone every row of every known collection.

    The store directory and its hash chain persist (the daemon's drop
    likewise never rewinds the provenance clock); the catalog is
    re-materialized by the caller's reset flow.
    """
    from .schema import declared_catalog

    core = core_for(db_name, settings_dict)
    tables = set(declared_catalog())
    try:
        for row in core.nesql("FROM _nedb.collections"):
            entry = json.loads(row)
            name = entry.get("name") or entry.get("collection")
            if name:
                tables.add(name)
    except Exception:
        pass
    for table in sorted(tables):
        try:
            core.nesql('DELETE FROM "%s"' % table)
        except Exception:
            # A never-written collection has no relation to purge
            # (the engine answers 42P01); on a fresh store that is
            # every table, and "nothing to delete" is success here.
            pass
    core.flush()
    return True


# -- parameter interpolation (psycopg-style %s, client-side) ----------


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, datetime.datetime):
        return "'%s'" % value.isoformat(sep=" ")
    if isinstance(value, (datetime.date, datetime.time)):
        return "'%s'" % value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "'\\x%s'" % bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return "(%s)" % ", ".join(_literal(item) for item in value)
    if isinstance(value, dict):
        return _literal(json.dumps(value))
    return "'%s'" % str(value).replace("'", "''")


def interpolate(sql, params):
    """Bind %s / %(name)s placeholders outside single-quoted literals."""
    if not params:
        return sql
    is_dict = isinstance(params, dict)
    values = params if is_dict else list(params)
    out = []
    i, p, n = 0, 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "%" and i + 1 < n:
            nxt = sql[i + 1]
            if nxt == "%":
                out.append("%")
                i += 2
                continue
            if nxt == "s" and not is_dict:
                out.append(_literal(values[p]))
                p += 1
                i += 2
                continue
            if nxt == "(" and is_dict:
                end = sql.index(")s", i)
                out.append(_literal(values[sql[i + 2 : end]]))
                i = end + 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


# -- rowcount synthesis -------------------------------------------------


def _statement_verb(sql):
    """First keyword of a statement, skipping comments/whitespace."""
    s = sql.lstrip()
    while s.startswith("--") or s.startswith("/*"):
        if s.startswith("--"):
            nl = s.find("\n")
            s = "" if nl < 0 else s[nl + 1 :].lstrip()
        else:
            end = s.find("*/")
            s = "" if end < 0 else s[end + 2 :].lstrip()
    match = re.match(r"([A-Za-z]+)", s)
    return match.group(1).upper() if match else ""


def _top_level_keyword(sql, keyword, start=0):
    """Index of ``keyword`` at paren depth 0 outside strings, or -1."""
    i, n = start, len(sql)
    depth = 0
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and (ch.isalpha() or ch == "_"):
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if sql[i:j].upper() == keyword:
                return i
            i = j
            continue
        i += 1
    return -1


def _values_tuple_count(sql):
    """Number of row tuples in an INSERT's VALUES list (0 if none).

    Counts top-level parenthesized groups after the VALUES keyword,
    stopping at the first non-comma token (ON CONFLICT, RETURNING,
    ``;``). Django's insert compiler emits exactly this shape.
    """
    idx = _top_level_keyword(sql, "VALUES")
    if idx < 0:
        return 0
    i, n = idx + len("VALUES"), len(sql)
    count = 0
    while True:
        while i < n and (sql[i].isspace() or sql[i] == ","):
            i += 1
        if i >= n or sql[i] != "(":
            return count
        depth = 0
        in_str = False
        while i < n:
            ch = sql[i]
            if in_str:
                if ch == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
                i += 1
                continue
            if ch == "'":
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        count += 1


_UPDATE_RE = re.compile(
    r'^\s*UPDATE\s+(?P<table>"(?:[^"]|"")+"|[A-Za-z_][\w$]*)\s+SET\b',
    re.IGNORECASE | re.DOTALL,
)
_DELETE_RE = re.compile(
    r'^\s*DELETE\s+FROM\s+(?P<table>"(?:[^"]|"")+"|[A-Za-z_][\w$]*)',
    re.IGNORECASE | re.DOTALL,
)


def _matched_count(core, sql, verb):
    """Rows an UPDATE/DELETE will match, or None if unparseable.

    Rebuilds the statement's table + WHERE as a COUNT(*) read. The
    WHERE text is reused verbatim -- it arrives table-qualified from
    the compiler, the only predicate shape the engine applies.
    """
    match = (_UPDATE_RE if verb == "UPDATE" else _DELETE_RE).match(sql)
    if not match:
        return None
    where_idx = _top_level_keyword(sql, "WHERE", match.end())
    count_sql = 'SELECT COUNT(*) FROM %s' % match.group("table")
    if where_idx >= 0:
        end = _top_level_keyword(sql, "RETURNING", where_idx)
        predicate = sql[where_idx + len("WHERE") : end if end >= 0 else None]
        count_sql += " WHERE " + predicate.strip().rstrip(";")
    try:
        raw = core.nesql(count_sql)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return int(list(json.loads(raw[0]).values())[0])
    except (ValueError, TypeError, IndexError):
        return None


# -- DB-API-shaped connection / cursor ---------------------------------


class _ConnectionInfo:
    server_version = 170004  # NEDB vendors the PostgreSQL 17.4 grammar

    def parameter_status(self, name):
        return "UTC" if name == "TimeZone" else None


class _TzLoader:
    timezone = datetime.timezone.utc


class _EmbeddedAdaptersMap:
    """A genuine psycopg AdaptersMap with a loader fallback.

    Django's create_cursor probes ``adapters.get_loader(TIMESTAMPTZ)``
    and the schema editor quotes values through ``psycopg.sql.quote``,
    whose Transformer is built from the context's adapters map. A bare
    AdaptersMap has dumpers but no OID loaders (those are registered
    from server type discovery on a real connection), so get_loader
    falls back to a UTC tz loader; Django then registers its own
    SpecificTzLoader on the cursor, exactly as over pgwire. Loaders
    never execute: nesql bypasses psycopg's wire path and values
    arrive as JSON for Django's field converters.
    """

    def __init__(self):
        import zoneinfo

        from django.conf import settings as dj_settings
        from django.db.backends.postgresql.psycopg_any import (
            get_adapters_template,
        )
        from psycopg.adapt import AdaptersMap

        # Django seeds real connections from get_adapters_template
        # (psycopg_any): it carries the dumpers, the jsonb/inet text
        # loaders, and a timestamptz loader class with .timezone set.
        # A bare AdaptersMap() has no dumpers at all (str cannot
        # adapt), and the stock template lacks that .timezone loader.
        template = get_adapters_template(
            dj_settings.USE_TZ, zoneinfo.ZoneInfo(dj_settings.TIME_ZONE)
        )
        self._map = AdaptersMap(template)

    def get_loader(self, oid, format=None):
        loader = self._map.get_loader(oid, format)
        return loader if loader is not None else _TzLoader()

    def get_dumper(self, cls, format=None):
        return self._map.get_dumper(cls, format)

    def register_loader(self, oid_or_name, loader):
        return self._map.register_loader(oid_or_name, loader)

    def register_dumper(self, cls, dumper):
        return self._map.register_dumper(cls, dumper)


class _OfflineContext:
    """The AdaptContext an embedded connection presents as itself.

    psycopg dumpers derive their quoting from ``context.connection``:
    with a truthy connection they call ``Escaping(connection.pgconn)``,
    which type-checks a real libpq PGconn in C -- the one thing
    embedded mode must never create (R1) -- and ``conn_encoding()``
    reads ``pgconn._encoding`` off it. This proxy is falsy, so both
    take psycopg's documented offline path instead (utf-8, single-
    quote doubling, ``E''`` when a backslash is present -- exactly
    the escaping this module's own ``_literal()`` already assumes),
    while every other attribute delegates to the real
    :class:`EmbeddedConnection`, so ``db_name`` / ``settings_dict`` /
    ``adapters`` / ``cursor()`` etc. behave exactly as before.
    """

    def __init__(self, connection):
        self._wrapped = connection

    def __bool__(self):
        return False

    @property
    def connection(self):
        return self

    @property
    def adapters(self):
        return self._wrapped.adapters

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _adapters_map():
    return _EmbeddedAdaptersMap()


class _ExecutedQuery:
    """psycopg3 exposes the last statement as cursor._query.query."""

    def __init__(self, query=None):
        self.query = query


class EmbeddedCursor:
    """A psycopg-shaped cursor whose wire is NedbCore.nesql."""

    def __init__(self, connection):
        # The AdaptContext view of the connection (R1): attribute
        # access delegates to the real EmbeddedConnection, but as a
        # context it is offline, so quoting via a cursor never
        # reaches for a libpq PGconn either.
        self.connection = connection.connection
        self.adapters = _adapters_map()
        self._query = _ExecutedQuery()
        self.arraysize = 1
        self.description = None
        self.rowcount = -1
        self.query = None
        self._rows = []
        self._pos = 0
        self._closed = False

    @property
    def _core(self):
        return core_for(
            self.connection.db_name, self.connection.settings_dict
        )

    def _run(self, sql):
        import psycopg

        try:
            return self._core.nesql(sql)
        except RuntimeError as exc:
            raise psycopg.OperationalError(str(exc)) from exc

    def execute(self, sql, params=None):
        if params:
            sql = interpolate(sql, params)
        self.query = sql.encode("utf-8", "replace")
        self._query = _ExecutedQuery(self.query)
        verb = _statement_verb(sql)
        returning = _top_level_keyword(sql, "RETURNING") >= 0
        # Pre-count BEFORE the write runs (see module docstring): a
        # pure read, so a wrong guess here can never re-apply a write.
        matched = None
        if verb in ("UPDATE", "DELETE") and not returning:
            matched = _matched_count(self._core, sql, verb)
        raw = self._run(sql)
        rows = []
        description = None
        for item in raw:
            obj = json.loads(item)
            if description is None:
                description = [
                    (key, None, None, None, None, None, None) for key in obj
                ]
            rows.append(tuple(obj.values()))
        self._rows = rows
        self._pos = 0
        self.description = description
        if returning or verb not in ("INSERT", "UPDATE", "DELETE"):
            self.rowcount = len(rows)
        elif verb == "INSERT":
            self.rowcount = _values_tuple_count(sql) or 1
        else:  # UPDATE / DELETE without RETURNING
            self.rowcount = matched if matched is not None else len(rows)
        return None

    def executemany(self, sql, param_seq):
        total = 0
        for params in param_seq:
            self.execute(sql, params)
            if self.rowcount > 0:
                total += self.rowcount
        self.rowcount = total

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchmany(self, size=None):
        if size is None:
            size = self.arraysize
        chunk = self._rows[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def fetchall(self):
        chunk = self._rows[self._pos :]
        self._pos = len(self._rows)
        return chunk

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class EmbeddedConnection:
    """A psycopg-shaped connection holding no socket at all."""

    def __init__(self, db_name, settings_dict):
        self.db_name = db_name
        self.settings_dict = settings_dict
        self.autocommit = True
        self.closed = False
        self.info = _ConnectionInfo()
        self.adapters = _adapters_map()
        # No libpq connect here (R1): there is no PGconn at all, so
        # constructing an embedded connection opens no socket and
        # ignores POSTGRES_HOST/POSTGRES_PORT entirely. psycopg
        # consumers reach the pgconn only through the offline
        # context below, which reports pgconn as None -- psycopg's
        # supported no-connection shape for quoting/encoding.
        self.pgconn = None
        self._offline_context = _OfflineContext(self)

    @property
    def connection(self):
        # psycopg's AdaptContext: a connection's .connection is
        # itself -- here, the offline context (R1, see its docstring),
        # so sql.quote()/dumpers never reach for a libpq PGconn.
        return self._offline_context

    def cursor(self, name=None, **kwargs):
        return EmbeddedCursor(self)

    def commit(self):
        # Flush is the durability point of the CAS/autocommit
        # contract: a failed flush means the writes are not
        # persisted, so the failure must surface to the caller
        # instead of being silently swallowed. Engine failures
        # arrive as RuntimeError (same as in EmbeddedCursor._run)
        # and are reported as OperationalError; anything else
        # propagates unchanged.
        import psycopg

        try:
            core_for(self.db_name, self.settings_dict).flush()
        except RuntimeError as exc:
            raise psycopg.OperationalError(str(exc)) from exc

    def rollback(self):
        # Append-only store: there is no transaction to roll back.
        # atomic() semantics on this backend already rest on the CAS
        # batch / autocommit contract (DYOR 9.4); a no-op here is the
        # honest embedded shape of that contract.
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
