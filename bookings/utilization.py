"""Per-stylist utilization for a date range.

Backend only — no views, templates, or UI. Read-only, derived only
from existing records (one source of truth); nothing stored.

For one salon and an inclusive local-date range, each active staff
member gets booked minutes reused verbatim from
:func:`bookings.staff_day.staff_day_load` (this module never
re-queries appointments) and rostered minutes reused verbatim from
:func:`team.availability.roster_availability` (``total_minutes``:
patterns merged, ``ShiftOverride`` ruling its date), each summed
per day. ``utilization`` is booked / rostered, or ``0.0`` when
rostered is 0 — never a division error or infinity, even if booked
is positive; raw minutes are always carried so callers can see
why. It can exceed 1.0 on overrun. Rows include every active staff
member, ordered by display name; reversed range or ``None``
salon/date returns an empty report.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bookings.availability import _tz
from bookings.staff_day import staff_day_load
from team.availability import roster_availability
from team.models import StaffMember

__all__ = [
    "StaffUtilization",
    "UtilizationReport",
    "staff_utilization",
    "utilization_report",
]


def _rate(booked, rostered):
    return booked / rostered if rostered else 0.0


@dataclass(frozen=True)
class StaffUtilization:
    staff_member: StaffMember = None
    appointment_count: int = 0
    booked_minutes: int = 0
    rostered_minutes: int = 0

    @property
    def staff_member_id(self):
        return self.staff_member.pk if self.staff_member else None

    @property
    def display_name(self):
        return self.staff_member.display_name if self.staff_member else ""

    @property
    def staff_name(self):
        return self.display_name

    @property
    def utilization(self):
        return _rate(self.booked_minutes, self.rostered_minutes)

    def as_dict(self):
        return {
            "staff_member_id": self.staff_member_id,
            "staff_name": self.display_name,
            "appointment_count": self.appointment_count,
            "booked_minutes": self.booked_minutes,
            "rostered_minutes": self.rostered_minutes,
            "utilization": self.utilization,
        }


@dataclass(frozen=True)
class UtilizationReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    appointment_count: int = 0
    booked_minutes: int = 0
    rostered_minutes: int = 0
    by_staff: tuple = field(default_factory=tuple)

    @property
    def utilization(self):
        return _rate(self.booked_minutes, self.rostered_minutes)

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "appointment_count": self.appointment_count,
            "booked_minutes": self.booked_minutes,
            "rostered_minutes": self.rostered_minutes,
            "utilization": self.utilization,
            "by_staff": [s.as_dict() for s in self.by_staff],
        }


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def staff_utilization(salon, date_from, date_to=None):
    """Return per-stylist utilization for ``salon`` over a range.

    ``date_to`` is inclusive and defaults to ``date_from``;
    datetimes are reduced to their date in the salon timezone.
    Returns a :class:`UtilizationReport` with one row per active
    staff member. ``None`` salon/date returns an empty report.
    """
    if salon is None or date_from is None:
        return UtilizationReport(salon=salon)
    tz = _tz(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return UtilizationReport(salon=salon, start_date=first, end_date=last)
    members = list(StaffMember.objects.filter(salon=salon, active=True))
    # pk -> [count, booked, rostered]
    agg = {m.pk: [0, 0, 0] for m in members}
    day = first
    while day <= last:
        for load in staff_day_load(salon, day):
            entry = agg.get(load.staff_member_id)
            if entry is not None:
                entry[0] += load.appointment_count
                entry[1] += load.booked_minutes
        for member in members:
            agg[member.pk][2] += roster_availability(member, day).total_minutes
        day += timedelta(days=1)
    by_staff = tuple(
        StaffUtilization(
            staff_member=m, appointment_count=agg[m.pk][0],
            booked_minutes=agg[m.pk][1], rostered_minutes=agg[m.pk][2],
        )
        for m in sorted(members, key=lambda m: (m.display_name, m.pk))
    )
    return UtilizationReport(
        salon=salon, start_date=first, end_date=last,
        appointment_count=sum(s.appointment_count for s in by_staff),
        booked_minutes=sum(s.booked_minutes for s in by_staff),
        rostered_minutes=sum(s.rostered_minutes for s in by_staff),
        by_staff=by_staff,
    )


def utilization_report(salon, date_from, date_to=None):
    return staff_utilization(salon, date_from, date_to)
