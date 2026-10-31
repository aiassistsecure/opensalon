"""NEDB schema editor: catalog-validating no-op for all DDL (N-M3d).

Per the NEDB DYOR note (2026-10-30), section 9:

* Implication 1 / 9.1: work at the execution/semantics layer only.
  NEDB's vendored PostgreSQL 17.4 grammar already parses every DDL
  statement Django emits; the engine refuses DDL at execution time
  ("collections are created implicitly by the first write ... because
  NEDB is schemaless", pgwire.rs:1246-1255). So this editor changes
  behaviour, not SQL text: it intercepts statements by class.
* Implication 3 / 9.3: the declared schema catalog lives in the APP
  layer (the sukuna-imagine gate pattern -- "NEDB stays schemaless;
  the strictness lives here"). "Migrate" on NEDB means: validate every
  DDL statement's referenced tables against the declared catalog --
  Django's app registry (every model's ``db_table``, including
  auto-created M2M through tables) plus ``django_migrations``, whose
  rows the stock MigrationRecorder stores as ordinary documents --
  and then send NOTHING. Collections come into existence implicitly
  on first write; there is no physical schema to create or alter.

An uncatalogued table in any DDL statement is a hard error
(:class:`UncataloguedTableError`): it means a migration references a
table no installed model declares, which is exactly the model drift /
hallucinated-table failure the catalog exists to catch. Validating
first and failing loudly is the whole point -- a silent no-op would
let migration state advance over a table that will never exist.

Scope: DDL only. Non-DDL statements handed to the editor (e.g. the
``UPDATE ... SET default`` data fixes in ``sql_update_with_default``)
pass through to the PostgreSQL editor unchanged. ``SET CONSTRAINTS``
fragments (PostgreSQL editor templates prepend them to some DDL) are
treated as part of the DDL they accompany and never sent alone.
Savepoints (9.4), temporal adaptation, and identity/RETURNING (9.6)
are separate microtasks and are NOT handled here.

AlterField (N-M6c): the PostgreSQL editor's ``_alter_field`` discovers
constraints to drop/recreate via ``_constraint_names`` ->
``introspection.get_constraints``, whose catalogue query uses a
``WITH ...`` form NEDB refuses at execution. So ``alter_field`` /
``_alter_field`` are intercepted here the same way as other DDL:
validate the model's (and any FK/M2M target's) table against the
declared catalog, then no-op the physical change -- there is no
schema to alter and no constraint catalogue to consult.
"""

import logging
import re

from django.apps import apps
from django.db.backends.postgresql.schema import (
    DatabaseSchemaEditor as PostgresDatabaseSchemaEditor,
)

logger = logging.getLogger("django.db.backends.schema")

# The MigrationRecorder's table is not a Django model, but its rows are
# ordinary NEDB documents and migrations legitimately target it.
EXTRA_CATALOG_TABLES = frozenset({"django_migrations"})


class UncataloguedTableError(ValueError):
    """DDL referenced a table that is not in the declared catalog."""


def declared_catalog():
    """The declared schema catalog: db_tables of the app registry."""
    tables = set(EXTRA_CATALOG_TABLES)
    for app_config in apps.get_app_configs():
        for model in app_config.get_models(include_auto_created=True):
            tables.add(model._meta.db_table)
    return frozenset(tables)


# An optionally schema-qualified, optionally quoted identifier; the
# table is the final component.
_NAME = r'(?:(?:"[^"]+"|[A-Za-z_][\w$]*)\s*\.\s*)?("[^"]+"|[A-Za-z_][\w$]*)'

# Patterns extracting every table a DDL statement references. FK
# REFERENCES targets are validated too: they are tables the statement
# depends on, and an uncatalogued one is the same drift failure.
_TABLE_PATTERNS = [
    re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _NAME, re.I),
    re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _NAME, re.I),
    re.compile(r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?" + _NAME, re.I),
    re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?" + _NAME, re.I),
    re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
               r"(?:IF\s+NOT\s+EXISTS\s+)?(?:\"[^\"]+\"|[A-Za-z_][\w$]*)?\s+ON\s+"
               r"(?:ONLY\s+)?" + _NAME, re.I),
    re.compile(r"\bCOMMENT\s+ON\s+(?:TABLE|COLUMN)\s+" + _NAME, re.I),
    re.compile(r"\bREFERENCES\s+" + _NAME, re.I),
    re.compile(r"\bGRANT\b[^;]*?\bON\s+(?:TABLE\s+)?" + _NAME, re.I),
    re.compile(r"\bREVOKE\b[^;]*?\bON\s+(?:TABLE\s+)?" + _NAME, re.I),
]

_RENAME_TO = re.compile(r"\bRENAME\s+TO\s+" + _NAME, re.I)
_ALTER_TABLE = _TABLE_PATTERNS[2]

# First words that make a single statement DDL (or DDL-adjacent).
_DDL_STARTERS = (
    ("CREATE",), ("ALTER",), ("DROP",), ("TRUNCATE",),
    ("GRANT",), ("REVOKE",),
    ("COMMENT", "ON"),
    ("SET", "CONSTRAINTS"),
)


def _is_ddl(sql):
    """True if any ``;``-separated statement in ``sql`` is DDL."""
    for statement in sql.split(";"):
        words = statement.strip().strip("()").split()
        if not words:
            continue
        head = tuple(word.upper() for word in words[:2])
        if any(head[: len(starter)] == starter for starter in _DDL_STARTERS):
            return True
    return False


