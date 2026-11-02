"""New clients per period (first-visit) report service.

Pure service module — no views, no templates, no UI. Read-only.

:func:`new_clients` lists clients whose *first visit* falls inside
a given inclusive date window. A first visit is the start of the
client's earliest non-cancelled appointment in
``bookings.Appointment`` — the one source of truth for bookings
(the same read :mod:`clients.summary` makes). Cancelled
appointments never count; every other status does. Because the
first visit is the earliest non-cancelled appointment, a result
client by construction has NO earlier non-cancelled appointment
before the window; an earlier *cancelled* one does not block
newness, and a cancelled appointment inside the window does not
become the first visit when a later non-cancelled one exists.

``Client.created_at`` is deliberately NOT used: imported clients
carry the import date, so keying on it would make every imported
client look new at import time.

Dates mean whole days: ``[start_date, end_date]`` inclusive at
both ends, in the salon's timezone when a salon is given, else
the current timezone. ``datetime`` / ISO string arguments are
reduced to their date there. A reversed or incomplete window
raises ``ValueError``. Ordering: first visit, then client id.
Scope: pass ``salon`` to limit to one salon, or omit it for all.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Min, Q
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client

__all__ = [
    "NewClient",
    "new_clients",
    "new_client_count",
    "new_clients_in_period",
]


@dataclass(frozen=True)
class NewClient:
    """One new client row. See the module docstring."""

    client: Client
    client_id: int
    first_appointment: datetime = None  # datetime | None

    @property
    def first_appointment_date(self):
        if self.first_appointment is None:
            return None
        if isinstance(self.first_appointment, datetime):
            return self.first_appointment.date()
        return self.first_appointment

    @property
    def first_visit(self):
        return self.first_appointment

    @property
    def first_visit_date(self):
        return self.first_appointment_date


def _tz_for(salon):
    name = getattr(salon, "timezone", None) if salon is not None else None
    if name:
        try:
            return ZoneInfo(str(name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            pass
    return timezone.get_current_timezone()


def _as_date(value, tz):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            parsed = datetime.fromisoformat(value.strip())
            return _as_date(parsed, tz)
    raise TypeError(f"expected a date or datetime, got {type(value).__name__}")


def _resolve(salon, start_date, end_date, kwargs):
    start = start_date
    if start is None:
        for key in ("start", "period_start", "date_from", "since"):
            start = kwargs.pop(key, None)
            if start is not None:
                break
    end = end_date
    if end is None:
        for key in ("end", "period_end", "date_to", "until"):
            end = kwargs.pop(key, None)
            if end is not None:
                break
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("Both start_date and end_date are required.")
    tz = _tz_for(salon)
    first = _as_date(start, tz)
    last = _as_date(end, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    return window_start, window_end


def new_clients(salon=None, start_date=None, end_date=None, **kwargs):
    """Return clients whose first visit falls in the window.

    Args:
        salon: optional ``saloncore.Salon`` to scope to.
        start_date / end_date: inclusive window bounds (``date``,
            ``datetime``, or ISO string; ``start`` / ``end``,
            ``period_start`` / ``period_end`` and ``date_from`` /
            ``date_to`` are accepted as keyword aliases).

    Returns:
        A list of :class:`NewClient` ordered by first visit, then
        client id. Each row's ``first_appointment`` is that
        client's earliest non-cancelled appointment start.
    """
    window_start, window_end = _resolve(salon, start_date, end_date, kwargs)
    clients = Client.objects.all()
    if salon is not None:
        clients = clients.filter(salon=salon)
    clients = clients.annotate(
        _first_visit=Min(
            "appointments__start",
            filter=~Q(appointments__status=Appointment.Status.CANCELLED),
        )
    ).filter(_first_visit__gte=window_start, _first_visit__lt=window_end)
    rows = [
        NewClient(client=c, client_id=c.pk, first_appointment=c._first_visit)
        for c in clients
    ]
    rows.sort(key=lambda r: (r.first_appointment, r.client_id))
    return rows


def new_client_count(salon=None, start_date=None, end_date=None, **kwargs):
    """Return how many clients are new in the window."""
    return len(new_clients(salon, start_date, end_date, **kwargs))


#: Alias matching the report's name.
new_clients_in_period = new_clients
