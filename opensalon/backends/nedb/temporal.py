"""Temporal adaptation for NEDB: values travel as ISO 8601 strings.

Per the NEDB DYOR note (2026-10-30), implication 1 (work at the
execution/semantics layer) and implication 9 (the SI document mapping:
scalar fields stay comparable as stored values): NEDB is a schemaless
document engine reached over pgwire. It stores and compares the values
it is given, and its write path accepts string literals, numbers,
TRUE/FALSE and NULL -- expressions, casts and function calls are
refused by design (DYOR section 5).

That breaks stock PostgreSQL datetime handling twice over (see
``EVIDENCE.md``, N-M3b): psycopg renders a ``datetime`` parameter as a
``'...'::timestamptz`` cast expression, which NEDB refuses outright.
Sending the value as a plain ISO 8601 string instead stores it as a
string scalar, and ISO 8601 strings in one fixed shape (UTC offset,
fixed field order) compare and sort chronologically as plain text --
so range filters and ordering keep working on the stored form.

The read path is the mirror: pgwire hands the stored string back, and
the operations converters (``operations.py``) parse it into real
``datetime`` / ``date`` / ``time`` objects again. Nothing temporal is
ever stored in any other shape on this backend.
"""

import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time


def _is_expression(value):
    # Query expressions are not values; Django expects adaptation
    # hooks to pass them through untouched (cf. the PostgreSQL
    # backend's adapt_integerfield_value).
    return hasattr(value, "resolve_expression")


def adapt_datetime_value(value):
    """datetime -> ISO 8601 string (None and expressions pass through)."""
    if value is None or _is_expression(value):
        return value
    if not isinstance(value, datetime.datetime):
        return value
    # Django's field prep has already converted aware values to the
    # connection timezone (UTC under USE_TZ here), so isoformat()
    # yields one canonical shape whose text order is chronological.
    return value.isoformat()


def adapt_date_value(value):
    """date -> ISO 8601 string (None and expressions pass through)."""
    if value is None or _is_expression(value):
        return value
    if isinstance(value, datetime.datetime) or not isinstance(
        value, datetime.date
    ):
        return value
    return value.isoformat()


def adapt_time_value(value):
    """time -> ISO 8601 string (None and expressions pass through)."""
    if value is None or _is_expression(value):
        return value
    if not isinstance(value, datetime.time):
        return value
    if timezone.is_aware(value):
        raise ValueError("Django does not support timezone-aware times.")
    return value.isoformat()


def date_part_sql(sql):
    """Date-part expression for ``sql`` that NEDB's evaluator answers.

    N-M8e (DYOR implication 1; probe: nedb-date-probe-2026-10-31.md).
    Stock PostgreSQL's ``datetime_cast_date_sql`` emits
    ``(sql AT TIME ZONE %s)::date``; on nedbd-v2 12.15.16 any
    statement carrying ``AT TIME ZONE`` leaves the SQL evaluator for
    the NQL path, which refuses JOINs verbatim ("JOIN is not
    supported -- NQL is single-collection") and cannot parse ``AT``
    at all unjoined. Dropping the timezone clause is not enough:
    NEDB casts are transparent (``(start)::date`` returns the full
    ISO string), so ``=`` / ``<=`` against a date would match
    nothing. ``DATE()``, ``DATE_TRUNC()`` and ``LEFT()`` are refused
    by name. What the evaluator does answer, joined and unjoined, is
    ``EXTRACT(YEAR/MONTH/DAY FROM ...)`` over the stored ISO string
    (EXTRACT reports the stored fields). Composing the parts with
    zero-padding yields ``YYYY-MM-DD`` text that compares
    chronologically against Django's date parameter for every
    lookup (``=``, ``>``, ``>=``, ``<``, ``<=``, ``BETWEEN``,
    parenthesised ``IS [NOT] NULL`` -- all verified live).

    The parentheses matter: unparenthesised, NEDB's parser binds
    ``IS NOT NULL`` to the last ``||`` segment only.

    The date part is the stored (UTC) date: NEDB offers no
    ``AT TIME ZONE`` on this path, this backend stores every
    datetime as a UTC ISO string, and the connection timezone is
    UTC by project default. A non-UTC connection timezone therefore
    gets UTC dates from ``__date`` on NEDB, where stock PostgreSQL
    would convert first -- a documented divergence, not a silent
    one-off.
    """
    year = f"EXTRACT(YEAR FROM {sql})"
    month = f"EXTRACT(MONTH FROM {sql})"
    day = f"EXTRACT(DAY FROM {sql})"
    return (
        f"({year} || '-' || "
        f"CASE WHEN {month} < 10 THEN '0' ELSE '' END || {month} || '-' || "
        f"CASE WHEN {day} < 10 THEN '0' ELSE '' END || {day})"
    )


def convert_datetime_value(value, connection):
    """Stored string -> datetime; real datetimes pass through."""
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is not None:
            value = parsed
    if isinstance(value, datetime.datetime):
        from django.conf import settings

        if settings.USE_TZ and not timezone.is_aware(value):
            value = timezone.make_aware(value, connection.timezone)
    return value


def convert_date_value(value):
    """Stored string -> date; real dates pass through."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed is not None:
            return parsed
    return value


def convert_time_value(value):
    """Stored string -> time; real times pass through."""
    if value is None or isinstance(value, datetime.time):
        return value
    if isinstance(value, str):
        parsed = parse_time(value)
        if parsed is not None:
            return parsed
    return value