def _referenced_tables(sql):
    """Table names referenced by DDL in ``sql`` (unquoted, as written)."""
    tables = set()
    for pattern in _TABLE_PATTERNS:
        for match in pattern.finditer(sql):
            tables.add(match.group(1).strip('"'))
    # ALTER TABLE "old" RENAME TO "new": the source is a historical
    # name the live registry no longer declares; the destination is
    # the catalogued name going forward, so validate only that one.
    if _RENAME_TO.search(sql):
        for match in _ALTER_TABLE.finditer(sql):
            tables.discard(match.group(1).strip('"'))
        for match in _RENAME_TO.finditer(sql):
            tables.add(match.group(1).strip('"'))
    return tables


class DatabaseSchemaEditor(PostgresDatabaseSchemaEditor):
    """PostgreSQL schema editor that validates DDL, then sends none.

    ``catalog`` may be injected (tests, tooling); by default the
    declared catalog is rebuilt from the app registry on each use, so
    it always reflects the installed models.
    """

    def __init__(self, *args, catalog=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalog = catalog

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = declared_catalog()
        return self._catalog

    def validate_sql(self, sql):
        """Raise UncataloguedTableError for any uncatalogued table."""
        known = {table.lower() for table in self.catalog}
        unknown = sorted(
            table for table in _referenced_tables(sql)
            if table.lower() not in known
        )
        if unknown:
            raise UncataloguedTableError(
                "NEDB schema editor: DDL references table(s) absent from "
                "the declared catalog (app registry db_tables + "
                "django_migrations): %s. Statement: %s"
                % (", ".join(unknown), sql.strip()[:200])
            )

    def execute(self, sql, params=()):
        """No-op DDL after catalog validation; pass the rest through.

        Deferred SQL (indexes/constraints collected during a migration)
        reaches this method via ``__exit__`` like everything else, so
        it is validated and skipped here too -- zero DDL is ever sent
        to NEDB, including under ``collect_sql`` (nothing is collected
        either: on NEDB there is no DDL script to show).
        """
        sql_text = str(sql)
        if _is_ddl(sql_text):
            self.validate_sql(sql_text)
            logger.debug(
                "NEDB schema editor: skipping DDL after catalog "
                "validation: %s",
                sql_text.strip()[:200],
            )
            self._materialize_created_tables(sql_text)
            return None
        return super().execute(sql, params)

    def _materialize_created_tables(self, sql):
        """Materialize each CREATE TABLE's collection (N-M8c, 9.3).

        CREATE TABLE is the one DDL whose NEDB-semantics equivalent
        is not nothing: in PostgreSQL it makes the empty relation
        exist, and NEDB's write path / JOIN resolution refuse a
        never-written collection by name. The creation layer's
        put + tombstone sentinel makes the collection exist, empty
        (see creation.py). Best-effort by design (the wrap
        philosophy, DYOR section 7 -- never break the host): an
        unreachable nedbd HTTP surface is logged, never allowed to
        fail the migration; the flush/reset path materializes the
        whole catalog again regardless. Skipped under collect_sql
        (a dry run must not touch the store).
        """
        if self.collect_sql:
            return
        tables = {
            match.group(1).strip('"')
            for match in _TABLE_PATTERNS[0].finditer(sql)
        }
        if not tables:
            return
        creation = getattr(self.connection, "creation", None)
        materialize = getattr(creation, "materialize_collections", None)
        name = self.connection.settings_dict.get("NAME")
        if materialize is None or not name:
            return
        try:
            materialize(name, tables)
        except Exception as exc:  # never break the migration
            logger.warning(
                "NEDB schema editor: could not materialize "
                "collection(s) %s in database %s: %s",
                ", ".join(sorted(tables)),
                name,
                exc,
            )

    # -- AlterField: catalog-validating no-op (N-M6c, DYOR 9.1/9.3) ---

    def _validate_catalogued_table(self, table):
        if table and table.lower() not in {
            name.lower() for name in self.catalog
        }:
            raise UncataloguedTableError(
                "NEDB schema editor: AlterField references table %r "
                "absent from the declared catalog (app registry "
                "db_tables + django_migrations)" % (table,)
            )

    def _validate_alter_field(self, model, *fields):
        self._validate_catalogued_table(model._meta.db_table)
        for field in fields:
            remote = getattr(field, "remote_field", None)
            if remote is None:
                continue
            for related in (getattr(remote, "model", None),
                            getattr(remote, "through", None)):
                meta = getattr(related, "_meta", None)
                if meta is not None:
                    self._validate_catalogued_table(meta.db_table)

    def alter_field(self, model, old_field, new_field, strict=False):
        """Validate against the catalog, then no-op (never introspect).

        Deliberately does NOT call super(): both the PostgreSQL and
        base editors' alter paths call ``_constraint_names``, which
        runs the catalogue query NEDB refuses. ``strict`` is accepted
        for signature compatibility; with no physical constraints,
        there is no constraint count for it to check.
        """
        if not self._field_should_be_altered(old_field, new_field):
            return None
        self._validate_alter_field(model, old_field, new_field)
        logger.debug(
            "NEDB schema editor: skipping AlterField on %s after "
            "catalog validation (schemaless: no physical change)",
            model._meta.db_table,
        )
        return None

    def _alter_field(self, model, old_field, new_field, old_type,
                     new_type, old_db_params, new_db_params,
                     strict=False):
        # Direct-call safety net for the physical step: same
        # catalog-validating no-op, never the inherited introspection.
        self._validate_alter_field(model, old_field, new_field)
        return None

    def _constraint_names(self, model, column_names=None, unique=None,
                          primary_key=None, index=None, foreign_key=None,
                          check=None, type_=None, exclude=None):
        # NEDB holds no physical constraints and its catalogue query
        # is refused, so there is never anything to discover or drop.
        return []
