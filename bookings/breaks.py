"""Verbatim Break rows for one salon, plus the Break writer.

Backend only. The read service is derived only from ``Break``
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

:func:`add_break` is the single write path for ``Break``
rows: it mirrors the model's fields exactly (``staff_member``,
``start``, ``end``, ``paid`` -- ``paid`` is payroll-relevant,
whether the blocked time is on the clock) and refuses invalid
shapes with ``ValidationError``, writing nothing.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from bookings.availability import _tz
from bookings.models import Break
from team.models import StaffMember

__all__ = ["BreakRecord", "add_break", "breaks", "list_breaks"]


def add_break(staff_member, start=None, end=None, paid=False, **kwargs):
    """Create a ``Break`` for ``staff_member`` and return it.

    ``start``/``end`` are timezone-aware datetimes (the
    ``starts_at``/``ends_at`` keyword aliases are also accepted);
    ``paid`` records whether the time is on the clock. Raises
    ``ValidationError`` -- writing nothing -- for a missing or
    unknown staff member, missing/naive start or end, or an
    ``end`` that is not after ``start``.
    """
    if "starts_at" in kwargs:
        if start is not None:
            raise ValidationError(
                {"start": "Pass either start or starts_at, not both."})
        start = kwargs.pop("starts_at")
    if "ends_at" in kwargs:
        if end is not None:
            raise ValidationError(
                {"end": "Pass either end or ends_at, not both."})
        end = kwargs.pop("ends_at")
    if kwargs:
        raise ValidationError(
            {next(iter(kwargs)): "Unknown argument."})
    if staff_member is None or not isinstance(staff_member, StaffMember):
        raise ValidationError(
            {"staff_member": "A staff member is required."})
    if staff_member.pk is None or not StaffMember.objects.filter(
            pk=staff_member.pk).exists():
        raise ValidationError(
            {"staff_member": "That staff member does not exist."})
    for field, value in (("start", start), ("end", end)):
        if value is None:
            raise ValidationError({field: f"A break {field} is required."})
        if not isinstance(value, datetime) or timezone.is_naive(value):
            raise ValidationError(
                {field: f"Break {field} must be a timezone-aware datetime."})
    if end <= start:
        raise ValidationError(
            {"end": "Break end must be after its start."})
    return Break.objects.create(
        staff_member=staff_member, start=start, end=end,
        paid=bool(paid))


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
