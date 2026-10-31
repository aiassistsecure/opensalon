"""CSV export of online booking available slots.

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the available slots as a
list of dicts (:func:`export_slots`) and as a CSV string
(:func:`export_slots_csv`) built from that same list, so the
two formats can never disagree -- one source of truth.

Slots -- reused, never reimplemented
-------------------------------------
Membership, scoping, ordering, and every start time come
verbatim from :mod:`onlinebooking.slots`: this module calls
:func:`onlinebooking.slots.available_slots` and never
reimplements roster, appointment-subtraction, or per-staff
online-booking-toggle logic. That service already excludes a
staff member who is inactive or whose ``online_bookable``
toggle is OFF, and starts only from their rostered windows.
This module adds only an explicit salon guard: a staff member
whose salon is not the salon being exported exports nothing.

Columns -- only fields that exist, exactly
:data:`EXPORT_FIELDNAMES`: ``salon_id`` (the staff member's
salon), ``staff_member_id``, ``staff_name`` (the staff
member's ``display_name``), ``date`` (ISO-8601 date of the
slot), and ``slot_start`` (ISO-8601 datetime string).

Rows are ordered as the slots service orders its starts:
chronologically. One row per available slot start time.
"""
import csv
import io

from onlinebooking.slots import SLOT_STEP_MINUTES, available_slots

__all__ = [
    "EXPORT_FIELDNAMES",
    "SLOTS_FIELDNAMES",
    "export_slots",
    "export_slots_csv",
    "export_available_slots",
    "export_available_slots_csv",
    "slots_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "staff_member_id",
    "staff_name",
    "date",
    "slot_start",
]
SLOTS_FIELDNAMES = EXPORT_FIELDNAMES


def export_slots(salon, staff, date, service_duration, *,
                 step_minutes=SLOT_STEP_MINUTES):
    """Return the available slots as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``, as does a staff member of
            a different salon.
        staff: ``team.StaffMember`` to export slots for, passed
            unchanged to :func:`onlinebooking.slots.available_slots`.
        date: forwarded unchanged to that service.
        service_duration: forwarded unchanged to that service --
            minutes, a ``timedelta``, or a service-like object
            with ``total_minutes``.
        step_minutes: grid spacing, forwarded to that service.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, one per available slot start time, in the slots
        service's chronological order.
    """
    if salon is None or staff is None:
        return []
    if getattr(staff, "salon_id", None) != salon.pk:
        # Fall back to the related-object comparison when salon_id
        # is not materialised.
        staff_salon = getattr(staff, "salon", None)
        if staff_salon is None or staff_salon.pk != salon.pk:
            return []
    rows = []
    for slot in available_slots(
        staff, date, service_duration, step_minutes=step_minutes,
    ):
        rows.append({
            "salon_id": salon.pk,
            "staff_member_id": staff.pk,
            "staff_name": staff.display_name,
            "date": slot.date().isoformat() if slot else None,
            "slot_start": slot.isoformat() if slot else None,
        })
    return rows


def export_slots_csv(salon, staff, date, service_duration, *,
                     step_minutes=SLOT_STEP_MINUTES):
    """Return the slots export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_slots` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_slots(
        salon, staff, date, service_duration, step_minutes=step_minutes,
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_available_slots = export_slots
export_available_slots_csv = export_slots_csv
slots_csv = export_slots_csv
