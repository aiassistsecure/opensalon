"""NEDB operations: no session-setup SQL, no savepoint SQL, and
temporal values adapted to ISO 8601 strings (N-M3f).

DYOR implication 2 / spike blocker 1: NEDB's pgwire refuses
``set_config()`` by design ("refused rather than answered with NULL,
because a NULL column reads as missing DATA rather than a missing
feature"). Django's PostgreSQL backend builds its timezone statement
from ``set_time_zone_sql()``, so that method is neutralized here. The
wrapper in ``base.py`` additionally never calls it: both layers are
kept so no future caller can reintroduce the statement by accident.

Flush (N-M3h, DYOR implication 5): TRUNCATE is refused by design, so
``sql_flush`` builds no statements at all and ``execute_sql_flush``
replaces the flush with the creation layer's drop + recreate of the
whole database over the nedbd HTTP API.

FOR UPDATE (N-M3i, DYOR implication 7): lock clauses are refused by
design, so ``features.has_select_for_update`` is False and
``for_update_sql`` below returns an empty string -- a
``select_for_update()`` queryset compiles to a plain unlocked SELECT
on this backend (documented no-op; see ``features.py``).

Temporal adaptation (N-M3f, DYOR implications 1 and 9): the stock
PostgreSQL ``adapt_*field_value`` hooks return datetime/date/time
objects untouched, and psycopg then renders them as
``'...'::timestamptz`` cast expressions, which NEDB's write path
refuses by design (see ``EVIDENCE.md``). Here the hooks return ISO
8601 strings (``temporal.py``), which NEDB stores as string scalars
that compare chronologically, and ``get_db_converters`` registers the
mirror-image parsers so values read back as real temporal objects.

Decimal read path (N-M6e, DYOR implications 1 and 9): NEDB stores a
Decimal parameter as a JSON number and pgwire returns it as a Python
``float`` (live-suite signature: ``Decimal + float`` TypeError), so
``get_db_converters`` registers ``decimalfield.py``'s converter for
DecimalField expressions, restoring real ``Decimal`` values (with
the field's scale for plain columns). The write path stays numeric
on purpose: decimal strings would compare and sort lexicographically
on NEDB -- see ``decimalfield.py`` for the measured evidence.
"""

from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)

from . import decimalfield, identity, temporal

# Internal types whose stored values must come back as real ints
# (DYOR 9.6 read path): pgwire may hand an integer PK back as a
# numeric string, because NEDB stores ``_id`` as a string.
INTEGER_INTERNAL_TYPES = frozenset(
    {
        "AutoField",
        "BigAutoField",
        "BigIntegerField",
        "IntegerField",
        "PositiveBigIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
        "SmallAutoField",
        "SmallIntegerField",
    }
)


def _is_integer_field(field):
    if field is None:
        return False
    if field.get_internal_type() in INTEGER_INTERNAL_TYPES:
        return True
    target = getattr(field, "target_field", None)
    return (
        target is not None
        and target.get_internal_type() in INTEGER_INTERNAL_TYPES
    )


class DatabaseOperations(PostgresDatabaseOperations):
    # NEDB compilers: client-assigned PKs, no UNNEST (compiler.py).
    compiler_module = "opensalon.backends.nedb.compiler"
    # -- savepoints: no SQL exists on this backend (DYOR 9.4) --------
    # NEDB refuses SAVEPOINT / RELEASE / ROLLBACK TO at execution, and
    # features.uses_savepoints is False, so Django never asks for this
    # SQL. Returning None (not a statement) keeps the builders inert
    # for any direct caller, mirroring set_time_zone_sql below.

    def savepoint_create_sql(self, sid):
        return None

    def savepoint_commit_sql(self, sid):
        return None

    def savepoint_rollback_sql(self, sid):
        return None

    # -- flush: never TRUNCATE (DYOR 9.5, N-M3h) ----------------------
    # NEDB is append-only and refuses TRUNCATE by design, so there is
    # no flush SQL on this backend: sql_flush returns no statements,
    # and execute_sql_flush performs the semantic equivalent -- drop
    # + recreate the current database over HTTP (creation.py).

    def sql_flush(self, style, tables, *, reset_sequences=False, allow_cascade=False):
        return []

    def execute_sql_flush(self, sql_list):
        # sql_list is intentionally ignored (it is always [] here);
        # the flush is a database-level reset, not row deletion.
        name = self.connection.settings_dict["NAME"]
        self.connection.creation.reset_database(name)

    # -- FOR UPDATE: no lock clause exists on this backend (9.7) -----
    # NEDB refuses FOR UPDATE at execution, and
    # features.has_select_for_update is False, so Django's compiler
    # never asks for this SQL. Returning an empty string (falsy, so
    # the compiler appends nothing) keeps the builder inert for any
    # direct caller, mirroring set_time_zone_sql below and the
    # savepoint builders above. All variants (NOWAIT, SKIP LOCKED,
    # OF, NO KEY) degrade the same way: no locking is performed.

    def for_update_sql(self, nowait=False, skip_locked=False, of=(), no_key=False):
        return ""

    def set_time_zone_sql(self):
        # Neutralized: NEDB refuses set_config() on pgwire, and the
        # wrapper never executes a timezone statement. Returning an
        # empty string (not a set_config statement) is the marker that
        # no session-setup SQL exists on this backend.
        return ""

    # -- temporal write path: ISO 8601 strings, never casts ----------

    def adapt_datefield_value(self, value):
        return temporal.adapt_date_value(value)

    def adapt_datetimefield_value(self, value):
        return temporal.adapt_datetime_value(value)

    def adapt_timefield_value(self, value):
        return temporal.adapt_time_value(value)

    # -- temporal read path: stored strings back to objects ----------

    def get_db_converters(self, expression):
        converters = super().get_db_converters(expression)
        if _is_integer_field(expression.output_field):
            converters.append(self.convert_integerfield_value)
        internal_type = expression.output_field.get_internal_type()
        if internal_type == "DateTimeField":
            converters.append(self.convert_datetimefield_value)
        elif internal_type == "DateField":
            converters.append(self.convert_datefield_value)
        elif internal_type == "TimeField":
            converters.append(self.convert_timefield_value)
        elif internal_type == "DecimalField":
            converters.append(self.convert_decimalfield_value)
        return converters

    # -- identity read path: numeric strings back to ints (9.6) ------

    def convert_integerfield_value(self, value, expression, connection):
        return identity.convert_integer_value(value)

    # -- decimal read path: stored numbers back to Decimal (N-M6e) ---

    def convert_decimalfield_value(self, value, expression, connection):
        return decimalfield.convert_decimal_value(value, expression)

    def convert_datetimefield_value(self, value, expression, connection):
        return temporal.convert_datetime_value(value, connection)

    def convert_datefield_value(self, value, expression, connection):
        return temporal.convert_date_value(value)

    def convert_timefield_value(self, value, expression, connection):
        return temporal.convert_time_value(value)
