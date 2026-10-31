"""NEDB features: savepoints and FOR UPDATE are not supported (N-M3e/i).

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

FOR UPDATE (N-M3i, DYOR section 9.7): ``select_for_update()`` lock
clauses are likewise refused by design on NEDB's pgwire (spike
section 8; DYOR 9.7: "Ban FOR UPDATE ... on the pgwire path:
``select_for_update()`` must be a no-op/refused in the adapter").
Declaring ``has_select_for_update = False`` (and False for the
NOWAIT / SKIP LOCKED / OF / NO KEY variants) makes Django's SELECT
compiler skip the lock clause entirely, so no FOR UPDATE SQL ever
reaches nedbd; ``operations.for_update_sql`` additionally returns
an empty string as a second guard for any direct caller.

Semantics, documented and accepted: on NEDB a
``select_for_update()`` queryset is a plain unlocked SELECT -- the
call is a no-op, including its variants, not an error. Callers must
not rely on it for mutual exclusion or row locking on this backend;
where exclusion matters, use NEDB's native atomicity unit, the CAS
batch / ``if_seq`` transaction (DYOR sections 1 and 9.4).
"""

from django.db.backends.postgresql.features import (
    DatabaseFeatures as PostgresDatabaseFeatures,
)


class DatabaseFeatures(PostgresDatabaseFeatures):
    uses_savepoints = False
    # Release is meaningless without savepoints; keep the pair
    # consistent so no caller can reintroduce RELEASE SAVEPOINT.
    can_release_savepoints = False

    # FOR UPDATE: never emitted to nedbd (DYOR 9.7, N-M3i). With the
    # main flag False the compiler never builds a lock clause, so
    # the variant flags are False too -- they are not separate
    # capabilities NEDB could honour on its own.
    has_select_for_update = False
    has_select_for_update_nowait = False
    has_select_for_update_skip_locked = False
    has_select_for_update_of = False
    has_select_for_no_key_update = False
