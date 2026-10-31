"""CSV export of the online cancellations summary.

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the online cancellations
summary as a list of dicts (:func:`export_cancellations`) and
as a CSV string (:func:`export_cancellations_csv`) built from
that same list, so the two formats can never disagree -- one
source of truth.

Summary -- reused, never reimplemented
---------------------------------------
Membership, scoping, ordering, and every count come verbatim
from :mod:`onlinebooking.cancellations`: this module calls
:func:`onlinebooking.cancellations.online_cancellation_summary`
and never reimplements its cancelled + online-origin filter,
salon scoping, timezone day judgement, or breakdown ordering.

Columns -- only fields that exist on the summary rows, exactly
:data:`EXPORT_FIELDNAMES`: ``salon_id``, ``start_date`` /
``end_date`` (ISO-8601 date strings, or ``None`` when the
summary has no range), ``section`` (``"staff"``, ``"service"``,
or ``"day"`` -- which breakdown the row belongs to),
``staff_member_id`` / ``staff_name`` (staff rows only),
``service_id`` / ``service_name`` (service rows only), ``date``
(day rows only, ISO-8601), and ``count``.

Rows are ordered as the summary service orders its breakdowns:
staff rows first, then service rows, then day rows. Each
breakdown's counts sum to the summary's ``total``. An export
with no breakdown rows (no salon, or no range and no matching
cancellations) is ``[]`` / the header row alone; a ranged
export with no cancellations still carries the service's
zero-filled day rows.
"""
import csv
import io

from onlinebooking.cancellations import online_cancellation_summary

__all__ = [
    "EXPORT_FIELDNAMES",
    "CANCELLATIONS_FIELDNAMES",
    "export_cancellations",
    "export_cancellations_csv",
    "export_online_cancellations",
    "export_online_cancellations_csv",
    "cancellations_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "start_date",
    "end_date",
    "section",
    "staff_member_id",
    "staff_name",
    "service_id",
    "service_name",
    "date",
    "count",
]
CANCELLATIONS_FIELDNAMES = EXPORT_FIELDNAMES


def _base(salon, summary):
    return {
        "salon_id": salon.pk if salon is not None else None,
        "start_date": (
            summary.start_date.isoformat() if summary.start_date else None),
        "end_date": (
            summary.end_date.isoformat() if summary.end_date else None),
    }


def export_cancellations(salon, date_from=None, date_to=None, **kwargs):
    """Return the online cancellations summary as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        date_from / date_to: forwarded unchanged to
            :func:`onlinebooking.cancellations.online_cancellation_summary`.
        **kwargs: forwarded unchanged to that service (its
            ``start_date=`` / ``end_date=`` / ``day=`` /
            ``end_day=`` aliases).

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys: one per staff breakdown row, then one per service
        breakdown row, then one per day breakdown row, in the
        summary service's ordering within each section.
    """
    if salon is None:
        return []
    summary = online_cancellation_summary(
        salon, date_from, date_to, **kwargs)
    base = _base(salon, summary)
    rows = []
    for row in summary.by_staff:
        rows.append({**base, "section": "staff",
                     "staff_member_id": row.staff_member_id,
                     "staff_name": row.staff_display_name,
                     "service_id": None, "service_name": None,
                     "date": None, "count": row.count})
    for row in summary.by_service:
        rows.append({**base, "section": "service",
                     "staff_member_id": None, "staff_name": None,
                     "service_id": row.service_id,
                     "service_name": row.service_name,
                     "date": None, "count": row.count})
    for row in summary.by_day:
        rows.append({**base, "section": "day",
                     "staff_member_id": None, "staff_name": None,
                     "service_id": None, "service_name": None,
                     "date": row.date.isoformat() if row.date else None,
                     "count": row.count})
    return rows


def export_cancellations_csv(salon, date_from=None, date_to=None, **kwargs):
    """Return the cancellations export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_cancellations` with the same arguments,
    so the CSV and list exports always agree. Empty exports as
    the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_cancellations(
            salon, date_from, date_to, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_online_cancellations = export_cancellations
export_online_cancellations_csv = export_cancellations_csv
cancellations_csv = export_cancellations_csv
