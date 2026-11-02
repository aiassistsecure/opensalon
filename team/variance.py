"""Rostered-vs-actual variance service for the team app.

Backend only — no views, templates, or UI. Read-only.

For a salon and an inclusive date window (whole local days in
the salon's timezone), per staff member this compares:

* rostered minutes — from :func:`team.availability.roster_availability`,
  the one roster/availability resolution (patterns + overrides);
  no roster logic is duplicated here, and
* actual attended minutes — from
  :func:`team.attendance_summary.attendance_summary`, the one
  session-pairing service over ``AttendanceRecord`` events
  (closed sessions only; open sessions contribute no minutes
  but their check-in day still counts as attended).

``variance_minutes`` is actual − rostered. ``days_rostered``
counts days with rostered time, ``days_attended`` counts
distinct days with at least one attendance session, and
``absence_days`` counts rostered days with no session.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from team.attendance_summary import attendance_summary
from team.availability import _as_date, _tz, roster_availability
from team.models import StaffMember

__all__ = ["RosterVariance", "StaffVariance", "get_roster_variance",
           "roster_variance", "rostered_vs_actual", "variance_report"]


@dataclass(frozen=True)
class StaffVariance:
    """Rostered-vs-actual totals for one staff member."""

    staff_member: object
    rostered_minutes: int = 0
    actual_minutes: int = 0
    days_rostered: int = 0
    days_attended: int = 0
    absence_days: int = 0

    @property
    def staff_member_id(self):
        return getattr(self.staff_member, "pk", None)

    @property
    def display_name(self):
        return getattr(self.staff_member, "display_name", "")

    staff_name = display_name

    @property
    def variance_minutes(self):
        return self.actual_minutes - self.rostered_minutes

    variance = variance_minutes
    rostered_days = property(lambda self: self.days_rostered)
    attended_days = property(lambda self: self.days_attended)
    absences = property(lambda self: self.absence_days)


@dataclass(frozen=True)
class RosterVariance:
    """Rostered-vs-actual variance over an inclusive range."""

    salon: object = None
    start_date: object = None
    end_date: object = None
    per_staff: list = field(default_factory=list)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    entries = property(lambda self: self.per_staff)
    staff = entries

    @property
    def by_staff(self):
        return {e.staff_member_id: e for e in self.per_staff}

    def for_staff(self, staff_member):
        return self.by_staff.get(getattr(staff_member, "pk", staff_member))

    @property
    def rostered_minutes(self):
        return sum(e.rostered_minutes for e in self.per_staff)

    @property
    def actual_minutes(self):
        return sum(e.actual_minutes for e in self.per_staff)

    @property
    def variance_minutes(self):
        return self.actual_minutes - self.rostered_minutes

    @property
    def days_rostered(self):
        return sum(e.days_rostered for e in self.per_staff)

    @property
    def days_attended(self):
        return sum(e.days_attended for e in self.per_staff)

    @property
    def absence_days(self):
        return sum(e.absence_days for e in self.per_staff)

    __iter__ = lambda self: iter(self.per_staff)
    __len__ = lambda self: len(self.per_staff)


def roster_variance(salon, start_date, end_date):
    """Return :class:`RosterVariance` for ``salon`` and window.

    Covers the salon's active staff (zero-filled) plus any other
    member of the salon with attendance sessions in range, ordered
    by display name. Raises ``ValueError`` for a missing salon,
    missing dates, or a reversed range. Read-only.
    """
    if salon is None:
        raise ValueError("roster variance needs a salon")
    if start_date is None or end_date is None:
        raise ValueError("roster variance needs a start and end date")
    tz = _tz(salon)
    first, last = _as_date(start_date, tz), _as_date(end_date, tz)
    if last < first:
        raise ValueError("range end must not be before range start")

    summary = attendance_summary(salon, first, last)
    members = {m.pk: m for m in StaffMember.objects.filter(salon=salon, active=True)}
    for entry in summary.per_staff:
        members.setdefault(entry.staff_member_id, entry.staff_member)

    days = []
    day = first
    while day <= last:
        days.append(day)
        day += timedelta(days=1)

    per_staff = []
    for pk in sorted(members, key=lambda k: (members[k].display_name, k)):
        member = members[pk]
        entry = summary.for_staff(member)
        attended = {s.day for s in entry.sessions} if entry else set()
        rostered = days_rostered = absences = 0
        for d in days:
            avail = roster_availability(member, d)
            rostered += avail.total_minutes
            if avail.is_working:
                days_rostered += 1
                if d not in attended:
                    absences += 1
        per_staff.append(StaffVariance(
            staff_member=member,
            rostered_minutes=rostered,
            actual_minutes=entry.total_minutes if entry else 0,
            days_rostered=days_rostered,
            days_attended=len(attended),
            absence_days=absences,
        ))
    return RosterVariance(salon=salon, start_date=first, end_date=last,
                          per_staff=per_staff)


get_roster_variance = roster_variance
rostered_vs_actual = roster_variance
variance_report = roster_variance
