"""Rebook rate for a salon over a date window.

Backend only — no views, templates, or UI. Read-only; nothing stored.

Definitions (the contract of this module)
-----------------------------------------
* Window: appointments whose ``start`` falls on an inclusive
  local date in ``[start_date, end_date]``, judged in the salon's
  timezone, scoped to the salon via both client and staff member.
  Counts (``total``, ``completed``) are reused verbatim from
  :func:`bookings.status_counts.appointment_status_counts` — this
  module never recounts them.
* Rebooked: a *completed* appointment in the window is rebooked
  when its client has a later appointment — ``start`` strictly
  after the completed appointment's ``start``, with no upper
  bound (it may fall after the window) — whose status is not
  ``cancelled``, scoped to the same salon via both client and
  staff member. The later appointment need not be completed and
  may be with any staff member; the row it credits is the staff
  member of the completed appointment. This measures "the
  client booked again after that visit", not that a rebooking
  was taken at the desk during it — no such field exists.
* Rate: ``rebook_rate_percent`` is ``rebooked / completed * 100``,
  a :class:`~decimal.Decimal` quantised to two places
  (``ROUND_HALF_UP``), mirroring :mod:`bookings.noshow_rate`.
  When ``completed`` is zero there is no meaningful percentage,
  so the rate is ``None`` — never a division error, never
  infinity, never a float.
* ``by_staff`` carries one row per staff member with at least
  one completed appointment in the window, ordered by display
  name then id, each with its own ``completed`` / ``rebooked``
  / ``rebook_rate_percent`` under the same rules.
* A reversed window (``end_date`` before ``start_date``) raises
  ``ValueError``, as in :mod:`bookings.noshow_rate`.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.models import Appointment
from bookings.status_counts import appointment_status_counts

__all__ = [
    "RebookRate", "RebookRateReport", "StaffRebook", "StaffRebookRate",
    "rebook_rate", "rebook_rate_report", "rebook_report",
]

_CENTS = Decimal("0.01")


def _pct(part, total):
    if not total:
        return None
    return (Decimal(part) * 100 / Decimal(total)).quantize(
        _CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class StaffRebookRate:
    staff_member: object = None
    completed: int = 0
    rebooked: int = 0
    rebook_rate_percent: Decimal | None = None

    @property
    def staff_member_id(self):
        return self.staff_member.pk if self.staff_member else None

    @property
    def staff_name(self):
        return self.staff_member.display_name if self.staff_member else ""

    @property
    def display_name(self):
        return self.staff_name

    @property
    def completed_count(self):
        return self.completed

    @property
    def denominator(self):
        return self.completed

    @property
    def rebooked_count(self):
        return self.rebooked

    @property
    def rebook_rate(self):
        return self.rebook_rate_percent

    def as_dict(self):
        return {
            "staff_member_id": self.staff_member_id,
            "staff_name": self.staff_name,
            "completed": self.completed,
            "rebooked": self.rebooked,
            "rebook_rate_percent": self.rebook_rate_percent,
        }


StaffRebook = StaffRebookRate


@dataclass(frozen=True)
class RebookRateReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    total_appointments: int = 0
    completed: int = 0
    rebooked: int = 0
    rebook_rate_percent: Decimal | None = None
    by_staff: tuple = field(default_factory=tuple)

    @property
    def total(self):
        return self.total_appointments

    @property
    def completed_count(self):
        return self.completed

    @property
    def denominator(self):
        return self.completed

    @property
    def rebooked_count(self):
        return self.rebooked

    @property
    def rebook_rate(self):
        return self.rebook_rate_percent

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "total_appointments": self.total_appointments,
            "total": self.total_appointments,
            "completed": self.completed,
            "rebooked": self.rebooked,
            "rebook_rate_percent": self.rebook_rate_percent,
            "by_staff": [s.as_dict() for s in self.by_staff],
        }


RebookRate = RebookRateReport


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def rebook_rate_report(salon, date_from=None, date_to=None, *,
                       start_date=None, end_date=None):
    """Return the rebook rate for ``salon`` in a window.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one
    day, or with ``start_date=`` / ``end_date=`` aliases. Dates
    may be dates or datetimes (reduced in the salon timezone).

    Raises:
        ValueError: if no date is given, or the window is reversed.
    """
    first_raw = date_from if date_from is not None else start_date
    last_raw = date_to if date_to is not None else end_date
    if first_raw is None:
        raise ValueError("Both start_date and end_date are required.")
    if last_raw is None:
        last_raw = first_raw
    if salon is None:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        first, last = _as_local_date(first_raw, tz), _as_local_date(last_raw, tz)
        if last < first:
            raise ValueError("end_date must be on or after start_date.")
        return RebookRateReport(salon=None, start_date=first, end_date=last)
    tz = _tz(salon)
    first = _as_local_date(first_raw, tz)
    last = _as_local_date(last_raw, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    counts = appointment_status_counts(salon, first, last)
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    completed_qs = list(
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            status=Appointment.Status.COMPLETED,
            start__gte=window_start, start__lt=window_end,
        ).select_related("staff_member").order_by("start", "id")
    )
    # Later non-cancelled starts per client (sorted for bisect).
    later = {}
    if completed_qs:
        client_ids = {a.client_id for a in completed_qs}
        rows = Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            client_id__in=client_ids,
        ).exclude(status=Appointment.Status.CANCELLED
                  ).values_list("client_id", "start")
        for client_id, start in rows:
            later.setdefault(client_id, []).append(start)
        for starts in later.values():
            starts.sort()

    def _rebooked(appt):
        starts = later.get(appt.client_id, [])
        return bisect_right(starts, appt.start) < len(starts)

    agg = {}
    for appt in completed_qs:
        entry = agg.setdefault(appt.staff_member_id,
                               {"member": appt.staff_member, "c": 0, "r": 0})
        entry["c"] += 1
        entry["r"] += 1 if _rebooked(appt) else 0
    by_staff = tuple(
        StaffRebookRate(
            staff_member=e["member"], completed=e["c"], rebooked=e["r"],
            rebook_rate_percent=_pct(e["r"], e["c"]))
        for e in sorted(agg.values(),
                        key=lambda e: (e["member"].display_name, e["member"].pk))
    )
    rebooked = sum(s.rebooked for s in by_staff)
    completed = counts.completed
    return RebookRateReport(
        salon=salon, start_date=first, end_date=last,
        total_appointments=counts.total, completed=completed,
        rebooked=rebooked,
        rebook_rate_percent=_pct(rebooked, completed),
        by_staff=by_staff,
    )


rebook_rate = rebook_rate_report
rebook_report = rebook_rate_report
