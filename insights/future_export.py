"""Future appointments value CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's future appointments
value report as a plain, JSON-serializable list of dicts
(:func:`export_future_appointments_value`) and as a CSV string
(:func:`export_future_appointments_value_csv`) built from that
same list, so the two formats can never disagree — one source
of truth.

The report is built ON TOP of :mod:`insights.services` — the
definition of future value (future, non-cancelled appointments,
salon scoping via the staff member, price resolved live from
the price book, days judged in the salon's timezone) is that
service's alone and is reused verbatim via
:func:`insights.services.future_appointments_value`; this module
never reimplements that math, re-queries appointments, or
re-orders rows. Ordering is exactly the service's per-day
ordering: ``start_date`` through ``end_date``, oldest first.

The service returns one summary plus a 7-day breakdown, so each
exported row is one day of the breakdown and also carries the
summary fields, repeated on every row, so nothing is lost:

- ``date``: the day entry's calendar date (ISO date).
- ``value``: the day entry's booked value.
- ``count``: the day entry's appointment count.
- ``total``: the summary's total value of all future
  appointments (including those beyond the 7-day breakdown).
- ``total_count``: the summary's total appointment count.
- ``as_of``: the summary's ``as_of`` moment (ISO datetime).
- ``start_date``: the summary's breakdown start (ISO date).
- ``end_date``: the summary's breakdown end (ISO date).

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.services import future_appointments_value

__all__ = [
    "FUTURE_FIELDNAMES",
    "FUTURE_APPOINTMENTS_FIELDNAMES",
    "FUTURE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_future_appointments_value",
    "export_future_appointments_csv",
    "export_future_appointments_value_csv",
    "future_csv",
    "future_appointments_csv",
]

#: Column / key order shared by the dict export and the CSV export.
FUTURE_FIELDNAMES = [
    "date",
    "value",
    "count",
    "total",
    "total_count",
    "as_of",
    "start_date",
    "end_date",
]

FUTURE_APPOINTMENTS_FIELDNAMES = FUTURE_FIELDNAMES
FUTURE_EXPORT_FIELDNAMES = FUTURE_FIELDNAMES
EXPORT_FIELDNAMES = FUTURE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_future_appointments_value(salon, as_of=None, **kwargs):
    """Return ``salon``'s future appointments value as dicts.

    Each entry is a dict with exactly :data:`FUTURE_FIELDNAMES`
    keys, built directly from
    :func:`insights.services.future_appointments_value` called
    with the same arguments: one entry per day of that result's
    7-day breakdown, in its order, with the result's summary
    fields repeated on every entry. Salon scoping and every
    inclusion rule are the service's. A salon with no qualifying
    appointments returns seven zeroed day entries carrying a
    zero total, never an empty list. Records nothing.
    """
    result = future_appointments_value(salon, as_of, **kwargs)
    summary = {
        "total": _money(result.total),
        "total_count": result.count,
        "as_of": result.as_of.isoformat(),
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
    }
    return [
        {
            "date": entry.day.isoformat(),
            "value": _money(entry.value),
            "count": entry.count,
            **summary,
        }
        for entry in result.days
    ]


def export_future_appointments_value_csv(salon, as_of=None, **kwargs):
    """Return ``salon``'s future appointments value as CSV.

    The header row is :data:`FUTURE_FIELDNAMES` and every data
    row comes from :func:`export_future_appointments_value`
    with the same arguments, so the CSV and list exports always
    agree. Lines end with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=FUTURE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_future_appointments_value(
        salon, as_of, **kwargs
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_future_appointments_csv = export_future_appointments_value_csv
future_csv = export_future_appointments_value_csv
future_appointments_csv = export_future_appointments_value_csv
