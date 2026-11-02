"""Prior-period comparison for campaign send totals.

Backend only, read-only. For an inclusive current window
``[start, end]`` of ``length`` days, the prior period is
``[start - length, start - 1 day]``. Figures for both windows
come verbatim from ``campaign_send_totals`` (``CampaignSend``,
scoped via ``campaign__salon``) -- never recounted here. Each
metric carries ``current``/``prior``/``delta``/``percent_change``
(Decimal, 2dp, ROUND_HALF_UP), ``None`` when prior is zero.
The comparison also carries ``by_channel_by_status`` and
``by_day_by_channel`` deltas, taken verbatim from
``campaign_send_totals``'s own breakdowns for both windows --
no new counting path here. ``by_day_by_channel`` is aligned
by day position within the window, exactly like ``by_day``
(a current day pairs with the prior day at the same offset),
and its cells are zero-filled to the union of both windows'
channels; ``by_channel_by_status`` is zero-filled to the
union of both windows' channels and statuses.
A reversed window or missing salon raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .campaign_send_totals import campaign_send_totals

__all__ = ["CountDelta", "MetricDelta", "PriorCampaignSendTotalsComparison",
           "prior_campaign_send_totals", "prior_period_campaign_send_totals",
           "compare_campaign_send_totals", "get_prior_campaign_send_totals"]
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class CountDelta:
    """One count in both periods, with its change."""

    component: str
    current: int = 0
    prior: int = 0
    delta: int = 0
    percent_change: Decimal | None = None

    @property
    def name(self): return self.component
    @property
    def previous(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


MetricDelta = CountDelta


def _delta(name, current, prior):
    current, prior = int(current), int(prior)
    pct = None if not prior else (
        (Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
    ).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return CountDelta(name, current, prior, current - prior, pct)


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass(frozen=True)
class PriorCampaignSendTotalsComparison:
    """Current vs prior campaign send totals for one salon."""

    salon: object = None
    start_date: date = None
    end_date: date = None
    prior_start_date: date = None
    prior_end_date: date = None
    current: object = None
    prior: object = None
    total: CountDelta = None
    by_channel: dict = field(default_factory=dict)
    by_status: dict = field(default_factory=dict)
    by_channel_by_status: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)
    by_day_by_channel: dict = field(default_factory=dict)

    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def days(self): return (self.end_date - self.start_date).days + 1
    @property
    def current_total(self): return self.total.current
    @property
    def prior_total(self): return self.total.prior
    @property
    def current_campaign(self): return self.current
    @property
    def prior_campaign(self): return self.prior
    @property
    def previous(self): return self.prior

    @property
    def deltas(self):
        return {"total": self.total, "by_channel": self.by_channel,
                "by_status": self.by_status,
                "by_channel_by_status": self.by_channel_by_status,
                "by_day": self.by_day,
                "by_day_by_channel": self.by_day_by_channel}

    def as_dict(self):
        by = lambda d: {str(k): v.as_dict() for k, v in d.items()}  # noqa: E731
        cross = {str(ch): by(cells) for ch, cells in
                 self.by_channel_by_status.items()}
        day_ch = {day.isoformat(): by(cells) for day, cells in
                  self.by_day_by_channel.items()}
        return {"salon_id": self.salon_id, "start_date": self.start_date,
                "end_date": self.end_date,
                "prior_start_date": self.prior_start_date,
                "prior_end_date": self.prior_end_date,
                "total": self.total.as_dict(),
                "by_channel": by(self.by_channel),
                "by_status": by(self.by_status),
                "by_channel_by_status": cross,
                "by_day": by(self.by_day),
                "by_day_by_channel": day_ch}


def prior_campaign_send_totals(salon, start=None, end=None, **kwargs):
    """Return the prior-period campaign send-totals comparison.

    Call as ``(salon, first, last)`` or ``(salon, day)`` for one
    day; ``date_from``/``date_to``, ``start_date``/``end_date``
    and ``since``/``until`` are accepted as aliases. Dates may be
    ``date``, ``datetime``, or ISO strings. Read-only.
    """
    if salon is None:
        raise ValueError("prior_campaign_send_totals needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "start_date", kwargs.pop("since", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "end_date", kwargs.pop("until", None)))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if start is None:
        raise ValueError("Both start_date and end_date are required.")
    if end is None:
        end = start
    tz = _tz(salon)
    first, last = _as_date(start, tz), _as_date(end, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    length = (last - first).days + 1
    p_end, p_start = first - timedelta(days=1), first - timedelta(days=length)
    cur = campaign_send_totals(salon, first, last)
    pri = campaign_send_totals(salon, p_start, p_end)

    def _union(cur_map, pri_map, prefix):
        keys = list(cur_map) + [k for k in pri_map if k not in cur_map]
        return {k: _delta(f"{prefix}_{k}", cur_map.get(k, 0),
                          pri_map.get(k, 0)) for k in keys}

    # Cross-tab: verbatim from the source's own
    # by_channel_by_status for both windows, zero-filled to
    # the union of both windows' channels and statuses.
    cross_channels = list(cur.by_channel_by_status) + [
        ch for ch in pri.by_channel_by_status
        if ch not in cur.by_channel_by_status]
    by_channel_by_status = {}
    for ch in cross_channels:
        cur_cells = cur.by_channel_by_status.get(ch, {})
        pri_cells = pri.by_channel_by_status.get(ch, {})
        statuses = list(cur_cells) + [
            s for s in pri_cells if s not in cur_cells]
        by_channel_by_status[ch] = {
            s: _delta(f"channel_{ch}_status_{s}",
                      cur_cells.get(s, 0), pri_cells.get(s, 0))
            for s in statuses}

    by_day = {}
    by_day_by_channel = {}
    cur_days = sorted(cur.by_day)
    for offset, day in enumerate(cur_days):
        prior_day = p_start + timedelta(days=offset)
        by_day[day] = _delta(f"day_{day.isoformat()}",
                             cur.by_day.get(day, 0),
                             pri.by_day.get(prior_day, 0))
        # By-day-by-channel: verbatim from the source's own
        # by_day_by_channel for both windows, offset-aligned
        # like by_day, zero-filled to the union of channels.
        cur_cells = cur.by_day_by_channel.get(day, {})
        pri_cells = pri.by_day_by_channel.get(prior_day, {})
        channels = list(cur_cells) + [
            ch for ch in pri_cells if ch not in cur_cells]
        by_day_by_channel[day] = {
            ch: _delta(f"day_{day.isoformat()}_{ch}",
                       cur_cells.get(ch, 0), pri_cells.get(ch, 0))
            for ch in channels}
    return PriorCampaignSendTotalsComparison(
        salon=salon, start_date=first, end_date=last,
        prior_start_date=p_start, prior_end_date=p_end,
        current=cur, prior=pri,
        total=_delta("total", cur.total, pri.total),
        by_channel=_union(cur.by_channel, pri.by_channel, "channel"),
        by_status=_union(cur.by_status, pri.by_status, "status"),
        by_channel_by_status=by_channel_by_status,
        by_day=by_day, by_day_by_channel=by_day_by_channel)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_campaign_send_totals = prior_campaign_send_totals
compare_campaign_send_totals = prior_campaign_send_totals
get_prior_campaign_send_totals = prior_campaign_send_totals
