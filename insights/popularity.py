"""Service popularity: appointments per service, split by status.

Backend only — no views, templates, or UI. Nothing here is stored
or mutated: each figure is computed read-only from the
``Appointment`` rows in the bookings app, which are the one source
of truth for appointments.

Definitions (the contract of this module)
-----------------------------------------
* An appointment belongs to the salon via its staff member
  (``staff_member__salon``), as in :mod:`insights.retention`, and
  to the calendar day of its ``start`` judged in the salon's
  timezone. The range is inclusive at both ends.
* The service name is resolved in one place, in this order: the
  linked service's name (``service.name`` via the FK) when a
  service is linked, otherwise the appointment's verbatim
  ``service_name`` snapshot, otherwise ``"Unknown service"``.
  Rows are grouped by linked service when present (two distinct
  services never merge, even with the same name); snapshot-only
  appointments group by their snapshot name.
* Status split — every appointment falls in exactly one bucket:

  - *completed*: ``Appointment.Status.COMPLETED``.
  - *booked*: every not-yet-completed, not-cancelled status —
    ``BOOKED``, ``CONFIRMED``, ``ARRIVED``, and ``IN_SERVICE``.
  - *cancelled/no-show*: ``CANCELLED`` and ``NO_SHOW`` combined
    in ``cancelled_no_show_count`` (the separate
    ``cancelled_count`` / ``no_show_count`` are also carried).

* Rows are ranked by ``completed_count`` descending, then
  ``total_count`` descending, then service name ascending.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from bookings.models import Appointment

from .services import _as_date, _salon_tz

UNKNOWN_SERVICE_NAME = "Unknown service"

BOOKED_STATUSES = frozenset({
    Appointment.Status.BOOKED,
    Appointment.Status.CONFIRMED,
    Appointment.Status.ARRIVED,
    Appointment.Status.IN_SERVICE,
})


@dataclass(frozen=True)
class ServicePopularity:
    """Appointment counts for one service in an inclusive window.

    ``service`` is the linked ``Service`` (``None`` for
    snapshot-only / unknown rows). ``service_name`` is the
    resolved display name (FK name, else snapshot, else
    ``"Unknown service"``). ``total_count`` is the sum of the
    three status buckets.
    """

    service: object | None
    service_name: str
    completed_count: int
    booked_count: int
    cancelled_no_show_count: int
    cancelled_count: int
    no_show_count: int

    @property
    def service_id(self):
        return self.service.pk if self.service is not None else None

    @property
    def name(self):
        return self.service_name

    @property
    def display_name(self):
        return self.service_name

    @property
    def completed(self):
        return self.completed_count

    @property
    def booked(self):
        return self.booked_count

    @property
    def cancelled_or_no_show_count(self):
        return self.cancelled_no_show_count

    @property
    def total_count(self):
        return (
            self.completed_count + self.booked_count
            + self.cancelled_no_show_count
        )

    @property
    def total(self):
        return self.total_count

    @property
    def appointment_count(self):
        return self.total_count


# Aliases: the same result under other natural names.
ServicePopularityRow = ServicePopularity
PopularityByService = ServicePopularity


def service_popularity(salon, start=None, end=None, *,
                       start_date=None, end_date=None,
                       since=None, until=None):
    """Return per-service popularity for ``salon`` over a range.

    ``start`` / ``end`` are inclusive bounds (``date`` objects, or
    ``datetime`` objects judged by their date in the salon's
    timezone, as in :func:`insights.retention.repeat_visit_retention`);
    ``start_date`` / ``end_date`` and ``since`` / ``until`` are
    accepted as keyword aliases. Definitions are in this module's
    docstring.

    Returns a list of :class:`ServicePopularity` rows — one per
    service with at least one appointment in the range — ranked
    by completed count descending. A range with no appointments —
    or a reversed range — returns an empty list, never ``None``.
    """
    if start is None:
        start = start_date if start_date is not None else since
    if end is None:
        end = end_date if end_date is not None else until
    if start is None or end is None:
        raise TypeError(
            "service_popularity requires a start and an end date"
        )
    tz = _salon_tz(salon)
    start_day = _as_date(start, tz)
    end_day = _as_date(end, tz)
    if end_day < start_day:
        return []
    start_dt = datetime.combine(start_day, time.min, tzinfo=tz)
    end_dt = datetime.combine(end_day + timedelta(days=1), time.min,
                              tzinfo=tz)
    appointments = (
        Appointment.objects.filter(
            staff_member__salon=salon,
            start__gte=start_dt, start__lt=end_dt,
        )
        .select_related("service")
        .order_by("start", "pk")
    )
    # key: ("service", pk) or ("snapshot", name)
    # -> [service, name, completed, booked, cancelled, no_show]
    buckets = {}
    for appt in appointments:
        if appt.service_id is not None:
            key = ("service", appt.service_id)
            service = appt.service
            name = (service.name if service is not None
                    else appt.service_name) or UNKNOWN_SERVICE_NAME
        else:
            name = appt.service_name or UNKNOWN_SERVICE_NAME
            key = ("snapshot", name)
            service = None
        bucket = buckets.setdefault(key, [service, name, 0, 0, 0, 0])
        if appt.status == Appointment.Status.COMPLETED:
            bucket[2] += 1
        elif appt.status == Appointment.Status.CANCELLED:
            bucket[4] += 1
        elif appt.status == Appointment.Status.NO_SHOW:
            bucket[5] += 1
        elif appt.status in BOOKED_STATUSES:
            bucket[3] += 1
        else:  # pragma: no cover - unknown status counts as booked
            bucket[3] += 1
    rows = [
        ServicePopularity(
            service=service, service_name=name,
            completed_count=completed, booked_count=booked,
            cancelled_no_show_count=cancelled + no_show,
            cancelled_count=cancelled, no_show_count=no_show,
        )
        for service, name, completed, booked, cancelled, no_show
        in buckets.values()
    ]
    rows.sort(key=lambda row: (
        -row.completed_count, -row.total_count, row.service_name,
    ))
    return rows


# Aliases: the same service under other natural names.
popularity_by_service = service_popularity
appointments_per_service = service_popularity
get_service_popularity = service_popularity
