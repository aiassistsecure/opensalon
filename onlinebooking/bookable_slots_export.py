"""CSV export of online booking bookable slots (service-scoped).

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the bookable slots as a
list of dicts (:func:`export_bookable_slots`) and as a CSV
string (:func:`export_bookable_slots_csv`) built from that
same list, so the two formats can never disagree -- one source
of truth.

Why this is not :mod:`onlinebooking.slots_export`
-------------------------------------------------
That module exports :mod:`onlinebooking.slots`: discrete start
times (stepped every 15 minutes) for ONE staff member, given a
bare duration. This module exports a different read shape:
:func:`onlinebooking.services.bookable_slots`, which is
salon-wide and scoped to a concrete ``saloncore.Service`` and
returns, per online-bookable staff member, the free
*intervals* (start/end) long enough for that service. Rows
here are intervals, not discrete starts, and cover every
bookable staff member in the salon at once.

Bookable slots -- reused, never reimplemented
---------------------------------------------
Membership, scoping, ordering, and every interval come
verbatim from :func:`onlinebooking.services.bookable_slots`:
this module calls it unchanged and never re-checks the
per-staff online-booking toggle, the roster, or existing
appointments itself. That service already delegates to
``bookings.availability.available_slots(..., online_only=True)``,
so toggle-off and inactive staff never appear and only
rostered time minus the day's non-cancelled appointments is
offered, with intervals shorter than the service dropped.

Columns -- only fields that exist, exactly
:data:`EXPORT_FIELDNAMES`: ``salon_id``, ``service_id``,
``service_name``, ``service_minutes`` (the service's
``total_minutes``), ``staff_member_id``, ``staff_name`` (the
staff member's ``display_name``), ``online_bookable`` (as
reported on the availability row), ``date`` (ISO-8601 date of
the interval start), ``interval_start`` / ``interval_end``
(ISO-8601 datetime strings), and ``interval_minutes``.

Rows are ordered as the service orders staff (display name),
then by interval order within each staff member. One row per
free interval; a rostered staff member with no free interval
long enough for the service contributes no rows.
"""
import csv
import io

from onlinebooking.services import bookable_slots

__all__ = [
    "EXPORT_FIELDNAMES",
    "BOOKABLE_SLOTS_FIELDNAMES",
    "export_bookable_slots",
    "export_bookable_slots_csv",
    "bookable_slots_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "service_id",
    "service_name",
    "service_minutes",
    "staff_member_id",
    "staff_name",
    "online_bookable",
    "date",
    "interval_start",
    "interval_end",
    "interval_minutes",
]
BOOKABLE_SLOTS_FIELDNAMES = EXPORT_FIELDNAMES


def _record(salon, service, availability, interval):
    return {
        "salon_id": salon.pk,
        "service_id": service.pk,
        "service_name": service.name,
        "service_minutes": service.total_minutes,
        "staff_member_id": availability.staff_member_id,
        "staff_name": availability.staff_member.display_name,
        "online_bookable": availability.online_bookable,
        "date": interval.start.date().isoformat() if interval.start else None,
        "interval_start": interval.start.isoformat() if interval.start else None,
        "interval_end": interval.end.isoformat() if interval.end else None,
        "interval_minutes": interval.minutes,
    }


def export_bookable_slots(salon, service, day):
    """Return the bookable slots as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        service: ``saloncore.Service`` to book, passed unchanged
            to :func:`onlinebooking.services.bookable_slots`.
            ``None`` exports ``[]``.
        day: forwarded unchanged to that service. ``None``
            exports ``[]``.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, one per free interval per bookable staff member,
        in the service's order.
    """
    if salon is None or service is None or day is None:
        return []
    rows = []
    for availability in bookable_slots(salon, service, day):
        for interval in availability.intervals:
            rows.append(_record(salon, service, availability, interval))
    return rows


def export_bookable_slots_csv(salon, service, day):
    """Return the bookable-slots export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_bookable_slots` with the same arguments,
    so the CSV and list exports always agree. Empty exports as
    the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_bookable_slots(salon, service, day):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias matching common caller phrasing.
bookable_slots_csv = export_bookable_slots_csv
