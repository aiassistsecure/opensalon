"""Repeat-visit retention: how many clients come back, from appointments.

Backend only — no views, templates, or UI. Nothing here is stored
or mutated: each figure is computed read-only from the
``Appointment`` rows in the bookings app, which are the one source
of truth for visits.

Definitions (the contract of this module)
-----------------------------------------
* A *visit* is one appointment whose status is ``completed``
  (``Appointment.Status.COMPLETED``) — nothing else. Booked,
  confirmed, arrived, and in-service appointments have not (yet)
  completed a visit, and cancelled and no-show appointments never
  count as visits.
* An appointment belongs to the salon via its staff member
  (``staff_member__salon``), as in :mod:`insights.services`, and
  to the calendar day of its ``start`` judged in the salon's
  timezone.
* The range is inclusive at both ends: an appointment starting
  on the start date or the end date (salon-local) counts.
* *Active clients* are the distinct clients with at least one
  visit in the range.
* *Repeat clients* are the distinct clients with at least two
  visits in the range — a subset of the active clients. A client
  who visited twice before the range, or once inside and once
  outside it, is not a repeat client for this range.
* *Repeat rate* is ``repeat_clients / active_clients`` as a float
  in ``[0.0, 1.0]``; it is ``0.0`` when there are no active
  clients, never ``None`` or a division error.
* *Average visits per active client* is
  ``total_visits / active_clients`` as a float; it is ``0.0``
  when there are no active clients.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Count

from bookings.models import Appointment

from .services import _as_date, _salon_tz


@dataclass(frozen=True)
class Retention:
    """Repeat-visit retention for one inclusive date window.

    ``start_date`` / ``end_date`` are the inclusive window bounds
    (salon-local dates). Counts are ints, rates are floats.
    """

    start_date: date
    end_date: date
    active_clients: int
    repeat_clients: int
    total_visits: int
    repeat_rate: float
    average_visits_per_active_client: float

    @property
    def active_client_count(self):
        return self.active_clients

    @property
    def clients_with_at_least_one_visit(self):
        return self.active_clients

    @property
    def repeat_client_count(self):
        return self.repeat_clients

    @property
    def clients_with_at_least_two_visits(self):
        return self.repeat_clients

    @property
    def repeat_visit_rate(self):
        return self.repeat_rate

    @property
    def retention_rate(self):
        return self.repeat_rate

    @property
    def average_visits(self):
        return self.average_visits_per_active_client

    @property
    def visits_per_active_client(self):
        return self.average_visits_per_active_client


# Aliases: the same result under other natural names.
RepeatVisitRetention = Retention
RetentionInsight = Retention


def repeat_visit_retention(salon, start=None, end=None, *,
                           start_date=None, end_date=None,
                           since=None, until=None):
    """Return repeat-visit retention for ``salon`` over a range.

    ``start`` / ``end`` are the inclusive range bounds (``date``
    objects, or ``datetime`` objects judged by their date in the
    salon's timezone, as in :func:`insights.services.busiest_days`);
    ``start_date`` / ``end_date`` and ``since`` / ``until`` are
    accepted as keyword aliases for the same bounds. Definitions
    are in this module's docstring.

    Returns a :class:`Retention`; a range with no visits — or a
    reversed range (``end`` before ``start``) — returns zeroes,
    never ``None``.
    """
    if start is None:
        start = start_date if start_date is not None else since
    if end is None:
        end = end_date if end_date is not None else until
    if start is None or end is None:
        raise TypeError(
            "repeat_visit_retention requires a start and an end date"
        )
    tz = _salon_tz(salon)
    start_day = _as_date(start, tz)
    end_day = _as_date(end, tz)
    if end_day < start_day:
        return Retention(
            start_date=start_day, end_date=end_day,
            active_clients=0, repeat_clients=0, total_visits=0,
            repeat_rate=0.0, average_visits_per_active_client=0.0,
        )
    start_dt = datetime.combine(start_day, time.min, tzinfo=tz)
    end_dt = datetime.combine(end_day + timedelta(days=1), time.min,
                              tzinfo=tz)
    per_client = (
        Appointment.objects.filter(
            staff_member__salon=salon,
            status=Appointment.Status.COMPLETED,
            start__gte=start_dt, start__lt=end_dt,
        )
        .values("client_id")
        .annotate(visits=Count("id"))
    )
    visit_counts = [row["visits"] for row in per_client]
    active = len(visit_counts)
    repeat = sum(1 for visits in visit_counts if visits >= 2)
    total = sum(visit_counts)
    return Retention(
        start_date=start_day,
        end_date=end_day,
        active_clients=active,
        repeat_clients=repeat,
        total_visits=total,
        repeat_rate=(repeat / active) if active else 0.0,
        average_visits_per_active_client=(
            (total / active) if active else 0.0
        ),
    )


# Aliases: the same service under other natural names.
retention = repeat_visit_retention
repeat_retention = repeat_visit_retention
get_repeat_visit_retention = repeat_visit_retention
