"""NEDB operations: no session-setup SQL, no savepoint SQL, and
temporal values adapted to ISO 8601 strings (N-M3f).

DYOR implication 2 / spike blocker 1: NEDB's pgwire refuses
``set_config()`` by design ("refused rather than answered with NULL,
because a NULL column reads as missing DATA rather than a missing
feature"). Django's PostgreSQL backend builds its timezone statement
from ``set_time_zone_sql()``, so that method is neutralized here. The
wrapper in ``base.py`` additionally never calls it: both layers are
kept so no future caller can reintroduce the statement by accident.

Temporal adaptation (N-M3f, DYOR implications 1 and 9): the stock
PostgreSQL ``adapt_*field_value`` hooks return datetime/date/time
objects untouched, and psycopg then renders them as
``'...'::timestamptz`` cast expressions, which NEDB's write path
refuses by design (see ``EVIDENCE.md``). Here the hooks return ISO
8601 strings (``temporal.py``), which NEDB stores as string scalars
that compare chronologically, and ``get_db_converters`` registers the
mirror-image parsers so values read back as real temporal objects.
"""

from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)

from . import identity, temporal

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
        return converters

    # -- identity read path: numeric strings back to ints (9.6) ------

    def convert_integerfield_value(self, value, expression, connection):
        return identity.convert_integer_value(value)

    def convert_datetimefield_value(self, value, expression, connection):
        return temporal.convert_datetime_value(value, connection)

    def convert_datefield_value(self, value, expression, connection):
        return temporal.convert_date_value(value)

    def convert_timefield_value(self, value, expression, connection):
        return temporal.convert_time_value(value)
