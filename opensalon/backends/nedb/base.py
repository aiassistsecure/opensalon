"""NEDB DatabaseWrapper: PostgreSQL backend, NEDB connection semantics.

Skeleton scope (N-M3b), per the NEDB DYOR note (2026-10-30), section 9:

* Implication 1: work at the execution/semantics layer only. NEDB's
  vendored PostgreSQL 17.4 grammar already parses everything Django
  emits; the failures are semantics refusals, so this backend changes
  behaviour, not SQL text.
* Implication 2: neutralize connection setup. The stock PostgreSQL
  backend runs ``SELECT set_config('TimeZone', %s, false)`` on every
  new connection (spike blocker 1: NEDB refuses it and every Django
  connection dies). Here ``init_connection_state``,
  ``_configure_connection``, ``_configure_timezone`` and
  ``ensure_timezone`` are no-ops, and the operations class returns no
  set_config statement, so no session-setup SQL is ever sent.
* Implication 8: databases are pre-created over nedbd's HTTP API; see
  ``creation.py`` for the test-database half.
* Implication 3: migration/DDL handling lives in ``schema.py`` -- a
  catalog-validating no-op schema editor (all DDL validated against
  the app registry, then nothing is sent; NEDB is schemaless and its
  collections are created implicitly by the first write).
* Implication 4: savepoints are killed (N-M3e). SAVEPOINT / RELEASE
  SAVEPOINT / ROLLBACK TO SAVEPOINT are refused by NEDB at execution
  (spike section 6, pgwire.rs:1246-1255), so ``features.py`` declares
  ``uses_savepoints = False`` and the ``_savepoint*`` hooks below are
  no-ops: Django ``atomic()`` nesting never sends savepoint SQL to
  nedbd. The accepted trade-off: nested-atomic rollback is
  transaction-level on NEDB, whose atomicity unit is the CAS batch /
  ``if_seq`` transaction, not SQL savepoints.

* Implication 6: identity/RETURNING handling lives in
  ``identity.py`` (client-generated integer PKs, DYOR 9.6) and
  ``compiler.py`` (insert compiler assigns the PK and includes the
  ``id`` column explicitly; no UNNEST bulk shape), with the read-path
  integer converter in ``operations.py``.

TRUNCATE/flush replacement (implication 5, N-M3h) lives in
``creation.py`` (test-database teardown = drop + recreate over the
nedbd HTTP API) and ``operations.py`` (``sql_flush`` builds nothing;
``execute_sql_flush`` delegates to that reset).
"""

from django.db.backends.postgresql.base import (
    DatabaseWrapper as PostgresDatabaseWrapper,
)
from django.db.backends.postgresql.client import DatabaseClient
from django.db.backends.postgresql.introspection import DatabaseIntrospection

from .creation import DatabaseCreation
from .features import DatabaseFeatures
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor


class DatabaseWrapper(PostgresDatabaseWrapper):
    display_name = "NEDB (PostgreSQL pgwire)"
    # Keep vendor "postgresql": Django and third-party code branch on it,
    # and NEDB's pgwire presents as PostgreSQL. The backend is identified
    # by its ENGINE path, not by a new vendor string (skeleton scope).

    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations
    SchemaEditorClass = DatabaseSchemaEditor

    # -- connection setup: no session SQL is ever sent to NEDB ---------

    def _configure_timezone(self, connection):
        return False

    def _configure_connection(self, connection):
        # Stock implementation configures timezone (set_config) and role
        # (SET ROLE); NEDB pgwire refuses session-setup statements, so a
        # NEDB connection needs no configuration at all.
        return False

    def ensure_timezone(self):
        return False

    def init_connection_state(self):
        # No-op on purpose. The PostgreSQL override calls
        # _configure_connection (the set_config path); the base-class
        # version additionally probes the server version on first use.
        # A NEDB connection needs neither: no session state is set here.
        pass

    # -- savepoints: never sent to NEDB (DYOR 9.4, N-M3e) -------------

    def _savepoint(self, sid):
        # No-op on purpose: NEDB refuses SAVEPOINT at execution. The
        # primary guard is features.uses_savepoints = False (Django's
        # _savepoint_allowed() then never calls this); this override
        # keeps the hook inert even for a direct caller.
        pass

    def _savepoint_rollback(self, sid):
        # No-op: ROLLBACK TO SAVEPOINT is refused the same way. An
        # inner atomic() failure therefore rolls back the whole
        # transaction -- Django's fallback when no savepoint exists.
        pass

    def _savepoint_commit(self, sid):
        # No-op: RELEASE SAVEPOINT is refused the same way.
        pass
