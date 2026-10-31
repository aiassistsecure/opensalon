"""Day book data feed: per-staff appointment blocks for one day.

Pure service module — no views, no templates, no UI. This is the
view-context contract the (separate) webui track consumes to render
the day book; everything here is derived from real querysets, and
nothing new is stored (one source of truth: ``Appointment`` for
blocks, ``RosterPattern`` via :mod:`bookings.availability` for
non-available intervals).

Context shape
-------------
``blocks_for_day(salon, day)`` returns a list of ``StaffDayColumn``,
one per active staff member of the salon, ordered by staff display
name (``StaffMember``'s default ordering)::

    StaffDayColumn(
        staff_member,        # team.StaffMember instance
        staff_member_id,     # its pk (convenience for templates)
        display_name,        # staff_member.display_name
        online_bookable,     # per-staff online-booking toggle
        blocks=(             # AppointmentBlock, ordered by start
            AppointmentBlock(
                appointment_id,        # Appointment pk
                staff_member_id,
                client_display_name,   # str(client): "First Last"
                service_name,          # Service.name, else the
                                       # appointment's service_name snapshot
                service_category_name, # ServiceCategory.name, "" if no service
                start, end,            # aware datetimes, as stored
                status,                # Appointment.status value
            ),
            ...
        ),
    )

Cancelled appointments are not blocks: they do not occupy the book
(the same rule :mod:`bookings.availability` applies). Every other
status is included, with ``status`` carried through so the UI can
style e.g. arrived / in-service / no-show differently.

``breaks_for_day(salon, day)`` returns a list of ``StaffBreaks``
(see its docstring) in the same staff order, and
``daybook_context(salon, day)`` combines both into the plain dict
the day book view hands to its template::

    {"salon": salon, "day": date,
     "columns": [{"staff_member": ..., "staff_member_id": ...,
                  "display_name": ..., "online_bookable": ...,
                  "blocks": [AppointmentBlock, ...],
                  "breaks": [BreakInterval, ...]}, ...]}
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from bookings.availability import _tz, available_slots
from bookings.models import Appointment
from team.models import StaffMember


@dataclass(frozen=True)
class AppointmentBlock:
    appointment_id: int
    staff_member_id: int
    client_display_name: str
    service_name: str
    service_category_name: str
    start: datetime
    end: datetime
    status: str


@dataclass(frozen=True)
class StaffDayColumn:
    staff_member: StaffMember
    online_bookable: bool
    blocks: tuple

    @property
    def staff_member_id(self):
        return self.staff_member.pk

    @property
    def display_name(self):
        return self.staff_member.display_name


@dataclass(frozen=True)
class BreakInterval:
    start: datetime
    end: datetime

    @property
    def minutes(self):
        return (self.end - self.start) // timedelta(minutes=1)


@dataclass(frozen=True)
class StaffBreaks:
    staff_member: StaffMember
    intervals: tuple

    @property
    def staff_member_id(self):
        return self.staff_member.pk


def _day_bounds(salon, day):
    tz = _tz(salon)
    if isinstance(day, datetime):
        day = day.astimezone(tz).date() if day.tzinfo else day.date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return day, start, start + timedelta(days=1)


def blocks_for_day(salon, day):
    """Per-staff columns of appointment blocks for ``salon`` on ``day``.

    Args:
        salon: ``saloncore.Salon`` instance.
        day: a ``datetime.date`` (a datetime is reduced to its date
            in the salon timezone, as in ``available_slots``).

    Returns:
        list of ``StaffDayColumn`` for every active staff member of
        the salon — including members with no blocks, so the UI can
        render an empty column — ordered by staff display name.
        Blocks are the day's non-cancelled appointments overlapping
        the day, ordered by start.
    """
    _, day_start, day_end = _day_bounds(salon, day)
    staff = list(StaffMember.objects.filter(salon=salon, active=True))
    appointments = (
        Appointment.objects.filter(
            staff_member__in=staff,
            start__lt=day_end, end__gt=day_start,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("client", "staff_member", "service", "service__category")
        .order_by("start")
    )
    by_staff = {member.pk: [] for member in staff}
    for appt in appointments:
        by_staff[appt.staff_member_id].append(AppointmentBlock(
            appointment_id=appt.pk,
            staff_member_id=appt.staff_member_id,
            client_display_name=str(appt.client),
            service_name=(
                appt.service.name if appt.service else appt.service_name
            ),
            service_category_name=(
                appt.service.category.name if appt.service else ""
            ),
            start=appt.start,
            end=appt.end,
            status=appt.status,
        ))
    return [
        StaffDayColumn(
            staff_member=member,
            online_bookable=member.online_bookable,
            blocks=tuple(by_staff[member.pk]),
        )
        for member in staff
    ]


def breaks_for_day(salon, day):
    """Placeholder: roster-derived non-available intervals for ``day``.

    There is no break / blocked-time model in the repo yet (see
    :mod:`bookings.availability`). Until one lands, a "break" here is
    any non-available interval *bounded by* free intervals for a
    staff member that day: the gaps between successive free intervals
    returned by ``available_slots``. Such a gap is either a booked
    appointment or a gap between roster windows (e.g. a lunch split
    in the roster) — both are time the day book must not offer.

    Reuses ``available_slots`` rather than re-deriving roster or
    appointment logic, so this stays correct when a real break model
    is subtracted there. Leading/trailing time outside the roster is
    unbounded and is not returned.

    Returns:
        list of ``StaffBreaks`` for staff with rostered time that
        weekday (the ``available_slots`` population), in staff
        display-name order; intervals may be empty.
    """
    results = []
    for availability in available_slots(salon, day):
        free = availability.intervals
        gaps = tuple(
            BreakInterval(start=free[i].end, end=free[i + 1].start)
            for i in range(len(free) - 1)
            if free[i + 1].start > free[i].end
        )
        results.append(StaffBreaks(
            staff_member=availability.staff_member, intervals=gaps,
        ))
    return results


def daybook_context(salon, day):
    """Plain-dict day book context combining blocks and breaks.

    Keys are documented in the module docstring. Columns follow
    ``blocks_for_day`` (all active staff); breaks are merged in by
    staff id, empty for staff with no rostered time that day.
    """
    day, _, _ = _day_bounds(salon, day)
    breaks = {entry.staff_member_id: entry.intervals
              for entry in breaks_for_day(salon, day)}
    columns = [{
        "staff_member": column.staff_member,
        "staff_member_id": column.staff_member_id,
        "display_name": column.display_name,
        "online_bookable": column.online_bookable,
        "blocks": list(column.blocks),
        "breaks": list(breaks.get(column.staff_member_id, ())),
    } for column in blocks_for_day(salon, day)]
    return {"salon": salon, "day": day, "columns": columns}
