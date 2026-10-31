"""Service popularity CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's service-popularity
report as a CSV string built ON TOP of
:mod:`insights.popularity` — the definition of service popularity
(appointments per service split by status, service-name resolution,
salon scoping, inclusive window judged in the salon's timezone,
and ranking) is that service's alone and is reused verbatim via
:func:`insights.popularity.service_popularity`; this module
never reimplements counting, re-queries appointments, or
re-orders rows. Ordering is exactly the service's ordering:
``completed_count`` descending, then ``total_count`` descending,
then service name ascending.

Columns are only fields the service's rows actually carry:

- ``service_id``: the row's linked service pk, or empty for
  snapshot-only / unknown rows (``service is None``).
- ``service_name``: the row's resolved display name.
- ``completed_count``: the row's completed appointment count.
- ``booked_count``: the row's booked appointment count.
- ``cancelled_no_show_count``: the row's combined
  cancelled/no-show appointment count.
- ``cancelled_count``: the row's cancelled appointment count.
- ``no_show_count``: the row's no-show appointment count.
- ``total_count``: the row's total appointment count.
"""
import csv
import io

from insights.popularity import service_popularity

__all__ = [
    "POPULARITY_FIELDNAMES",
    "POPULARITY_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_popularity_csv",
    "popularity_csv",
]

#: Column order of the CSV export.
POPULARITY_FIELDNAMES = [
    "service_id",
    "service_name",
    "completed_count",
    "booked_count",
    "cancelled_no_show_count",
    "cancelled_count",
    "no_show_count",
    "total_count",
]

POPULARITY_EXPORT_FIELDNAMES = POPULARITY_FIELDNAMES
EXPORT_FIELDNAMES = POPULARITY_FIELDNAMES


def export_popularity_csv(salon, start, end, **kwargs):
    """Return ``salon``'s service-popularity report as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.popularity.service_popularity`.
        start: inclusive window start, as accepted by that service.
        end: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service.

    Returns:
        A CSV string whose header row is
        :data:`POPULARITY_FIELDNAMES` and whose data rows
        follow the popularity service's ordering exactly,
        with values matching that service's rows. An empty
        window exports as the header row alone. Lines end
        with ``"\\n"``.
    """
    rows = service_popularity(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=POPULARITY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "service_id": (
                "" if row.service_id is None else row.service_id
            ),
            "service_name": row.service_name,
            "completed_count": row.completed_count,
            "booked_count": row.booked_count,
            "cancelled_no_show_count": row.cancelled_no_show_count,
            "cancelled_count": row.cancelled_count,
            "no_show_count": row.no_show_count,
            "total_count": row.total_count,
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
popularity_csv = export_popularity_csv
