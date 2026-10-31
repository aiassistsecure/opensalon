"""Decimal values for NEDB: numbers on the wire, Decimal in Django.

Per the NEDB DYOR note (2026-10-30), implication 1 (work at the
execution/semantics layer only) and implication 9 (scalar fields stay
SQL-filterable as stored values). Measured against nedbd-v2 12.15.16
(N-M6e probe; evidence file cited in the PR):

* A ``Decimal`` parameter sent through Django's insert path is stored
  by NEDB as a JSON number and pgwire hands it back as a Python
  ``float`` (type oid 701, float8) -- ``85.00`` returns as ``85.0``.
  Django registers no converter for plain DecimalField columns (it
  trusts the driver to return ``Decimal`` for a numeric column, as
  stock psycopg does), so the float reaches model code untouched and
  ``Decimal('0.00') + float`` raises ``TypeError`` -- the live-suite
  signature ``unsupported operand type(s) for +: 'decimal.Decimal'
  and 'float'`` (x20, nedb-live-suite-2026-10-30-2112.md).
* Depending on the writer, the same column can also come back as
  ``int`` (integral values / evaluator arithmetic) or as ``str``
  (a Decimal stored by a raw psycopg writer arrives as text). All
  three shapes must become ``Decimal`` on read.
* The write path must NOT be "fixed" by storing strings, the way
  temporal values are stored: decimal strings neither sort nor
  compare numerically on NEDB (measured: ``ORDER BY`` on string
  amounts is lexicographic -- 100.00, 85.00, 9.00 -- and
  ``amount > '50'`` wrongly matches 9.00). ISO datetimes keep one
  fixed shape whose text order is chronological; decimal strings
  have no such shape. Numbers stay numbers.

So the fix is read-path only, per-field, mirroring the SQLite
backend's ``get_decimalfield_converter``: ``operations.py`` registers
the converter below for DecimalField expressions only. A global
psycopg float loader would be the wrong layer -- it cannot tell a
DecimalField's float from a genuine FloatField's float, and would
corrupt the latter.

Conversion rules: ``float`` converts via ``str()`` (Python's shortest
round-trip repr, so the float NEDB made from ``19.99`` converts back
to exactly ``Decimal('19.99')``); ``int`` and numeric ``str`` convert
directly; a ``Decimal`` passes through. For a plain column (``Col``)
the result is quantized to the field's ``decimal_places`` under the
field's context, restoring the stored scale (``85.0`` ->
``Decimal('85.00')``); expression results (aggregates, annotations)
are not quantized, mirroring SQLite. Anything unconvertible passes
through unchanged rather than inventing a value -- the same
never-fabricate rule as the identity converter (DYOR 9.6).
"""

import decimal

from django.db.models.expressions import Col


def _to_decimal(value):
    """Lossless-ish Decimal for int/float/str/Decimal, else None."""
    if isinstance(value, decimal.Decimal):
        return value
    if isinstance(value, float):
        # str() gives the shortest repr that round-trips the float,
        # which for a float NEDB derived from a decimal literal is
        # the literal itself ("19.99", not 19.989999...).
        return decimal.Decimal(str(value))
    if isinstance(value, int):
        return decimal.Decimal(value)
    if isinstance(value, str):
        try:
            return decimal.Decimal(value.strip())
        except decimal.InvalidOperation:
            return None
    return None


def convert_decimal_value(value, expression):
    """Stored number/string -> Decimal; None and unknowns pass through."""
    if value is None:
        return None
    result = _to_decimal(value)
    if result is None or not result.is_finite():
        return value
    if isinstance(expression, Col):
        field = expression.output_field
        decimal_places = getattr(field, "decimal_places", None)
        if decimal_places is not None:
            quantum = decimal.Decimal(1).scaleb(-decimal_places)
            try:
                result = result.quantize(
                    quantum, context=field.context
                )
            except decimal.InvalidOperation:
                return value
    return result
