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

JSON write path (N-M8a, DYOR implications 7 and 9): the stock
PostgreSQL ``adapt_json_value`` returns psycopg's ``Jsonb`` wrapper,
whose text dumper renders a ``'...'::jsonb`` cast literal under
Django's client-side binding -- and cast VALUES are refused by NEDB
by design (live-suite signature #1, ~40 errors). Here the hook
returns the JSON text itself (``jsonfield.py``), a plain string
literal that NEDB stores verbatim; ``JSONField.from_db_value``
parses it back on read, so no read converter is registered.

Auto-field ranges (N-M6f, DYOR implications 1 and 6): the insert
compiler assigns client-generated PKs at millisecond scale
(~1.79e12, ``identity.py``) to *every* table, but Django's built-in
apps (auth, contenttypes, admin) declare 32-bit ``AutoField`` PKs.
Django's lookup layer compares an integer RHS against
``ops.integer_field_range()`` and raises ``EmptyResultSet`` on
overflow (``IntegerFieldOverflow``), so a ``filter(pk=...)`` /
``UPDATE ... WHERE id = ...`` for such a row compiles to nothing,
the update reports 0 rows, and ``save(update_fields=...)`` raises
"Save with update_fields did not affect any rows" -- the live-suite
signature, via ``update_last_login`` on ``force_login``. On NEDB
there is no 32-bit serial column for that range to describe: the
store is schemaless and ``_id`` is a string, and the assigned ids
round-trip exactly (probe evidence 2026-10-30). So below,
``integer_field_range`` reports the signed 64-bit range for the
auto field types only; every other integer field keeps its stock
range and validation.
"""

from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)

from . import decimalfield, identity, jsonfield, temporal

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


# NEDB stores auto-field PKs as string ``_id`` values with no
# integer width (DYOR 9.6); the range Django must plan against for
# them is the signed 64-bit range the client allocator draws from.
_AUTO_FIELD_RANGE = (-9223372036854775808, 9223372036854775807)
_AUTO_INTERNAL_TYPES = frozenset(
    {"AutoField", "BigAutoField", "SmallAutoField"}
)


class DatabaseOperations(PostgresDatabaseOperations):
    # NEDB compilers: client-assigned PKs, no UNNEST (compiler.py).
    compiler_module = "opensalon.backends.nedb.compiler"

    def integer_field_range(self, internal_type):
        # N-M6f: without this, Django's IntegerFieldOverflow turns a
        # lookup/update on a client-assigned PK (> 2**31, on an
        # AutoField-PK model from a built-in app) into EmptyResultSet
        # before any SQL is sent, and the UPDATE reports 0 rows.
        # Django's SQLite backend widens its ranges the same way for
        # a store that enforces no integer width. Non-auto integer
        # fields keep their stock ranges (module docstring).
        if internal_type in _AUTO_INTERNAL_TYPES:
            return _AUTO_FIELD_RANGE
        return super().integer_field_range(internal_type)
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

    # -- JSON write path: JSON text as a plain string, never a cast --
    # Stock PostgreSQL adapt_json_value returns psycopg's Jsonb, whose
    # text dumper (Django binds client-side) renders a '...'::jsonb
    # cast literal that NEDB refuses by design (DYOR 9.7). Returning
    # the JSON text itself (jsonfield.py) makes the value a plain
    # string literal NEDB stores verbatim (DYOR 9.9); the read path
    # is JSONField.from_db_value's own json.loads, so no converter
    # is registered for JSONField in get_db_converters below.

    def adapt_json_value(self, value, encoder):
        return jsonfield.adapt_json_value(value, encoder)

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
