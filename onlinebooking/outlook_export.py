"""CSV export of the online booking availability outlook.

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the availability outlook
as a list of dicts (:func:`export_outlook`) and as a CSV string
(:func:`export_outlook_csv`) built from that same list, so the
two formats can never disagree -- one source of truth.

Outlook -- reused, never reimplemented
---------------------------------------
Membership, scoping, ordering, and every slot count come
verbatim from :mod:`onlinebooking.outlook`: this module calls
:func:`onlinebooking.outlook.availability_outlook` and never
reimplements slot, roster, or toggle logic. That service
defines the outlook as:

* One :class:`~onlinebooking.outlook.StaffOutlook` per active
  staff member of the salon with ``online_bookable=True``,
  ordered by display name; staff with
  ``online_bookable=False`` and inactive staff are excluded
  entirely, and staff of other salons never appear.
* Per staff member, one
  :class:`~onlinebooking.outlook.DayOutlook` per day in the
  window (``days``, default ``DEFAULT_OUTLOOK_DAYS``, starting
  at ``start_date``), whose ``slot_count`` / ``slots`` come from
  ``onlinebooking.slots.available_slots`` -- rostered time minus
  the day's appointments, with a start offered only when the
  whole service fits.

Columns -- only fields that exist on the outlook rows, exactly
:data:`EXPORT_FIELDNAMES`: ``salon_id``, ``staff_member_id``,
``staff_name`` (the row's ``display_name``), ``date`` (ISO-8601
date string), ``slot_count``, ``first_slot`` / ``last_slot``
(ISO-8601 strings, or ``None`` when the day has no slots), and
``slots`` (the day's slot start times as ISO-8601 strings
joined by ``";"``, ``""`` when the day has no slots).

Rows are ordered as the outlook service orders staff (display
name), then by date within each staff member.
"""
import csv
import io

from onlinebooking.outlook import (
    DEFAULT_OUTLOOK_DAYS,
    availability_outlook,
)
from onlinebooking.slots import SLOT_STEP_MINUTES

__all__ = [
    "EXPORT_FIELDNAMES",
    "OUTLOOK_FIELDNAMES",
    "export_outlook",
    "export_outlook_csv",
    "export_availability_outlook",
    "export_availability_outlook_csv",
    "outlook_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "staff_member_id",
    "staff_name",
    "date",
    "slot_count",
    "first_slot",
    "last_slot",
    "slots",
]
OUTLOOK_FIELDNAMES = EXPORT_FIELDNAMES


def _record(salon, staff_row, day):
    slots = [slot.isoformat() for slot in day.slots]
    return {
        "salon_id": salon.pk if salon is not None else None,
        "staff_member_id": staff_row.staff_member_id,
        "staff_name": staff_row.display_name,
        "date": day.date.isoformat() if day.date else None,
        "slot_count": day.slot_count,
        "first_slot": day.first_slot.isoformat() if day.first_slot else None,
        "last_slot": day.last_slot.isoformat() if day.last_slot else None,
        "slots": ";".join(slots),
    }


def export_outlook(salon, service_duration, *, days=DEFAULT_OUTLOOK_DAYS,
                   start_date=None, step_minutes=SLOT_STEP_MINUTES):
    """Return the availability outlook as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        service_duration: passed unchanged to
            :func:`onlinebooking.outlook.availability_outlook`.
        days: window size in days, forwarded to the outlook
            service; a non-positive value exports ``[]``.
        start_date: first day of the window, forwarded to the
            outlook service.
        step_minutes: grid spacing, forwarded to the outlook
            service.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, one per staff member per day, ordered as the
        outlook service orders staff, then by date.
    """
    if salon is None:
        return []
    rows = []
    for staff_row in availability_outlook(
        salon, service_duration, days=days, start_date=start_date,
        step_minutes=step_minutes,
    ):
        for day in staff_row.days:
            rows.append(_record(salon, staff_row, day))
    return rows


def export_outlook_csv(salon, service_duration, *, days=DEFAULT_OUTLOOK_DAYS,
                       start_date=None, step_minutes=SLOT_STEP_MINUTES):
    """Return the outlook export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_outlook` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_outlook(
        salon, service_duration, days=days, start_date=start_date,
        step_minutes=step_minutes,
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_availability_outlook = export_outlook
export_availability_outlook_csv = export_outlook_csv
outlook_csv = export_outlook_csv
