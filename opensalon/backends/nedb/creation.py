"""NEDB test-database lifecycle: HTTP create / drop / recreate.

DYOR (nedb-dyor-2026-10-30.md), section 9, implications 4, 5 and 8 --
work at the execution/semantics layer only (implication 1):

* Databases are never created or dropped via SQL. NEDB has no
  ``postgres`` maintenance database and refuses all DDL by design
  (pgwire.rs:1246-1255); a database must exist before pgwire serves
  it, created over nedbd's HTTP API (``POST /v1/databases``).
* Test teardown is NOT ``DROP DATABASE`` and never ``TRUNCATE``:
  TRUNCATE is refused by design ("NEDB is append-only so that history
  cannot be discarded"), so teardown and flush semantics are
  drop + recreate of the whole database over HTTP
  (``DELETE /v1/databases/:name`` then ``POST /v1/databases``),
  leaving an empty, pre-created test database behind (implication 5).
* The TestCase wrap-in-transaction replacement from implication 4
  starts here: a fresh test database per run is created by
  drop + recreate, never by savepoints or row deletion.
* Relation materialization (N-M8c, implication 3): a catalogued
  collection that has never been written does not exist as a
  relation for NEDB's write path (DELETE/UPDATE) or its SQL
  evaluator's JOIN resolution -- ``relation "<table>" does not
  exist`` (live-suite signature #2, x37) -- while a plain
  single-table SELECT tolerates it. CREATE TABLE's NEDB-semantics
  equivalent is materializing the empty collection: one sentinel
  document put + tombstone delete per table, in a single CAS batch
  call (probe: nedb-relation-probe-2026-10-31.md). ``reset_database``
  re-materializes the declared catalog after every recreate, and
  the schema editor materializes each CREATE TABLE it validates.

The HTTP endpoint is resolved, in order, from the connection's
``OPTIONS`` (``nedbd_url`` / ``nedbd_http_port`` / ``nedbd_token``),
the ``NEDBD_URL`` / ``NEDBD_HTTP_PORT`` / ``NEDBD_TOKEN`` environment
variables (the official client's env surface, DYOR section 6), or
derived from the pgwire ``HOST`` with the spike's HTTP port 17070.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from django.db.backends.postgresql.creation import (
    DatabaseCreation as PostgresDatabaseCreation,
)

DEFAULT_HTTP_PORT = 17070


class NedbHttpError(RuntimeError):
    """nedbd HTTP API failure; ``status`` is None on transport errors."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class DatabaseCreation(PostgresDatabaseCreation):
    # -- HTTP endpoint resolution -------------------------------------

    def _options(self):
        return self.connection.settings_dict.get("OPTIONS") or {}

    def http_base_url(self):
        options = self._options()
        url = (
            options.get("nedbd_url")
            or options.get("NEDBD_URL")
            or os.environ.get("NEDBD_URL")
        )
        if url:
            return url.rstrip("/")
        host = self.connection.settings_dict.get("HOST") or "127.0.0.1"
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].split(":", 1)[0] or "127.0.0.1"
        port = (
            options.get("nedbd_http_port")
            or os.environ.get("NEDBD_HTTP_PORT")
            or DEFAULT_HTTP_PORT
        )
        return "http://%s:%s" % (host, port)

    def _http_token(self):
        return (
            self._options().get("nedbd_token")
            or os.environ.get("NEDBD_TOKEN")
            or ""
        )

    # -- HTTP transport (one method; tests mock this seam) ------------

    def _http_request(self, method, path, payload=None):
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        token = self._http_token()
        if token:
            headers["Authorization"] = "Bearer %s" % token
        request = urllib.request.Request(
            self.http_base_url() + path, data=body, headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise NedbHttpError(
                "nedbd %s %s -> HTTP %s: %s" % (method, path, exc.code, detail),
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise NedbHttpError(
                "nedbd %s %s unreachable: %s" % (method, path, exc.reason)
            ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- embedded mode: same primitives, in-process ------------------

    def _embedded(self):
        from . import embedded

        return embedded.embedded_enabled(self.connection.settings_dict)

    # -- database primitives over HTTP (DYOR section 4 surface) -------

    def database_exists(self, name):
        if self._embedded():
            from . import embedded

            return embedded.database_exists(
                name, self.connection.settings_dict
            )
        payload = self._http_request("GET", "/v1/databases")
        entries = payload.get("databases", []) if isinstance(payload, dict) else []
        names = {
            entry.get("name") if isinstance(entry, dict) else entry
            for entry in entries
        }
        return name in names

    def create_database(self, name):
        """POST /v1/databases. Returns True if this call created it."""
        if self._embedded():
            from . import embedded

            existed = embedded.database_exists(
                name, self.connection.settings_dict
            )
            embedded.core_for(name, self.connection.settings_dict)
            return not existed
        try:
            self._http_request("POST", "/v1/databases", {"name": name})
        except NedbHttpError as exc:
            if exc.status == 409:  # already exists: creation is idempotent
                return False
            raise
        return True

    def ensure_database(self, name):
        """Create iff missing (the official client's ensure semantics)."""
        if self.database_exists(name):
            return False
        return self.create_database(name)

    def drop_database(self, name):
        """DELETE /v1/databases/:name. A missing database is success.

        Measured on nedbd-v2 12.15.16: after a drop, a recreate POST
        returns an empty database (no collections, no readable rows)
        whose seq/head continue the dropped incarnation's chain --
        the append-only provenance clock is never rewound, which is
        DYOR section 1 behaviour, not leftover data.
        """
        if self._embedded():
            from . import embedded

            self.connection.close()
            return embedded.purge_database(
                name, self.connection.settings_dict
            )
        self.connection.close()
        try:
            self._http_request(
                "DELETE", "/v1/databases/%s" % urllib.parse.quote(name, safe="")
            )
        except NedbHttpError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    # -- relation materialization (N-M8c, DYOR 9.3) -------------------
    # The sentinel's only job is to make the collection exist; it is
    # tombstoned in the same batch, so no read ever sees it (its put
    # and tombstone remain in the append-only log, DYOR section 1).
    MATERIALIZED_SENTINEL_ID = "__opensalon_materialized__"

    def materialize_collections(self, name, tables):
        """Create each table's collection, empty, via one batch call.

        put + del of the sentinel per table over the CAS batch
        endpoint (DYOR section 4). Idempotent: re-materializing an
        existing collection rewrites and re-tombstones only the
        sentinel id, never a real row. Returns the table count.
        """
        tables = sorted({table for table in tables if table})
        if not tables:
            return 0
        if self._embedded():
            from . import embedded

            core = embedded.core_for(name, self.connection.settings_dict)
            for table in tables:
                core.put(
                    table,
                    self.MATERIALIZED_SENTINEL_ID,
                    json.dumps({"id": 0}),
                )
                core.delete(table, self.MATERIALIZED_SENTINEL_ID)
            return len(tables)
        ops = []
        for table in tables:
            ops.append(
                {
                    "op": "put",
                    "coll": table,
                    "id": self.MATERIALIZED_SENTINEL_ID,
                    "doc": {"id": 0},
                }
            )
            ops.append(
                {"op": "del", "coll": table, "id": self.MATERIALIZED_SENTINEL_ID}
            )
        self._http_request(
            "POST",
            "/v1/databases/%s/batch" % urllib.parse.quote(name, safe=""),
            {"ops": ops},
        )
        return len(tables)

    def materialize_catalog(self, name):
        """Materialize every table in the declared catalog (9.3)."""
        from .schema import declared_catalog

        return self.materialize_collections(name, declared_catalog())

    # -- reset lock-safety (cycle 620, census Cluster A/B) ------------
    # A drop's DELETE can return before nedbd has released the data
    # directory, so an immediate recreate POST can meet the engine's
    # split-brain lock refusal (HTTP 500, "locked by another
    # process"). That refusal is NEDB semantics, not a reason to use
    # the daemon's shared-open escape hatch -- the fix lives here, at
    # the execution
    # layer (DYOR 9.1): confirm the drop landed, retry the locked
    # create with bounded backoff, reuse a database the serving
    # engine already has open, and never strand a dropped database
    # behind a failed reset.
    #
    # -- reset freshness (cycle 634, census Cluster C / PR #902) ------
    # The cycle-620 reuse paths above are exactly the cycle-633 leak
    # when the drop itself does not land: if the previous test's
    # database is still open (a stale connection holds it), DELETE
    # can report success while the name keeps listing with its rows
    # intact; the old reset ignored the _wait_until_absent timeout,
    # met a 409 / locked create, called that "reuse-success", and
    # materialized the catalog over the leaked rows. Per DYOR 9.4/9.5
    # a flush IS the drop + recreate -- a database that survived the
    # drop is not a flush and is never reused as one. reset_database
    # therefore: re-closes this process's connection and re-issues
    # the drop (bounded) until absence is verified; accepts a create
    # outcome as fresh only when this reset's POST actually created
    # the database after that verified absence, or when a reused
    # database is demonstrably empty (the daemon's list entry for a
    # fresh database reports no collections -- measured on nedbd
    # 12.15.16, DYOR 9.11); and raises rather than pass a non-empty
    # database on to the next test.
    RESET_RELEASE_TIMEOUT_SECONDS = 5.0
    RESET_RELEASE_POLL_SECONDS = 0.1
    RESET_CREATE_ATTEMPTS = 3
    RESET_CREATE_BACKOFF_SECONDS = 0.25
    RESET_ATTEMPTS = 3

    @staticmethod
    def _is_lock_error(exc):
        if exc.status != 500:
            return False
        text = str(exc)
        return "locked by another process" in text or "split-brain" in text

    def _database_open(self, name):
        """database_exists that treats a failed probe as 'not open'."""
        try:
            return bool(self.database_exists(name))
        except NedbHttpError:
            return False

    def _wait_until_absent(self, name):
        """Poll until the dropped database is gone/released (bounded).

        Returns True once the name no longer lists; False if it is
        still listed when the timeout expires (the create path then
        decides: a 409 / already-open outcome is reuse, not failure).
        """
        deadline = time.monotonic() + self.RESET_RELEASE_TIMEOUT_SECONDS
        while True:
            if not self._database_open(name):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.RESET_RELEASE_POLL_SECONDS)

    def _database_entry(self, name):
        """The daemon's list entry for ``name``, or None if absent."""
        if self._embedded():
            return None
        payload = self._http_request("GET", "/v1/databases")
        entries = payload.get("databases", []) if isinstance(payload, dict) else []
        for entry in entries:
            entry_name = entry.get("name") if isinstance(entry, dict) else entry
            if entry_name == name:
                return entry if isinstance(entry, dict) else {}
        return None

    def _reused_is_fresh(self, name):
        """True unless a reused database is demonstrably non-empty.

        Only called after absence was verified in this reset, so a
        database that is open now post-dates the drop. Where the
        daemon reports the database's collections (nedbd 12.15.16
        does), a fresh database has none; any collection present
        means rows may have survived, and the reuse is rejected.
        Where the daemon reports no collections, the verified
        absence is the freshness evidence available.
        """
        try:
            entry = self._database_entry(name)
        except NedbHttpError:
            return True
        if entry is None:
            return False
        collections = entry.get("collections")
        if collections is None:
            return True
        return len(collections) == 0

    def _create_with_lock_retry(self, name):
        """create_database with bounded retry on the lock refusal only.

        A locked create whose database is in fact already open on the
        serving engine returns False (reuse, like a 409) -- but that
        is only a provisional outcome: reset_database accepts it
        solely after absence was verified in the same reset and the
        reused database passes _reused_is_fresh. Outside that
        sequence, "already open" is the leak, not a success.
        """
        for attempt in range(self.RESET_CREATE_ATTEMPTS):
            try:
                return self.create_database(name)
            except NedbHttpError as exc:
                if not self._is_lock_error(exc):
                    raise
                if self._database_open(name):
                    return False
                if attempt + 1 >= self.RESET_CREATE_ATTEMPTS:
                    raise
                time.sleep(self.RESET_CREATE_BACKOFF_SECONDS * (attempt + 1))

    def _recover_database(self, name):
        """Best-effort reopen/recreate after a failed reset create.

        Returns True only when the database is verified open, so a
        failed reset never strands the suite with a dropped database
        (census Cluster B) when recovery was in fact possible.
        Records in ``_recover_created`` whether recovery's own create
        actually created the database (fresh) as opposed to finding
        one already open (a reuse reset must still verify).
        """
        self._recover_created = False
        if self._database_open(name):
            return True
        try:
            self._recover_created = bool(self.create_database(name))
        except NedbHttpError:
            pass
        return self._database_open(name)

    def reset_database(self, name):
        """Flush by drop + recreate over HTTP -- never TRUNCATE (9.5).

        The recreate is followed by catalog materialization (N-M8c):
        a fresh database otherwise has no relations at all for
        never-written tables, which NEDB's write path and JOIN
        resolution refuse by name.

        Lock-safe and failure-atomic (cycle 620): after the drop,
        confirm the database is gone/released before recreating;
        retry a locked create with bounded backoff; if the create
        still fails, attempt one reopen/recreate and verify the
        database is open before raising, so a failed reset never
        strands a dropped database.

        Fresh (cycle 634): absence after the drop is a hard gate,
        not a hint -- while the name still lists, the drop is
        re-issued (each attempt re-closes this process's connection
        first, via drop_database) instead of proceeding to a create
        whose 409/lock outcome the old code called reuse-success
        over the previous test's rows. A reuse outcome is accepted
        only for a database demonstrably empty (see _reused_is_fresh);
        a reset that cannot obtain a genuinely fresh empty database
        raises instead of leaking rows into the next test.
        """
        if self._embedded():
            # Embedded drop IS the freshness guarantee: purge
            # tombstones every row of every collection in-process,
            # and the store directory persists, so absence-by-listing
            # and the HTTP reuse paths have no meaning here.
            self.drop_database(name)
            self.materialize_catalog(name)
            return name
        for _attempt in range(self.RESET_ATTEMPTS):
            self.drop_database(name)
            if not self._wait_until_absent(name):
                continue  # stale open database survived: drop again
            self._recover_created = False
            try:
                created = self._create_with_lock_retry(name)
            except NedbHttpError:
                if not self._recover_database(name):
                    raise
                created = self._recover_created
            if created or self._reused_is_fresh(name):
                self.materialize_catalog(name)
                return name
            # A reused database with collections present is the
            # previous incarnation, not a flush: loop and re-drop it.
        raise NedbHttpError(
            "nedbd reset of %s failed: no fresh empty database after "
            "%d drop+recreate attempts; refusing to reuse a non-empty "
            "database" % (name, self.RESET_ATTEMPTS)
        )

    # The flush/teardown primitive under its Django-facing name.
    flush_database = reset_database

    # -- Django test-database hooks: no SQL, HTTP only -----------------

    def _execute_create_test_db(self, cursor, parameters, keepdb=False):
        # The cursor is never touched: CREATE DATABASE is refused by
        # NEDB, so creation goes over HTTP regardless of the caller.
        name = str(parameters["dbname"]).strip('"')
        if keepdb:
            self.ensure_database(name)
        else:
            self.create_database(name)

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        # No maintenance-database cursor (NEDB has none). keepdb keeps
        # an existing test database; otherwise the test database is
        # reset by drop + recreate so every run starts empty -- the
        # prompt/autoclobber SQL flow has no NEDB equivalent.
        test_database_name = self._get_test_db_name()
        try:
            if keepdb:
                self.ensure_database(test_database_name)
            else:
                self.reset_database(test_database_name)
        except NedbHttpError as exc:
            self.log("Got an error creating the test database: %s" % exc)
            sys.exit(2)
        return test_database_name

    def _destroy_test_db(self, test_database_name, verbosity):
        # Teardown = drop + recreate over HTTP (DYOR 9.5): the data is
        # gone, an empty pre-created database remains for the next run,
        # and no DROP DATABASE / TRUNCATE SQL is ever emitted. A failed
        # teardown is logged, never allowed to mask the suite's result.
        self.connection.close()
        try:
            self.reset_database(test_database_name)
        except NedbHttpError as exc:
            self.log(
                "NEDB backend: test database teardown over HTTP failed "
                "for %s: %s" % (test_database_name, exc)
            )
        return test_database_name

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        # No CREATE DATABASE ... TEMPLATE (DDL, refused) and no COPY
        # (refused by design, DYOR section 5): a clone is a fresh empty
        # database over HTTP; collections are created implicitly by
        # the first write, so a schema-only clone is the NEDB shape.
        target = self.get_test_db_clone_settings(suffix)["NAME"]
        if keepdb:
            self.ensure_database(target)
        else:
            self.reset_database(target)
