"""Read-only reminder send-history summary service (L8-M7b).

Pure service module -- no views, no templates, no UI. Nothing is
sent, stored, or mutated here: every figure is derived from the
``ReminderSend`` rows that are the one source of truth for sends
actually dispatched (see :mod:`messaging.models`).

Opt-in state is not read or duplicated here; it lives only on
``clients.Client``. This module only counts history.

Public surface:

* :func:`reminder_history_summary` -- counts over an inclusive
  local-date range: ``total``, counts grouped ``by_channel``
  (every known channel present, zero-filled) and ``by_day``
  (every local day in the range present, zero-filled), plus
  ``by_day_by_channel`` for the cross-tab.
* :func:`counts_by_channel` / :func:`counts_by_day` -- the two
  groupings on their own.
* :func:`client_send_history` -- one client's sends, most
  recent first.

"Local day" means the day of ``sent_at`` in the currently active
timezone (``django.utils.timezone.localtime``), which is the
deployment timezone unless a caller activates another. Grouping
is done in Python rather than with database date-truncation
functions so the same code runs unchanged on every supported
backend.

A date range is inclusive at both ends. ``date`` arguments mean
whole local days; ``datetime`` arguments are reduced to their
local date, so a range always covers whole days. A reversed
range raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from clients.models import Client

from .models import ReminderSend

__all__ = [
    "ReminderHistorySummary",
    "client_send_history",
    "counts_by_channel",
    "counts_by_day",
    "per_client_history",
    "reminder_history",
    "reminder_history_summary",
    "send_history_summary",
    "sends_for_client",
]

CHANNELS = tuple(value for value, _label in ReminderSend.Channel.choices)


@dataclass(frozen=True)
class ReminderHistorySummary:
    """Send counts over one inclusive local-date range."""

    start_date: date = None
    end_date: date = None
    total: int = 0
    by_channel: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)
    by_day_by_channel: dict = field(default_factory=dict)

    @property
    def counts(self):
        """Alias for ``by_channel``."""
        return self.by_channel

    @property
    def by_date(self):
        """Alias for ``by_day``."""
        return self.by_day

    def count_for(self, channel):
        return self.by_channel.get(str(channel), 0)

    def as_dict(self):
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total": self.total,
            "by_channel": dict(self.by_channel),
            "by_day": dict(self.by_day),
            "by_day_by_channel": {
                day: dict(counts)
                for day, counts in self.by_day_by_channel.items()
            },
        }


def _as_local_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected a date or datetime, got {type(value).__name__}")


def _resolve_range(start, end, date_from, date_to, start_date, end_date):
    first = start if start is not None else date_from
    if first is None:
        first = start_date
    last = end if end is not None else date_to
    if last is None:
        last = end_date
    if first is None or last is None:
        raise TypeError(
            "a date range is required (start and end dates, or "
            "date_from=/date_to=)"
        )
    first = _as_local_date(first)
    last = _as_local_date(last)
    if last < first:
        raise ValueError("range end must not be before range start")
    return first, last


def _window(first, last):
    tz = timezone.get_current_timezone()
    start_dt = datetime.combine(first, time.min, tzinfo=tz)
    end_dt = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    return start_dt, end_dt


def _sends_between(first, last):
    start_dt, end_dt = _window(first, last)
    return ReminderSend.objects.filter(
        sent_at__gte=start_dt, sent_at__lt=end_dt
    )


def reminder_history_summary(
    start=None, end=None, *, date_from=None, date_to=None,
    start_date=None, end_date=None,
):
    """Return a :class:`ReminderHistorySummary` for a date range.

    Call as ``reminder_history_summary(first, last)`` or with
    ``date_from=`` / ``date_to=`` (``start_date=`` / ``end_date=``
    accepted as aliases). The range is inclusive and covers whole
    local days. An empty range yields a zeroed summary -- total
    ``0``, every channel ``0``, every day ``0`` -- never ``None``.
    """
    first, last = _resolve_range(
        start, end, date_from, date_to, start_date, end_date
    )
    by_channel = {channel: 0 for channel in CHANNELS}
    by_day = {}
    by_day_by_channel = {}
    day = first
    while day <= last:
        by_day[day] = 0
        by_day_by_channel[day] = {channel: 0 for channel in CHANNELS}
        day += timedelta(days=1)

    total = 0
    rows = _sends_between(first, last).values_list("channel", "sent_at")
    for channel, sent_at in rows.iterator():
        local_day = timezone.localtime(sent_at).date()
        if local_day not in by_day:
            continue
        channel = str(channel)
        by_channel[channel] = by_channel.get(channel, 0) + 1
        by_day[local_day] += 1
        per_channel = by_day_by_channel[local_day]
        per_channel[channel] = per_channel.get(channel, 0) + 1
        total += 1
    return ReminderHistorySummary(
        start_date=first, end_date=last, total=total,
        by_channel=by_channel, by_day=by_day,
        by_day_by_channel=by_day_by_channel,
    )


def counts_by_channel(start=None, end=None, **kwargs):
    """Return ``{channel: count}`` over the range, zero-filled."""
    return reminder_history_summary(start, end, **kwargs).by_channel


def counts_by_day(start=None, end=None, **kwargs):
    """Return ``{local_date: count}`` over the range, zero-filled."""
    return reminder_history_summary(start, end, **kwargs).by_day


def send_history_summary(start=None, end=None, **kwargs):
    """Alias for :func:`reminder_history_summary`."""
    return reminder_history_summary(start, end, **kwargs)


def reminder_history(start=None, end=None, **kwargs):
    """Alias for :func:`reminder_history_summary`."""
    return reminder_history_summary(start, end, **kwargs)


def client_send_history(client, limit=None):
    """Return one client's reminder sends, most recent first.

    ``client`` may be a ``clients.Client`` instance or a client
    id. Ordering is the model's ordering (``-sent_at``, ``-id``),
    so the newest send is first and ties break deterministically.
    A missing/unknown client yields an empty list, never ``None``.
    ``limit``, when given, caps the number of rows returned.
    """
    if client is None:
        return []
    client_id = client.pk if isinstance(client, Client) else client
    if client_id is None:
        return []
    queryset = ReminderSend.objects.filter(client_id=client_id)
    if limit is not None:
        queryset = queryset[: int(limit)]
    return list(queryset)


def sends_for_client(client, limit=None):
    """Alias for :func:`client_send_history`."""
    return client_send_history(client, limit=limit)


def per_client_history(client, limit=None):
    """Alias for :func:`client_send_history`."""
    return client_send_history(client, limit=limit)
