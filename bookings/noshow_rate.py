"""No-show / late-cancel rate for a salon over a date window.

Backend only — no views, templates, or UI. Read-only; nothing stored.

Definitions (the contract of this module)
-----------------------------------------
* Window: appointments whose ``start`` falls on an inclusive
  local date in ``[start_date, end_date]``, judged in the salon's
  timezone, scoped to the salon via both client and staff member.
  Counts (``total``, ``completed``, ``no_shows``, ``cancelled``)
  are reused verbatim from
  :func:`bookings.status_counts.appointment_status_counts` — this
  module never recounts them.
* Late cancellation: no cancellation policy or threshold exists
  anywhere in this codebase (searched 2026-11-02), so the late
  rule used here is: a cancelled appointment is *late* when it
  was cancelled after the appointment's start time. The model
  carries no dedicated ``cancelled_at`` field, so the cancellation
  moment is ``updated_at`` (the timestamp of the status change to
  ``cancelled``); late means ``updated_at >= start`` for a
  ``cancelled`` appointment in the window.
* Rates: ``no_show_rate_percent`` is ``no_shows / total * 100``
  and ``late_cancel_rate_percent`` is
  ``late_cancellations / total * 100``, each a
  :class:`~decimal.Decimal` quantised to two places
  (``ROUND_HALF_UP``), mirroring :mod:`insights.category_mix` /
  :mod:`insights.prior_period`. When ``total`` is zero there is
  no meaningful percentage, so the rate is ``None`` — never a
  division error, never infinity, never a float.
* A reversed window (``end_date`` before ``start_date``) raises
  ``ValueError``, as in :mod:`insights.prior_period`.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F

from bookings.availability import _tz
from bookings.models import Appointment
from bookings.status_counts import appointment_status_counts

__all__ = [
    "NoShowLateCancelRate", "NoShowRateReport",
    "no_show_late_cancel_rate", "noshow_late_cancel_rate",
    "noshow_rate", "noshow_rate_report",
]

_CENTS = Decimal("0.01")


def _pct(part, total):
    if not total:
        return None
    return (Decimal(part) * 100 / Decimal(total)).quantize(
        _CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class NoShowLateCancelRate:
    salon: object = None
    start_date: object = None
    end_date: object = None
    total_appointments: int = 0
    completed: int = 0
    no_shows: int = 0
    cancelled: int = 0
    late_cancellations: int = 0
    no_show_rate_percent: Decimal | None = None
    late_cancel_rate_percent: Decimal | None = None

    @property
    def total(self):
        return self.total_appointments

    @property
    def completed_count(self):
        return self.completed

    @property
    def no_show_count(self):
        return self.no_shows

    @property
    def cancelled_count(self):
        return self.cancelled

    @property
    def late_cancel_count(self):
        return self.late_cancellations

    @property
    def late_cancellation_count(self):
        return self.late_cancellations

    @property
    def no_show_rate(self):
        return self.no_show_rate_percent

    @property
    def late_cancel_rate(self):
        return self.late_cancel_rate_percent

    @property
    def late_cancellation_rate_percent(self):
        return self.late_cancel_rate_percent

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "total_appointments": self.total_appointments,
            "total": self.total_appointments,
            "completed": self.completed,
            "no_shows": self.no_shows,
            "no_show_count": self.no_shows,
            "cancelled": self.cancelled,
            "late_cancellations": self.late_cancellations,
            "no_show_rate_percent": self.no_show_rate_percent,
            "late_cancel_rate_percent": self.late_cancel_rate_percent,
        }


#: Alias under the report naming used by sibling services.
NoShowRateReport = NoShowLateCancelRate


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def noshow_rate_report(salon, date_from=None, date_to=None, *,
                       start_date=None, end_date=None):
    """Return no-show / late-cancel rates for ``salon`` in a window.

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
        # Still validate the window shape before returning zeros.
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        first, last = _as_local_date(first_raw, tz), _as_local_date(last_raw, tz)
        if last < first:
            raise ValueError("end_date must be on or after start_date.")
        return NoShowLateCancelRate(
            salon=None, start_date=first, end_date=last)
    tz = _tz(salon)
    first = _as_local_date(first_raw, tz)
    last = _as_local_date(last_raw, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    counts = appointment_status_counts(salon, first, last)
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    late = Appointment.objects.filter(
        client__salon=salon, staff_member__salon=salon,
        status=Appointment.Status.CANCELLED,
        start__gte=window_start, start__lt=window_end,
        updated_at__gte=F("start"),
    ).count()
    total = counts.total
    no_shows = counts.no_show
    return NoShowLateCancelRate(
        salon=salon, start_date=first, end_date=last,
        total_appointments=total, completed=counts.completed,
        no_shows=no_shows, cancelled=counts.cancelled,
        late_cancellations=late,
        no_show_rate_percent=_pct(no_shows, total),
        late_cancel_rate_percent=_pct(late, total),
    )


#: Aliases matching common caller phrasing.
no_show_late_cancel_rate = noshow_rate_report
noshow_late_cancel_rate = noshow_rate_report
noshow_rate = noshow_rate_report
