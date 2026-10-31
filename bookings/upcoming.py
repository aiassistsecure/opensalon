"""Upcoming appointments service for a salon.

Pure read-only service module — no views, no templates, no UI,
no writes. Derived only from existing ``Appointment`` records
(one source of truth); nothing new is stored.

For one salon, a start datetime, and a horizon of ``days`` days,
the window is the half-open interval
``[start, start + days)`` compared on the appointment's ``start``.
The result is::

    UpcomingAppointments(
        salon,          # saloncore.Salon instance (or None)
        start,          # aware datetime, window start (inclusive)
        end,            # aware datetime, window end (exclusive)
        days,           # horizon length in days, as resolved
        total,          # number of appointments in the window
        appointments,   # tuple of UpcomingAppointment, by start
        by_day,         # tuple of DayUpcoming, by local date
        by_staff,       # tuple of StaffUpcoming, by display name
    )

Each appointment entry carries::

    UpcomingAppointment(
        appointment_id, client, staff_member,
        client_display_name,   # str(client): "First Last"
        service_name,          # Service.name, else the
                               # appointment's service_name snapshot
        service_category_name, # ServiceCategory.name, "" if none
        start, end,            # aware datetimes, as stored
        status,                # Appointment.status value
    )

Cancelled appointments are excluded: they do not occupy the book
(the same rule :mod:`bookings.daybook`, :mod:`bookings.staff_day`
and :mod:`bookings.availability` apply). Every other status is
included, with ``status`` carried through for callers to style or
filter. Scoping follows :mod:`bookings.search`: appointments
belong to the salon via both the client and the staff member
(``client__salon`` and ``staff_member__salon``), never via the
service, so snapshot-only appointments (``service=None``) are
included with their snapshot name.

Grouping: ``by_day`` groups by the appointment's local date in
the salon's timezone (via ``bookings.availability._tz``) and
``by_staff`` by staff member; both contain only days / staff
with at least one appointment in the window, ordered by date
and by display name respectively, each entry carrying its
``count`` and its appointments (ordered by start). Convenience
dicts ``counts_by_day`` (``{date: int}``) and ``counts_by_staff``
(``{staff_member_id: int}``) are derived from those groups.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from bookings.availability import _tz
from bookings.models import Appointment

__all__ = [
    "DayUpcoming",
    "StaffUpcoming",
    "UpcomingAppointment",
    "UpcomingAppointments",
    "list_upcoming",
    "salon_upcoming_appointments",
    "upcoming_appointments",
]

DEFAULT_DAYS = 7


@dataclass(frozen=True)
class UpcomingAppointment:
    appointment_id: int
    client: object
    staff_member: object
    client_display_name: str
    service_name: str
    service_category_name: str
    start: datetime
    end: datetime
    status: str

    @property
    def client_id(self):
        return self.client.pk if self.client is not None else None

    @property
    def staff_member_id(self):
        return self.staff_member.pk if self.staff_member is not None else None

    @property
    def staff_display_name(self):
        return self.staff_member.display_name if self.staff_member else ""


@dataclass(frozen=True)
class DayUpcoming:
    date: date
    count: int = 0
    appointments: tuple = field(default_factory=tuple)

    @property
    def day(self):
        return self.date


@dataclass(frozen=True)
class StaffUpcoming:
    staff_member: object
    count: int = 0
    appointments: tuple = field(default_factory=tuple)

    @property
    def staff_member_id(self):
        return self.staff_member.pk if self.staff_member is not None else None

    @property
    def display_name(self):
        return self.staff_member.display_name if self.staff_member else ""


@dataclass(frozen=True)
class UpcomingAppointments:
    salon: object = None
    start: datetime = None
    end: datetime = None
    days: int = DEFAULT_DAYS
    total: int = 0
    appointments: tuple = field(default_factory=tuple)
    by_day: tuple = field(default_factory=tuple)
    by_staff: tuple = field(default_factory=tuple)

    @property
    def count(self):
        return self.total

    @property
    def counts_by_day(self):
        return {entry.date: entry.count for entry in self.by_day}

    @property
    def counts_by_staff(self):
        return {entry.staff_member_id: entry.count for entry in self.by_staff}


def _resolve_start(value, tz):
    """Resolve ``value`` to an aware datetime in the salon timezone."""
    if value is None:
        return timezone.now()
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=tz)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=tz)
    return value


def upcoming_appointments(salon, start=None, days=DEFAULT_DAYS, *,
                          horizon_days=None, start_datetime=None, now=None):
    """Return ``salon``'s upcoming appointments within a horizon.

    Args:
        salon: ``saloncore.Salon`` instance to scope to. ``None``
            returns an empty result.
        start: aware datetime the horizon opens at (inclusive);
            a plain ``date`` means that day's start in the salon
            timezone, and a naive datetime is read in that timezone.
            Defaults to ``timezone.now()``.
        days: horizon length in days (default 7); the window is
            ``[start, start + days)`` on appointment ``start``.
            ``horizon_days`` is an alias and wins when given.
            ``days <= 0`` returns an empty result.
        now: alias for ``start`` when ``start`` is not given.

    Returns:
        An :class:`UpcomingAppointments` whose appointments are
        the salon's non-cancelled appointments in the window,
        ordered by ``start`` (then ``pk``), grouped by local day
        and by staff member.
    """
    if horizon_days is not None:
        days = horizon_days
    if start is None:
        start = start_datetime if start_datetime is not None else now
    tz = _tz(salon) if salon is not None else None
    if tz is None:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
    window_start = _resolve_start(start, tz)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    window_end = window_start + timedelta(days=max(days, 0))
    empty = UpcomingAppointments(
        salon=salon, start=window_start, end=window_end, days=days,
    )
    if salon is None or days <= 0:
        return empty

    rows = (
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            start__gte=window_start, start__lt=window_end,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related(
            "client", "staff_member", "service", "service__category"
        )
        .order_by("start", "pk")
    )
    entries = tuple(
        UpcomingAppointment(
            appointment_id=appt.pk,
            client=appt.client,
            staff_member=appt.staff_member,
            client_display_name=str(appt.client),
            service_name=(
                appt.service.name if appt.service else appt.service_name
            ),
            service_category_name=(
                appt.service.category.name if appt.service else ""
            ),
            start=appt.start,
            end=appt.end,
            status=appt.status,
        )
        for appt in rows
    )
    by_date, by_member = {}, {}
    for entry in entries:
        local_day = entry.start.astimezone(tz).date()
        by_date.setdefault(local_day, []).append(entry)
        by_member.setdefault(entry.staff_member_id, []).append(entry)
    by_day = tuple(
        DayUpcoming(date=day, count=len(items), appointments=tuple(items))
        for day, items in sorted(by_date.items())
    )
    staff_entries = sorted(
        by_member.values(),
        key=lambda items: (items[0].staff_display_name, items[0].staff_member_id),
    )
    by_staff = tuple(
        StaffUpcoming(
            staff_member=items[0].staff_member,
            count=len(items), appointments=tuple(items),
        )
        for items in staff_entries
    )
    return UpcomingAppointments(
        salon=salon, start=window_start, end=window_end, days=days,
        total=len(entries), appointments=entries,
        by_day=by_day, by_staff=by_staff,
    )


def salon_upcoming_appointments(salon, start=None, days=DEFAULT_DAYS, **kw):
    """Alias for :func:`upcoming_appointments`."""
    return upcoming_appointments(salon, start, days, **kw)


def list_upcoming(salon, start=None, days=DEFAULT_DAYS, **kw):
    """Return just the appointment entries, ordered by start."""
    return upcoming_appointments(salon, start, days, **kw).appointments
