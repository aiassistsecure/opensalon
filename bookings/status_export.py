"""Appointment status counts CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports appointment status counts as a
list of dict rows and as a CSV string built from that same list,
built ON TOP of :mod:`bookings.status_counts` — the
definition of the counts (salon scoping, day/range membership in
the salon's timezone, every status present zero-filled, totals)
is that service's alone and is reused verbatim via
:func:`bookings.status_counts.appointment_status_counts`; this
module never recounts, re-queries appointments, or recomputes a
total. The total in every row is the service's ``total`` verbatim.

Columns are only fields carried by the service's
``StatusCounts`` result:

- ``salon_id``: pk of the salon the counts were scoped to, or
  empty when the service result has no salon.
- ``start_date`` / ``end_date``: ISO-8601 first / last local
  dates counted, inclusive, as carried by the result.
- ``status``: one ``by_status`` key per row, in the service's
  order (every known status, then any legacy value the service
  included).
- ``count``: ``by_status[status]`` verbatim.
- ``total``: the service's ``total`` verbatim, repeated on
  every row so each row is self-contained.

An empty day or range is not header-only: the service returns
every status zero-filled, so the export carries one zero row
per status with ``total`` 0. Lines end with ``"\\n"``.
"""
import csv
import io

from bookings.status_counts import appointment_status_counts

__all__ = [
    "STATUS_EXPORT_FIELDNAMES",
    "export_status_counts",
    "export_status_counts_rows",
    "export_status_counts_csv",
    "status_counts_csv",
]

#: Column order of the CSV export.
STATUS_EXPORT_FIELDNAMES = [
    "salon_id",
    "start_date",
    "end_date",
    "status",
    "count",
    "total",
]


def export_status_counts(
    salon, day=None, end_day=None, *,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return status counts for ``salon`` as a list of dicts.

    Accepts exactly the parameters of
    :func:`bookings.status_counts.appointment_status_counts`,
    passed through unchanged. Every row mirrors a CSV row exactly:
    keys are :data:`STATUS_EXPORT_FIELDNAMES` in order,
    ``salon_id`` is the salon's pk (``""`` when the service result
    has no salon), ``start_date`` / ``end_date`` are ISO-8601
    strings (``""`` when absent), ``count`` and ``total`` are ints.
    Rows follow the service result's ``by_status`` order. An empty
    day or range carries one zero row per status with ``total`` 0.
    Records nothing.
    """
    result = appointment_status_counts(
        salon, day, end_day,
        date_from=date_from, date_to=date_to,
        start_date=start_date, end_date=end_date,
    )
    return [{
        "salon_id": result.salon.pk if result.salon is not None else "",
        "start_date": (
            result.start_date.isoformat() if result.start_date else ""
        ),
        "end_date": (
            result.end_date.isoformat() if result.end_date else ""
        ),
        "status": status,
        "count": count,
        "total": result.total,
    } for status, count in result.by_status.items()]


def export_status_counts_csv(
    salon, day=None, end_day=None, *,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return status counts for ``salon`` as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.status_counts.appointment_status_counts`,
    passed through unchanged: a single day, an inclusive range,
    or the ``date_from=`` / ``date_to=`` (``start_date=`` /
    ``end_date=``) keyword forms. Built from
    :func:`export_status_counts` with the same arguments, so the
    CSV and dict exports always agree.

    Returns:
        A CSV string whose header row is
        :data:`STATUS_EXPORT_FIELDNAMES` and whose data rows are
        one per status in the service result's ``by_status``
        order. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STATUS_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_status_counts(
        salon, day, end_day,
        date_from=date_from, date_to=date_to,
        start_date=start_date, end_date=end_date,
    ):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_status_counts_rows = export_status_counts
status_counts_csv = export_status_counts_csv
