"""Combined per-staff payroll feed: roster, attendance, breaks.

Backend only, read-only. Pure service combining three existing
sources of truth — it re-queries none of their underlying rows:
rostered/shift time via :func:`team.availability.salon_roster`
(patterns + shift overrides resolved there), attendance actuals
via :func:`team.attendance_summary.attendance_summary`, and
paid/unpaid breaks via :func:`bookings.break_totals.break_totals`.
One row per staff member (active members zero-filled, plus any
member appearing in attendance/breaks in range), name order;
optional ``staff_member`` scopes to one. Dates are inclusive
local dates in the salon timezone. ``None`` salon/date or a
reversed range returns an empty report, as in break_totals.
No pay rates or amounts are derived — minutes only.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from bookings.availability import _tz
from bookings.break_totals import break_totals
from team.attendance_summary import _as_date, attendance_summary
from team.availability import salon_roster
from team.models import StaffMember

__all__ = [
    "PayrollFeedReport",
    "StaffPayrollRow",
    "payroll_feed",
    "payroll_feed_report",
]


@dataclass(frozen=True)
class StaffPayrollRow:
    staff_member_id: int = None
    staff_name: str = ""
    rostered_minutes: int = 0
    rostered_days: int = 0
    rostered_intervals: int = 0
    actual_minutes: int = 0
    attendance_sessions: int = 0
    closed_sessions: int = 0
    open_sessions: int = 0
    break_count: int = 0
    total_break_minutes: int = 0
    paid_break_count: int = 0
    paid_minutes: int = 0
    unpaid_break_count: int = 0
    unpaid_minutes: int = 0

    def as_dict(self):
        return {
            "staff_member_id": self.staff_member_id,
            "staff_name": self.staff_name,
            "rostered_minutes": self.rostered_minutes,
            "rostered_days": self.rostered_days,
            "rostered_intervals": self.rostered_intervals,
            "actual_minutes": self.actual_minutes,
            "attendance_sessions": self.attendance_sessions,
            "closed_sessions": self.closed_sessions,
            "open_sessions": self.open_sessions,
            "break_count": self.break_count,
            "total_break_minutes": self.total_break_minutes,
            "paid_break_count": self.paid_break_count,
            "paid_minutes": self.paid_minutes,
            "unpaid_break_count": self.unpaid_break_count,
            "unpaid_minutes": self.unpaid_minutes,
        }


@dataclass(frozen=True)
class PayrollFeedReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    by_staff: tuple = field(default_factory=tuple)

    def _sum(self, name):
        return sum(getattr(row, name) for row in self.by_staff)

    staff_count = property(lambda self: len(self.by_staff))
    rostered_minutes = property(lambda self: self._sum("rostered_minutes"))
    actual_minutes = property(lambda self: self._sum("actual_minutes"))
    total_break_minutes = property(lambda self: self._sum("total_break_minutes"))
    paid_minutes = property(lambda self: self._sum("paid_minutes"))
    unpaid_minutes = property(lambda self: self._sum("unpaid_minutes"))

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "staff_count": self.staff_count,
            "rostered_minutes": self.rostered_minutes,
            "actual_minutes": self.actual_minutes,
            "total_break_minutes": self.total_break_minutes,
            "paid_minutes": self.paid_minutes,
            "unpaid_minutes": self.unpaid_minutes,
            "by_staff": [row.as_dict() for row in self.by_staff],
        }


def payroll_feed(salon, start_date, end_date=None, *, staff_member=None):
    """Return the combined payroll feed for ``salon`` over a range.

    Args:
        salon: ``saloncore.Salon``; ``None`` returns an empty report.
        start_date: first local date, inclusive.
        end_date: last local date, inclusive; defaults to ``start_date``.
        staff_member: optional ``team.StaffMember`` to scope to.
    """
    if salon is None or start_date is None:
        return PayrollFeedReport(salon=salon)
    tz = _tz(salon)
    first = _as_date(start_date, tz)
    last = _as_date(end_date, tz) if end_date is not None else first
    if last < first:
        return PayrollFeedReport(salon=salon, start_date=first, end_date=last)

    names, rostered = {}, {}

    def note(member):
        names.setdefault(member.pk, member.display_name)

    if staff_member is not None:
        note(staff_member)
    else:
        for member in StaffMember.objects.filter(salon=salon, active=True):
            note(member)

    day = first
    while day <= last:
        for avail in salon_roster(salon, day):
            if staff_member is not None and avail.staff_member_id != staff_member.pk:
                continue
            note(avail.staff_member)
            entry = rostered.setdefault(
                avail.staff_member_id, {"mins": 0, "days": 0, "intervals": 0})
            entry["mins"] += avail.total_minutes
            entry["intervals"] += len(avail.intervals)
            if avail.is_working:
                entry["days"] += 1
        day += timedelta(days=1)

    attendance = attendance_summary(salon, first, last)
    att = {}
    for entry in attendance.per_staff:
        if staff_member is not None and entry.staff_member_id != staff_member.pk:
            continue
        note(entry.staff_member)
        att[entry.staff_member_id] = entry

    breaks = break_totals(salon, first, last, staff_member=staff_member)
    brk = {}
    for row in breaks.by_staff:
        names.setdefault(row.staff_member_id, row.staff_name)
        brk[row.staff_member_id] = row

    rows = []
    for pk in sorted(names, key=lambda pk: (names[pk], pk)):
        r = rostered.get(pk, {"mins": 0, "days": 0, "intervals": 0})
        a = att.get(pk)
        b = brk.get(pk)
        rows.append(StaffPayrollRow(
            staff_member_id=pk, staff_name=names[pk],
            rostered_minutes=r["mins"], rostered_days=r["days"],
            rostered_intervals=r["intervals"],
            actual_minutes=a.total_minutes if a else 0,
            attendance_sessions=a.sessions_count if a else 0,
            closed_sessions=a.closed_sessions if a else 0,
            open_sessions=a.open_sessions if a else 0,
            break_count=b.break_count if b else 0,
            total_break_minutes=b.total_break_minutes if b else 0,
            paid_break_count=b.paid_break_count if b else 0,
            paid_minutes=b.paid_minutes if b else 0,
            unpaid_break_count=b.unpaid_break_count if b else 0,
            unpaid_minutes=b.unpaid_minutes if b else 0,
        ))
    return PayrollFeedReport(
        salon=salon, start_date=first, end_date=last, by_staff=tuple(rows))


def payroll_feed_report(salon, start_date, end_date=None, *, staff_member=None):
    """Alias for :func:`payroll_feed`."""
    return payroll_feed(salon, start_date, end_date, staff_member=staff_member)
