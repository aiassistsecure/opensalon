"""Verbatim Break rows for one salon.

Backend only. Read-only service derived only from ``Break``
rows, returned VERBATIM as stored -- unlike
:mod:`bookings.break_totals`, this module never aggregates,
counts, sums minutes, or splits paid/unpaid into totals: one
result entry per stored ``Break`` row.

Scoping is via the staff member (``staff_member__salon``) --
``Break`` has no salon field. Optional inclusive local-date
range filters by ``start`` local date in the salon timezone
(via ``bookings.availability._tz``, the break_totals
convention); no range returns every break for the salon.
Optional ``staff_member`` scopes to one member. ``None``
salon returns no rows. Ordering is by ``start``, then ``id``.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from bookings.availability import _tz
from bookings.models import Break

__all__ = ["BreakRecord", "breaks", "list_breaks"]


@dataclass(frozen=True)
class BreakRecord:
    id: int = None
    salon_id: int = None
    staff_member_id: int = None
    staff_name: str = ""
    start: object = None
    end: object = None
    paid: bool = False

    def as_dict(self):
        return {
            "id": self.id,
            "salon_id": self.salon_id,
            "staff_member_id": self.staff_member_id,
            "staff_name": self.staff_name,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "paid": bool(self.paid),
        }


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def breaks(salon, date_from=None, date_to=None, *, staff_member=None):
    """Return ``salon``'s Break rows verbatim, as BreakRecords.

    ``date_from``/``date_to`` are inclusive local dates (or
    datetimes reduced to their salon-local date); ``date_to``
    defaults to ``date_from`` when only the former is given.
    A reversed range returns ``()``. Read-only.
    """
    if salon is None:
        return ()
    qs = Break.objects.filter(
        staff_member__salon=salon,
    ).select_related("staff_member").order_by("start", "id")
    if staff_member is not None:
        qs = qs.filter(staff_member=staff_member)
    if date_from is not None:
        tz = _tz(salon)
        first = _as_local_date(date_from, tz)
        last = _as_local_date(date_to, tz) if date_to is not None else first
        if last < first:
            return ()
        ws = datetime.combine(first, time.min, tzinfo=tz)
        we = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
        qs = qs.filter(start__gte=ws, start__lt=we)
    return tuple(
        BreakRecord(
            id=row.pk, salon_id=row.staff_member.salon_id,
            staff_member_id=row.staff_member_id,
            staff_name=row.staff_member.display_name,
            start=row.start, end=row.end, paid=bool(row.paid),
        )
        for row in qs
    )


#: Alias, mirroring the naming convenience in sibling services.
list_breaks = breaks
