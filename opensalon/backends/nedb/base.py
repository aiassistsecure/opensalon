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

Deliberately NOT here (later microtasks): migration/DDL handling
(implication 3), savepoint/transaction mapping (implication 4),
TRUNCATE/flush replacement (implication 5), and identity/RETURNING
handling (implication 6).
"""

from django.db.backends.postgresql.base import (
    DatabaseWrapper as PostgresDatabaseWrapper,
)
from django.db.backends.postgresql.client import DatabaseClient
from django.db.backends.postgresql.features import DatabaseFeatures
from django.db.backends.postgresql.introspection import DatabaseIntrospection
from django.db.backends.postgresql.schema import DatabaseSchemaEditor

from .creation import DatabaseCreation
from .operations import DatabaseOperations


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
