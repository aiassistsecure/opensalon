"""Inactive clients report service.

Pure service module — no views, no templates, no UI. Read-only:
nothing here creates, updates, deletes, or sends anything. This
is a report, not marketing: there is deliberately no messaging,
no opt-in handling, and no provider code of any kind here.

:func:`inactive_clients` lists clients with no non-cancelled
appointment in the last ``days`` days (default
:data:`DEFAULT_INACTIVE_DAYS`).

What counts as a visit:

* Only appointments in ``bookings.Appointment`` — the one source
  of truth for bookings — are considered, read-only.
* Cancelled appointments never count as a visit. Every other
  status (booked, confirmed, arrived, in-service, completed,
  no-show) does.
* A visit is a past appointment: ``start <= now``. A future
  booking is not a visit yet, so a client whose only
  appointments are in the future has no last visit (like a
  never-booked client) until one of them happens.
* ``last_appointment`` is the most recent such visit's start;
  ``last_appointment_date`` is its calendar date.

Threshold: a client is inactive when they have no visit, or
their last visit is before ``now - days``. A visit exactly
``days`` days before ``now`` is still within the window and the
client is *not* inactive. ``days_since_last_visit`` is the
calendar-day difference between ``now``'s date and the last
visit's date (``None`` for clients with no visit).

Ordering: never-visited clients first (they have been inactive
longest — indefinitely), then by last visit oldest first, with
client id as the deterministic tie-break.

Scope: pass ``salon`` to limit the report to one salon, or omit
it to report across all clients. The ``Client.active`` flag is
not a filter here — inactivity in this report is defined purely
by appointments, exactly as documented above.
"""
from dataclasses import dataclass
from datetime import date, datetime

from django.db.models import Max, Q
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client

__all__ = [
    "DEFAULT_INACTIVE_DAYS",
    "InactiveClient",
    "inactive_clients",
    "inactive_client_report",
]

#: Default inactivity window: no visit in the last 90 days.
DEFAULT_INACTIVE_DAYS = 90


@dataclass(frozen=True)
class InactiveClient:
    """One inactive client row. See the module docstring."""

    client: Client
    client_id: int
    last_appointment: datetime = None  # datetime | None
    days_since_last_visit: int = None  # int | None

    @property
    def last_appointment_date(self):
        """Date of the last visit (``None`` when never visited)."""
        if self.last_appointment is None:
            return None
        if isinstance(self.last_appointment, datetime):
            return self.last_appointment.date()
        return self.last_appointment

    @property
    def last_visit_date(self):
        """Alias for :attr:`last_appointment_date`."""
        return self.last_appointment_date

    @property
    def last_visit(self):
        """Alias for :attr:`last_appointment`."""
        return self.last_appointment

    @property
    def days_since(self):
        """Alias for :attr:`days_since_last_visit`."""
        return self.days_since_last_visit


def _clean_days(days):
    if days is None:
        return DEFAULT_INACTIVE_DAYS
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError("days must be a non-negative integer or None")
    return days


def inactive_clients(salon=None, days=DEFAULT_INACTIVE_DAYS, *, now=None,
                     threshold_days=None):
    """Return inactive clients, most inactive first.

    Args:
        salon: optional ``saloncore.Salon`` to scope the report
            to; when ``None`` (default) all clients are considered.
        days: inactivity window in days (default
            :data:`DEFAULT_INACTIVE_DAYS`). ``threshold_days``,
            when given, takes precedence as an alias.
        now: reference instant; defaults to ``timezone.now()``.
            Pass an aware datetime in tests for a deterministic
            boundary.

    Returns:
        A list of :class:`InactiveClient` ordered never-visited
        first, then last visit oldest first, then client id.
        Each row carries ``client_id``, ``last_appointment_date``
        (``None`` for never-booked / no past visit), and
        ``days_since_last_visit`` (``None`` in the same case).
    """
    if threshold_days is not None:
        days = threshold_days
    days = _clean_days(days)
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=days)
    today = now.date() if isinstance(now, datetime) else now

    clients = Client.objects.all()
    if salon is not None:
        clients = clients.filter(salon=salon)
    clients = clients.annotate(
        _last_visit=Max(
            "appointments__start",
            filter=Q(appointments__start__lte=now)
            & ~Q(appointments__status=Appointment.Status.CANCELLED),
        )
    ).filter(Q(_last_visit__isnull=True) | Q(_last_visit__lt=cutoff))

    rows = []
    for client in clients:
        last = client._last_visit
        if last is None:
            days_since = None
            last_date = None
        else:
            last_date = last.date() if isinstance(last, datetime) else last
            days_since = (today - last_date).days if isinstance(
                today, date
            ) else None
        rows.append(
            InactiveClient(
                client=client,
                client_id=client.pk,
                last_appointment=last,
                days_since_last_visit=days_since,
            )
        )

    # Never-visited first, then oldest last visit first, then id.
    rows.sort(
        key=lambda row: (
            row.last_appointment is not None,
            row.last_appointment_date or date.min,
            row.client_id,
        )
    )
    return rows


# Alias matching the report nature of the service.
inactive_client_report = inactive_clients
