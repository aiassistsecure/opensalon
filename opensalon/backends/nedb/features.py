"""NEDB features: transactions, savepoints, FOR UPDATE unsupported.

Transactions (N-M6a, DYOR 9.4): ``supports_transactions = False`` --
NEDB pgwire writes are appends to an append-only log and ROLLBACK
does not undo them, so Django's TestCase must not wrap tests in a
transaction it expects to roll back; with this flag TestCase falls
back to TransactionTestCase behaviour and isolates by flushing,
which this backend implements as HTTP drop + recreate (9.5).

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

GROUP BY (N-M6d, DYOR 9.1): ``allows_group_by_selected_pks = False``.
PostgreSQL collapses GROUP BY to the selected PKs, relying on
functional dependency (a grouped PK determines the row's other
columns). NEDB's SQL evaluator does not implement that dependency:
it rejects any selected column that is neither grouped nor
aggregated (live on nedbd-v2 12.15.16:
``column "catalog_product.salon_id" must appear in the GROUP BY
clause or be used in an aggregate function`` -- nedb-live-suite
2026-10-30-2112, signatures 3/5). Declaring False is the
execution/semantics-layer fix (DYOR 9.1): Django's compiler then
emits every selected column in GROUP BY, which NEDB accepts, with
identical grouping semantics (grouping by a PK plus its own row's
columns splits no PK group further).
"""

from django.db.backends.postgresql.features import (
    DatabaseFeatures as PostgresDatabaseFeatures,
)


class DatabaseFeatures(PostgresDatabaseFeatures):
    # Transactions: NEDB pgwire does not roll back (N-M6a, DYOR 9.4).
    # Writes append immediately to the append-only log; a ROLLBACK
    # does not remove them (measured on nedbd-v2 12.15.16: TestCase's
    # rollback left every row visible to the next test --
    # MultipleObjectsReturned across the suite). Declaring False is
    # the honest capability: Django's TestCase then behaves as
    # TransactionTestCase and isolates each test by flushing, and on
    # this backend flush is drop + recreate over HTTP (operations.py /
    # creation.py, DYOR 9.5) -- isolation that actually happens,
    # instead of a rollback wrap that pretends to. Production code
    # must not rely on atomic() rollback on NEDB either; its atomicity
    # unit is the CAS batch / if_seq transaction (DYOR 9.4).
    supports_transactions = False

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

    # GROUP BY: NEDB has no PK functional-dependency reduction
    # (N-M6d, DYOR 9.1) -- see module docstring. False makes the
    # compiler group by every selected column instead of only the PK.
    allows_group_by_selected_pks = False
