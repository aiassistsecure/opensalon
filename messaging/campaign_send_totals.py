"""Read-only per-salon campaign send totals summary.

Pure aggregation service -- no views, no templates, no UI.
Nothing is sent, stored, or mutated here, and no provider
adapter is touched: every figure is derived from the
``CampaignSend`` rows that are the one source of truth for
campaign messages actually dispatched (see
:mod:`messaging.models`).

Mirrors :mod:`messaging.send_totals` (which aggregates
``ReminderSend``), scoped to ONE salon. ``CampaignSend`` has no
salon foreign key of its own, so a send belongs to a salon via
its campaign: ``campaign__salon``. Sends for other salons are
never counted.

Public surface:

* :func:`campaign_send_totals` -- totals for a salon over an
  inclusive local-date range: ``total``, ``by_channel`` (every
  ``Campaign.Channel`` value present, zero-filled), ``by_status``
  (every ``CampaignSend.Status`` value present, zero-filled),
  ``by_channel_by_status`` cross-tab, ``by_day`` (every local
  day in the range present, zero-filled) and
  ``by_day_by_channel``.
* :func:`per_channel_campaign_send_totals` /
  :func:`campaign_send_totals_summary` -- aliases.

"Local day" means the day of ``sent_at`` in the salon's timezone
(``Salon.timezone``, falling back to UTC), matching
:mod:`messaging.send_totals`. Grouping is done in Python rather
than with database date-truncation functions so the same code
runs unchanged on every backend.

A date range is inclusive at both ends. ``date`` arguments mean
whole local days; ``datetime`` arguments are reduced to their
local date. A reversed range raises ``ValueError``. ``salon=None``
yields a zeroed summary, never ``None``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Campaign, CampaignSend

__all__ = [
    "CampaignSendTotals",
    "campaign_send_totals",
    "campaign_send_totals_summary",
    "per_channel_campaign_send_totals",
]

CHANNELS = tuple(value for value, _label in Campaign.Channel.choices)
STATUSES = tuple(value for value, _label in CampaignSend.Status.choices)


@dataclass(frozen=True)
class CampaignSendTotals:
    """Per-channel campaign send totals for one salon over one range."""

    salon: object = None
    start_date: date = None
    end_date: date = None
    total: int = 0
    by_channel: dict = field(default_factory=dict)
    by_status: dict = field(default_factory=dict)
    by_channel_by_status: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)
    by_day_by_channel: dict = field(default_factory=dict)

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def by_date(self):
        """Alias for ``by_day``."""
        return self.by_day

    @property
    def counts(self):
        """Alias for ``by_channel``."""
        return self.by_channel

    def count_for(self, channel):
        return self.by_channel.get(str(channel), 0)

    def status_count(self, status):
        return self.by_status.get(str(status), 0)

    def as_dict(self):
        return {
            "salon_id": self.salon_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total": self.total,
            "by_channel": dict(self.by_channel),
            "by_status": dict(self.by_status),
            "by_channel_by_status": {
                channel: dict(counts)
                for channel, counts in self.by_channel_by_status.items()
            },
            "by_day": dict(self.by_day),
            "by_day_by_channel": {
                day: dict(counts)
                for day, counts in self.by_day_by_channel.items()
            },
        }


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected a date or datetime, got {type(value).__name__}")


def _resolve_range(start, end, date_from, date_to, start_date, end_date, tz):
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
    first = _as_local_date(first, tz)
    last = _as_local_date(last, tz)
    if last < first:
        raise ValueError("range end must not be before range start")
    return first, last


def _zeroed(first, last):
    by_day, by_day_by_channel = {}, {}
    day = first
    while day <= last:
        by_day[day] = 0
        by_day_by_channel[day] = {channel: 0 for channel in CHANNELS}
        day += timedelta(days=1)
    return by_day, by_day_by_channel


def campaign_send_totals(
    salon, start=None, end=None, *,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return :class:`CampaignSendTotals` for ``salon`` over a range.

    Call as ``campaign_send_totals(salon, first, last)`` or with
    ``date_from=`` / ``date_to=`` (``start_date=`` / ``end_date=``
    accepted as aliases). The range is inclusive and covers whole
    local days in the salon's timezone. An empty range yields a
    zeroed summary -- total ``0``, every channel/status ``0``,
    every day ``0`` -- never ``None``. Read-only.
    """
    tz = _tz(salon)
    first, last = _resolve_range(
        start, end, date_from, date_to, start_date, end_date, tz
    )
    by_channel = {channel: 0 for channel in CHANNELS}
    by_status = {status: 0 for status in STATUSES}
    by_channel_by_status = {
        channel: {status: 0 for status in STATUSES} for channel in CHANNELS
    }
    by_day, by_day_by_channel = _zeroed(first, last)
    if salon is None:
        return CampaignSendTotals(
            salon=None, start_date=first, end_date=last, total=0,
            by_channel=by_channel, by_status=by_status,
            by_channel_by_status=by_channel_by_status,
            by_day=by_day, by_day_by_channel=by_day_by_channel,
        )

    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    rows = CampaignSend.objects.filter(
        campaign__salon=salon,
        sent_at__gte=window_start, sent_at__lt=window_end,
    ).values_list("channel", "status", "sent_at")

    total = 0
    for channel, status, sent_at in rows.iterator():
        local_day = sent_at.astimezone(tz).date() if sent_at.tzinfo else sent_at.date()
        if local_day not in by_day:
            continue
        channel, status = str(channel), str(status)
        by_channel[channel] = by_channel.get(channel, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        cross = by_channel_by_status.setdefault(
            channel, {s: 0 for s in STATUSES}
        )
        cross[status] = cross.get(status, 0) + 1
        by_day[local_day] += 1
        per_channel = by_day_by_channel[local_day]
        per_channel[channel] = per_channel.get(channel, 0) + 1
        total += 1
    return CampaignSendTotals(
        salon=salon, start_date=first, end_date=last, total=total,
        by_channel=by_channel, by_status=by_status,
        by_channel_by_status=by_channel_by_status,
        by_day=by_day, by_day_by_channel=by_day_by_channel,
    )


def per_channel_campaign_send_totals(salon, start=None, end=None, **kwargs):
    """Alias for :func:`campaign_send_totals`."""
    return campaign_send_totals(salon, start, end, **kwargs)


def campaign_send_totals_summary(salon, start=None, end=None, **kwargs):
    """Alias for :func:`campaign_send_totals`."""
    return campaign_send_totals(salon, start, end, **kwargs)
