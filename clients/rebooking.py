"""Rebooking-candidates service.

Pure service module — no views, no templates, no UI. Read-only:
nothing here creates, updates, deletes, or sends anything, and no
client contact details are ever logged or returned beyond the
client record itself.

:func:`rebooking_candidates` answers one question for a salon:
which clients are due to rebook as of a reference date?

Definition (all comparisons use the calendar date of an
appointment's ``start``, except when the reference is passed as a
datetime, in which case instants are compared):

* A client's *last completed visit* is the most recent
  appointment with status ``completed`` (see
  ``bookings.Appointment.Status``) on or before the reference
  date. Cancelled appointments never count, and neither do any
  other non-completed statuses (booked, confirmed, arrived,
  in-service, no-show): only a completed visit is a visit that
  can be rebooked from.
* The client qualifies when that last completed visit falls
  inside the lookback window: on or after
  ``reference_date - lookback_days`` and on or before the
  reference date. Both boundaries are inclusive — a visit exactly
  ``lookback_days`` before the reference date qualifies, and so
  does a visit on the reference date itself.
* The client is excluded when they already have a future /
  upcoming appointment: any non-cancelled appointment starting
  after the reference date (any status — booked, confirmed,
  completed-in-the-future, etc.). A cancelled future appointment
  does not exclude anyone.
* Clients of other salons are never included: ``salon`` is
  required and scopes every query.

Ordering: by most-recent completed visit ascending — the client
whose last visit is oldest (longest ago within the window, i.e.
most overdue to rebook) comes first — with client id as the
deterministic tie-break.

The ``Client.active`` flag is not a filter here; candidacy is
defined purely by appointments, exactly as documented above.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Exists, Max, OuterRef, Q
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client

__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "RebookingCandidate",
    "rebooking_candidates",
]

#: Default lookback window in days.
DEFAULT_LOOKBACK_DAYS = 42


@dataclass(frozen=True)
class RebookingCandidate:
    """One client due to rebook. See the module docstring."""

    client: Client
    client_id: int
    last_visit: datetime = None  # datetime | None
    days_since_last_visit: int = None  # int | None

    @property
    def last_visit_date(self):
        """Date of the last completed visit."""
        if self.last_visit is None:
            return None
        if isinstance(self.last_visit, datetime):
            return self.last_visit.date()
        return self.last_visit


def _clean_days(days):
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError("lookback window must be a non-negative integer")
    return days


def rebooking_candidates(salon, reference_date=None,
                         lookback_days=DEFAULT_LOOKBACK_DAYS, *,
                         window_days=None):
    """Return clients of ``salon`` who are due to rebook.

    Args:
        salon: the ``saloncore.Salon`` to scope to (required).
        reference_date: a ``date`` or aware ``datetime`` to
            measure from; defaults to today
            (``timezone.localdate()``).
        lookback_days: window size in days (default
            :data:`DEFAULT_LOOKBACK_DAYS`). ``window_days``, when
            given, takes precedence as an alias.

    Returns:
        A list of :class:`RebookingCandidate` ordered by last
        completed visit ascending (oldest first), then client id.
    """
    if window_days is not None:
        lookback_days = window_days
    lookback_days = _clean_days(lookback_days)
    if reference_date is None:
        reference_date = timezone.localdate()

    if isinstance(reference_date, datetime):
        ref = reference_date
        if timezone.is_naive(ref):
            ref = timezone.make_aware(ref)
        ref_date = ref.date()
        last_filter = Q(
            appointments__status=Appointment.Status.COMPLETED,
            appointments__start__gte=ref - timedelta(days=lookback_days),
            appointments__start__lte=ref,
        )
        future_qs = Appointment.objects.filter(
            client=OuterRef("pk"), start__gt=ref
        ).exclude(status=Appointment.Status.CANCELLED)
    else:
        ref_date = reference_date
        tz = timezone.get_current_timezone()
        window_start = datetime.combine(
            ref_date - timedelta(days=lookback_days), time.min, tzinfo=tz
        )
        window_end = datetime.combine(
            ref_date + timedelta(days=1), time.min, tzinfo=tz
        )
        last_filter = Q(
            appointments__status=Appointment.Status.COMPLETED,
            appointments__start__gte=window_start,
            appointments__start__lt=window_end,
        )
        future_qs = Appointment.objects.filter(
            client=OuterRef("pk"), start__gte=window_end
        ).exclude(status=Appointment.Status.CANCELLED)

    clients = (
        Client.objects.filter(salon=salon)
        .annotate(_last_completed=Max("appointments__start", filter=last_filter))
        .annotate(_has_future=Exists(future_qs))
        .filter(_last_completed__isnull=False, _has_future=False)
    )

    rows = []
    for client in clients:
        last = client._last_completed
        last_date = last.date() if isinstance(last, datetime) else last
        rows.append(
            RebookingCandidate(
                client=client,
                client_id=client.pk,
                last_visit=last,
                days_since_last_visit=(ref_date - last_date).days
                if isinstance(last_date, date)
                else None,
            )
        )

    # Most-recent visit ascending: oldest (most overdue) first.
    rows.sort(
        key=lambda row: (
            row.last_visit_date or date.min,
            row.client_id,
        )
    )
    return rows
