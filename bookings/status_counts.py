"""Read-only appointment status counts service.

Pure service module — no views, no templates, no UI. Derived only
from existing ``Appointment`` records (one source of truth);
nothing new is stored and nothing is mutated.

For one salon and one local date — or an inclusive local date
range — the result is::

    StatusCounts(
        salon,          # saloncore.Salon instance (or None)
        start_date,     # first local date counted (date)
        end_date,       # last local date counted, inclusive (date)
        total,          # all appointments counted (int)
        by_status,      # {status value: count} for EVERY status
    )

``by_status`` always carries every ``Appointment.Status`` value,
with ``0`` for statuses that have no appointments, so callers never
have to guess which keys exist. Any legacy status value outside
the current choices is also included (and counted in ``total``)
rather than silently dropped. Per-status attributes are available
directly (``result.booked``, ``result.completed``, ...) and via
``result["booked"]``; ``result.counts`` is an alias for
``by_status`` and ``result.as_dict()`` returns a plain dict.

Scoping follows :mod:`bookings.search`: appointments belong to the
salon via both the client and the staff member
(``client__salon`` and ``staff_member__salon``), never via the
service — an appointment may have ``service=None`` with only its
``service_name`` snapshot and still counts.

Day membership is by the appointment's ``start`` on the local
date, in the salon's timezone (via ``bookings.availability._tz``):
the window is ``[start of first day, start of the day after the
last day)`` in that timezone, compared on ``start``. An appointment
spanning midnight therefore counts once, on the day it starts.
Every status counts, including ``cancelled`` and ``no_show`` —
unlike the day-load service, this is a census of the book, not a
measure of occupied time.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count

from bookings.availability import _tz
from bookings.models import Appointment

__all__ = [
    "StatusCounts",
    "appointment_status_counts",
    "status_counts",
    "status_counts_for_day",
    "status_counts_for_range",
]


@dataclass(frozen=True)
class StatusCounts:
    salon: object = None
    start_date: date = None
    end_date: date = None
    total: int = 0
    by_status: dict = field(default_factory=dict)

    @property
    def counts(self):
        return self.by_status

    @property
    def date(self):
        """The single local date, when start and end coincide."""
        return self.start_date

    def __getitem__(self, status):
        return self.by_status.get(str(status), 0)

    def count_for(self, status):
        return self.by_status.get(str(status), 0)

    def as_dict(self):
        return {"total": self.total, **self.by_status}

    # One attribute per known status, defaulting to 0.
    @property
    def booked(self):
        return self.by_status.get(Appointment.Status.BOOKED, 0)

    @property
    def confirmed(self):
        return self.by_status.get(Appointment.Status.CONFIRMED, 0)

    @property
    def arrived(self):
        return self.by_status.get(Appointment.Status.ARRIVED, 0)

    @property
    def in_service(self):
        return self.by_status.get(Appointment.Status.IN_SERVICE, 0)

    @property
    def completed(self):
        return self.by_status.get(Appointment.Status.COMPLETED, 0)

    @property
    def cancelled(self):
        return self.by_status.get(Appointment.Status.CANCELLED, 0)

    @property
    def no_show(self):
        return self.by_status.get(Appointment.Status.NO_SHOW, 0)


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    return value


def _resolve_range(day, end_day, date_from, date_to, start_date, end_date):
    first = day
    if first is None:
        first = date_from if date_from is not None else start_date
    last = end_day
    if last is None:
        last = date_to if date_to is not None else end_date
    if first is None:
        raise TypeError(
            "appointment_status_counts requires a local date or a "
            "date range (day / date_from / start_date)"
        )
    if last is None:
        last = first
    return first, last


def appointment_status_counts(
    salon, day=None, end_day=None, *,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return status counts for ``salon`` on a local date or range.

    Call as ``appointment_status_counts(salon, day)`` for a single
    day, ``appointment_status_counts(salon, first, last)`` for an
    inclusive range, or with ``date_from=`` / ``date_to=``
    (``start_date=`` / ``end_date=`` accepted as aliases). Dates may
    be ``date`` objects or datetimes, which are reduced to their
    date in the salon's timezone. A reversed range returns zeros.

    Args:
        salon: ``saloncore.Salon`` instance to scope to. ``None``
            returns an all-zero result.

    Returns:
        A :class:`StatusCounts` with every status present.
    """
    # Resolve dates in the salon timezone when a salon is given.
    tz = _tz(salon) if salon is not None else None
    if tz is None:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
    first_raw, last_raw = _resolve_range(
        day, end_day, date_from, date_to, start_date, end_date
    )
    first = _as_local_date(first_raw, tz)
    last = _as_local_date(last_raw, tz)
    by_status = {value: 0 for value, _label in Appointment.Status.choices}
    if salon is None or last < first:
        return StatusCounts(
            salon=salon, start_date=first, end_date=last,
            total=0, by_status=by_status,
        )

    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(
        last + timedelta(days=1), time.min, tzinfo=tz
    )
    rows = (
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            start__gte=window_start, start__lt=window_end,
        )
        .values("status")
        .annotate(n=Count("id"))
    )
    total = 0
    for row in rows:
        n = int(row["n"])
        by_status[str(row["status"])] = (
            by_status.get(str(row["status"]), 0) + n
        )
        total += n
    return StatusCounts(
        salon=salon, start_date=first, end_date=last,
        total=total, by_status=by_status,
    )


def status_counts(salon, day=None, end_day=None, **kwargs):
    """Alias for :func:`appointment_status_counts`."""
    return appointment_status_counts(salon, day, end_day, **kwargs)


def status_counts_for_day(salon, day):
    """Status counts for one local date."""
    return appointment_status_counts(salon, day)


def status_counts_for_range(salon, date_from, date_to):
    """Status counts for an inclusive local date range."""
    return appointment_status_counts(salon, date_from, date_to)
