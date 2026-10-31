"""Read-only summary of cancelled online bookings (backend only).

Pure service: derived only from existing ``Appointment`` records;
nothing is created, updated, or deleted, and no provider code is
involved.

Scope — an appointment counts only when ALL hold:

* ``status == Appointment.Status.CANCELLED``
* ``origin == Appointment.Origin.ONLINE`` (the online-booking
  creation path sets this; phone / walk-in / unknown origins are
  excluded — see PR adding ``Appointment.origin``)
* it belongs to the salon via both client and staff member
  (``client__salon`` and ``staff_member__salon``, as in
  :mod:`bookings.status_counts`) — never via the service, so a
  snapshot-only appointment (``service=None``) still counts
* its ``start`` falls in the inclusive local date range, judged
  in the salon timezone (``bookings.availability._tz``): window
  ``[start of first day, start of day after last day)``, counted
  on the local day it starts.

Result::

    OnlineCancellationSummary(
        salon, start_date, end_date,
        total,       # int, == sum of every breakdown
        by_staff,    # tuple[StaffCancellation], count desc, name, id
        by_service,  # tuple[ServiceCancellation], count desc, name, id
        by_day,      # tuple[DayCancellation], date asc, zero-filled
    )

Service name is ``service.name`` when a service is linked,
otherwise the appointment's verbatim ``service_name`` snapshot
(``""`` when neither exists).
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from bookings.availability import _tz
from bookings.models import Appointment

__all__ = [
    "DayCancellation",
    "OnlineCancellationSummary",
    "CancellationSummary",
    "ServiceCancellation",
    "StaffCancellation",
    "cancellation_summary",
    "online_cancellation_summary",
    "online_cancellations_summary",
]


@dataclass(frozen=True)
class StaffCancellation:
    staff_member: object = None
    staff_member_id: int = None
    staff_display_name: str = ""
    count: int = 0

    @property
    def display_name(self):
        return self.staff_display_name

    @property
    def staff_name(self):
        return self.staff_display_name

    @property
    def name(self):
        return self.staff_display_name


@dataclass(frozen=True)
class ServiceCancellation:
    service: object = None
    service_id: int = None
    service_name: str = ""
    count: int = 0

    @property
    def name(self):
        return self.service_name


@dataclass(frozen=True)
class DayCancellation:
    date: object = None
    count: int = 0

    @property
    def day(self):
        return self.date


@dataclass(frozen=True)
class OnlineCancellationSummary:
    salon: object = None
    start_date: object = None
    end_date: object = None
    total: int = 0
    by_staff: tuple = field(default_factory=tuple)
    by_service: tuple = field(default_factory=tuple)
    by_day: tuple = field(default_factory=tuple)

    @property
    def total_count(self):
        return self.total

    @property
    def count(self):
        return self.total

    @property
    def cancelled_count(self):
        return self.total

    @property
    def by_date(self):
        return self.by_day

    @property
    def counts_by_staff(self):
        return {row.staff_member_id: row.count for row in self.by_staff}

    @property
    def counts_by_service(self):
        return {row.service_name: row.count for row in self.by_service}

    @property
    def counts_by_day(self):
        return {row.date: row.count for row in self.by_day}

    # Aliases as plain dicts keyed as above.
    by_staff_counts = counts_by_staff
    by_service_counts = counts_by_service
    by_day_counts = counts_by_day

    def count_for_staff(self, staff_member):
        pk = getattr(staff_member, "pk", staff_member)
        return self.counts_by_staff.get(pk, 0)

    def count_for_service(self, name):
        return self.counts_by_service.get(str(name), 0)

    def count_for_day(self, day):
        if isinstance(day, datetime):
            day = day.date()
        return self.counts_by_day.get(day, 0)

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "total": self.total,
            "by_staff": [
                {"staff_member_id": r.staff_member_id,
                 "staff_display_name": r.staff_display_name,
                 "count": r.count} for r in self.by_staff
            ],
            "by_service": [
                {"service_id": r.service_id,
                 "service_name": r.service_name,
                 "count": r.count} for r in self.by_service
            ],
            "by_day": [
                {"date": r.date.isoformat() if r.date else None,
                 "count": r.count} for r in self.by_day
            ],
        }


#: Short alias.
CancellationSummary = OnlineCancellationSummary


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def _service_name(appt):
    if appt.service is not None:
        return appt.service.name
    return appt.service_name or ""


def online_cancellation_summary(salon, date_from=None, date_to=None, *,
                                start_date=None, end_date=None, day=None,
                                end_day=None):
    """Summarise cancelled online bookings for ``salon`` in a range.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one day,
    or with ``date_from=``/``date_to=`` (``start_date=``/``end_date=``
    and ``day=``/``end_day=`` accepted). Dates may be dates or
    datetimes (reduced in the salon timezone). With no date at all,
    all matching appointments are summarised and the result's
    dates are ``None``. A reversed range or ``salon=None`` returns
    a zero summary (``by_day`` zero-filled when a range is given).
    """
    first_raw = date_from if date_from is not None else start_date
    if first_raw is None:
        first_raw = day
    last_raw = date_to if date_to is not None else end_date
    if last_raw is None:
        last_raw = end_day
    if last_raw is None:
        last_raw = first_raw

    if salon is None:
        return OnlineCancellationSummary(salon=None)
    tz = _tz(salon)
    first = _as_local_date(first_raw, tz) if first_raw is not None else None
    last = _as_local_date(last_raw, tz) if last_raw is not None else None

    by_day = ()
    if first is not None and last is not None:
        if last < first:
            return OnlineCancellationSummary(
                salon=salon, start_date=first, end_date=last, total=0)
        days = [first + timedelta(days=i)
                for i in range((last - first).days + 1)]
        by_day_counts = {d: 0 for d in days}
    else:
        by_day_counts = {}

    qs = Appointment.objects.filter(
        client__salon=salon, staff_member__salon=salon,
        status=Appointment.Status.CANCELLED,
        origin=Appointment.Origin.ONLINE,
    ).select_related("staff_member", "service")
    if first is not None:
        qs = qs.filter(
            start__gte=datetime.combine(first, time.min, tzinfo=tz),
            start__lt=datetime.combine(
                last + timedelta(days=1), time.min, tzinfo=tz),
        )

    staff, services = {}, {}
    total = 0
    for appt in qs.order_by("start", "pk"):
        total += 1
        local_day = appt.start.astimezone(tz).date() if appt.start.tzinfo else appt.start.date()
        by_day_counts[local_day] = by_day_counts.get(local_day, 0) + 1
        skey = appt.staff_member_id
        if skey not in staff:
            staff[skey] = StaffCancellation(
                staff_member=appt.staff_member, staff_member_id=skey,
                staff_display_name=appt.staff_member.display_name)
        staff[skey] = StaffCancellation(
            staff_member=staff[skey].staff_member, staff_member_id=skey,
            staff_display_name=staff[skey].staff_display_name,
            count=staff[skey].count + 1)
        name = _service_name(appt)
        vkey = (appt.service_id, name)
        if vkey not in services:
            services[vkey] = ServiceCancellation(
                service=appt.service, service_id=appt.service_id,
                service_name=name)
        services[vkey] = ServiceCancellation(
            service=services[vkey].service, service_id=appt.service_id,
            service_name=name, count=services[vkey].count + 1)

    by_staff = tuple(sorted(
        staff.values(),
        key=lambda r: (-r.count, r.staff_display_name, r.staff_member_id or 0)))
    by_service = tuple(sorted(
        services.values(),
        key=lambda r: (-r.count, r.service_name, r.service_id or 0)))
    by_day = tuple(DayCancellation(date=d, count=by_day_counts[d])
                   for d in sorted(by_day_counts))
    return OnlineCancellationSummary(
        salon=salon, start_date=first, end_date=last, total=total,
        by_staff=by_staff, by_service=by_service, by_day=by_day)


#: Aliases matching common caller phrasing.
cancellation_summary = online_cancellation_summary
online_cancellations_summary = online_cancellation_summary
