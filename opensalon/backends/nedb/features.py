"""NEDB features: savepoints are not supported, by design (N-M3e).

Per the NEDB DYOR note (2026-10-30), section 9.4: SAVEPOINT /
RELEASE SAVEPOINT / ROLLBACK TO SAVEPOINT are execution/semantics
refusals on NEDB's pgwire (pgwire.rs:1246-1255) -- the vendored
PostgreSQL grammar parses them, the schemaless append-only engine
refuses them. Declaring ``uses_savepoints = False`` makes Django's
``_savepoint_allowed()`` return False, so ``atomic()`` nesting never
asks the wrapper to create, release, or roll back to a savepoint.

Consequence, accepted in DYOR 9.4: nested ``atomic()`` rollback is
statement/transaction-level on NEDB, not savepoint-level -- an
exception in an inner block marks the whole transaction for rollback
(Django's own fallback when a savepoint id is None). NEDB's actual
atomicity unit is its CAS batch / ``if_seq`` transaction, not SQL
savepoints.
"""

from django.db.backends.postgresql.features import (
    DatabaseFeatures as PostgresDatabaseFeatures,
)


class DatabaseFeatures(PostgresDatabaseFeatures):
    uses_savepoints = False
    # Release is meaningless without savepoints; keep the pair
    # consistent so no caller can reintroduce RELEASE SAVEPOINT.
    can_release_savepoints = False
