"""Read-only paid/unpaid break totals for payroll.

Backend only. Pure service derived only from ``Break`` rows.
``Break.paid`` had no totals anywhere (team attendance carries
no break figures), so payroll silently omitted breaks; this is
that feed. For one salon and an inclusive local-date range:
per-staff and overall break count, total whole minutes
(``(end - start) // 1 minute``, the staff_day convention), and
the paid vs unpaid split (both always sum to the totals).
Membership is by ``start`` local date in the salon timezone
(via ``bookings.availability._tz``), as in status_counts.
Scoping is via the staff member (``staff_member__salon``) —
``Break`` has no salon field. ``by_staff`` carries only staff
with >=1 break in range, name order; optional ``staff_member``
scopes to one member. Empty/reversed range or ``None`` salon
date returns zeros.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from bookings.availability import _tz
from bookings.models import Break

__all__ = [
    "BreakTotalsReport",
    "StaffBreakTotals",
    "break_totals",
    "break_totals_report",
]


@dataclass(frozen=True)
class StaffBreakTotals:
    staff_member_id: int = None
    staff_name: str = ""
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
            "break_count": self.break_count,
            "total_break_minutes": self.total_break_minutes,
            "paid_break_count": self.paid_break_count,
            "paid_minutes": self.paid_minutes,
            "unpaid_break_count": self.unpaid_break_count,
            "unpaid_minutes": self.unpaid_minutes,
        }


@dataclass(frozen=True)
class BreakTotalsReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    break_count: int = 0
    total_break_minutes: int = 0
    paid_break_count: int = 0
    paid_minutes: int = 0
    unpaid_break_count: int = 0
    unpaid_minutes: int = 0
    by_staff: tuple = field(default_factory=tuple)

    @property
    def count(self):
        return self.break_count

    @property
    def total_minutes(self):
        return self.total_break_minutes

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "break_count": self.break_count,
            "total_break_minutes": self.total_break_minutes,
            "paid_break_count": self.paid_break_count,
            "paid_minutes": self.paid_minutes,
            "unpaid_break_count": self.unpaid_break_count,
            "unpaid_minutes": self.unpaid_minutes,
            "by_staff": [s.as_dict() for s in self.by_staff],
        }


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def _window(salon, date_from, date_to):
    tz = _tz(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return first, last, None, None
    start = datetime.combine(first, time.min, tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    return first, last, start, end


def break_totals(salon, date_from, date_to=None, *, staff_member=None):
    """Return break totals for ``salon`` over a local range.

    Args:
        salon: ``saloncore.Salon`` instance; ``None`` returns zeros.
        date_from: first local date, inclusive (date, or datetime
            reduced to its date in the salon's timezone).
        date_to: last local date, inclusive; defaults to ``date_from``.
        staff_member: optional ``team.StaffMember`` to scope to.

    Returns:
        A :class:`BreakTotalsReport`. A reversed range returns zeros.
    """
    if salon is None or date_from is None:
        return BreakTotalsReport(salon=salon)
    first, last, ws, we = _window(salon, date_from, date_to)
    if ws is None:
        return BreakTotalsReport(salon=salon, start_date=first, end_date=last)
    qs = Break.objects.filter(
        staff_member__salon=salon, start__gte=ws, start__lt=we,
    ).select_related("staff_member")
    if staff_member is not None:
        qs = qs.filter(staff_member=staff_member)
    agg = {}
    for br in qs:
        minutes = (br.end - br.start) // timedelta(minutes=1)
        e = agg.setdefault(br.staff_member_id, {
            "name": br.staff_member.display_name,
            "n": 0, "mins": 0, "pn": 0, "pmins": 0, "un": 0, "umins": 0})
        e["n"] += 1
        e["mins"] += minutes
        if br.paid:
            e["pn"] += 1
            e["pmins"] += minutes
        else:
            e["un"] += 1
            e["umins"] += minutes
    by_staff = tuple(sorted(
        (StaffBreakTotals(
            staff_member_id=k, staff_name=v["name"], break_count=v["n"],
            total_break_minutes=v["mins"], paid_break_count=v["pn"],
            paid_minutes=v["pmins"], unpaid_break_count=v["un"],
            unpaid_minutes=v["umins"]) for k, v in agg.items()),
        key=lambda r: (r.staff_name, r.staff_member_id),
    ))
    return BreakTotalsReport(
        salon=salon, start_date=first, end_date=last,
        break_count=sum(s.break_count for s in by_staff),
        total_break_minutes=sum(s.total_break_minutes for s in by_staff),
        paid_break_count=sum(s.paid_break_count for s in by_staff),
        paid_minutes=sum(s.paid_minutes for s in by_staff),
        unpaid_break_count=sum(s.unpaid_break_count for s in by_staff),
        unpaid_minutes=sum(s.unpaid_minutes for s in by_staff),
        by_staff=by_staff,
    )


def break_totals_report(salon, date_from, date_to=None, *, staff_member=None):
    """Alias for :func:`break_totals`."""
    return break_totals(salon, date_from, date_to, staff_member=staff_member)
