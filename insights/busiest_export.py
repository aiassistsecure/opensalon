"""Busiest-days CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment or sale.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's busiest-days report
as a plain, JSON-serializable list of dicts
(:func:`export_busiest_days`) and as a CSV string
(:func:`export_busiest_days_csv`) built from that same list, so
the two formats can never disagree — one source of truth.

The report is built ON TOP of :mod:`insights.services` — the
definition of busiest days (non-cancelled appointments per
weekday, appointment value resolved live from the price book,
completed-sale revenue per weekday, salon scoping, inclusive
range judged in the salon's timezone) is that service's alone
and is reused verbatim via
:func:`insights.services.busiest_days`; this module never
reimplements that math, re-queries appointments or sales, or
re-orders rows. Ordering is exactly the service's ordering:
appointment ``count`` descending, then weekday ascending.

Columns are only fields the service's rows actually carry:

- ``weekday``: the row's weekday (Monday=0 through Sunday=6).
- ``weekday_name``: the row's English weekday name.
- ``count``: the row's non-cancelled appointment count.
- ``revenue``: the row's completed-sale revenue.
- ``appointment_value``: the row's appointment value.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.services import busiest_days

__all__ = [
    "BUSIEST_FIELDNAMES",
    "BUSIEST_DAYS_FIELDNAMES",
    "BUSIEST_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_busiest_days",
    "export_busiest_csv",
    "export_busiest_days_csv",
    "busiest_csv",
    "busiest_days_csv",
]

#: Column / key order shared by the dict export and the CSV export.
BUSIEST_FIELDNAMES = [
    "weekday",
    "weekday_name",
    "count",
    "revenue",
    "appointment_value",
]

BUSIEST_DAYS_FIELDNAMES = BUSIEST_FIELDNAMES
BUSIEST_EXPORT_FIELDNAMES = BUSIEST_FIELDNAMES
EXPORT_FIELDNAMES = BUSIEST_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _record(entry):
    return {
        "weekday": entry.weekday,
        "weekday_name": entry.weekday_name,
        "count": entry.count,
        "revenue": _money(entry.revenue),
        "appointment_value": _money(entry.appointment_value),
    }


def export_busiest_days(salon, since, until, **kwargs):
    """Return ``salon``'s busiest days as a list of dicts.

    Each entry is a dict with exactly :data:`BUSIEST_FIELDNAMES`
    keys, built directly from
    :func:`insights.services.busiest_days` called with the same
    arguments, in that service's order. Salon scoping and every
    inclusion rule are the service's. A range with no qualifying
    rows — or a reversed range — returns the service's seven
    zeroed weekday entries, never an empty list. Records nothing.
    """
    entries = busiest_days(salon, since, until, **kwargs)
    return [_record(entry) for entry in entries]


def export_busiest_days_csv(salon, since, until, **kwargs):
    """Return ``salon``'s busiest days as a CSV string.

    The header row is :data:`BUSIEST_FIELDNAMES` and every data
    row comes from :func:`export_busiest_days` with the same
    arguments, so the CSV and list exports always agree. Lines
    end with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=BUSIEST_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_busiest_days(salon, since, until, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_busiest_csv = export_busiest_days_csv
busiest_csv = export_busiest_days_csv
busiest_days_csv = export_busiest_days_csv
