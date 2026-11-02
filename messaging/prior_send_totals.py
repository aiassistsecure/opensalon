"""Prior-period comparison for messaging send totals.

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated, and no provider adapter is touched.
Mirrors sibling prior-period services: for an inclusive current
window ``[start, end]`` of ``length`` days, the prior period is
``[start - length, start - 1 day]``. Figures for both windows
come verbatim from :func:`messaging.send_totals.send_totals`
(``ReminderSend``) and
:func:`messaging.campaign_send_totals.campaign_send_totals`
(``CampaignSend``) -- never recounted here. Each metric carries
``current``, ``prior``, ``delta`` and ``percent_change``
(Decimal, two places, ROUND_HALF_UP), ``None`` when prior is
zero. The reminder side also carries ``by_day`` /
``by_day_by_channel`` deltas, taken verbatim from
``send_totals``'s own ``by_day`` and ``by_day_by_channel``
fields for both windows, zero-filled to the union of both
windows' days (a day present in only one window pairs with
``0`` on the other side). Both sides also carry
``by_status`` and ``by_channel_by_status`` deltas, and the
campaign side also carries ``by_day`` / ``by_day_by_channel``
deltas, taken verbatim from the two source services' own
``by_status``, ``by_channel_by_status``, ``by_day`` and
``by_day_by_channel`` fields for both windows, zero-filled
to the union of both windows' statuses, channels and days. The combined view
also carries ``combined_by_status``,
``combined_by_channel_by_status``, ``combined_by_day`` and
``combined_by_day_by_channel`` deltas, built by summing the
two sources' own breakdowns cell-by-cell for both windows
exactly as ``combined_by_channel`` already does.
No ``history.py`` wrapper is used
-- history stays salon-agnostic and unconsumed by
comparisons, and sourcing from ``send_totals`` keeps exactly
one counting path for ``ReminderSend`` rows. A reversed
window or missing salon raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .campaign_send_totals import campaign_send_totals
from .send_totals import send_totals

__all__ = ["CountDelta", "MetricDelta", "PriorSendTotalsComparison",
           "prior_send_totals", "prior_period_send_totals",
           "compare_send_totals", "get_prior_send_totals"]
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
class PriorSendTotalsComparison:
    """Current vs prior send totals (reminder + campaign)."""

    salon: object = None
    start_date: date = None
    end_date: date = None
    prior_start_date: date = None
    prior_end_date: date = None
    current_reminder: object = None
    prior_reminder: object = None
    current_campaign: object = None
    prior_campaign: object = None
    total: CountDelta = None
    reminder_total: CountDelta = None
    campaign_total: CountDelta = None
    reminder_by_channel: dict = field(default_factory=dict)
    campaign_by_channel: dict = field(default_factory=dict)
    combined_by_channel: dict = field(default_factory=dict)
    reminder_by_day: dict = field(default_factory=dict)
    reminder_by_day_by_channel: dict = field(default_factory=dict)
    reminder_by_status: dict = field(default_factory=dict)
    campaign_by_status: dict = field(default_factory=dict)
    reminder_by_channel_by_status: dict = field(default_factory=dict)
    campaign_by_channel_by_status: dict = field(default_factory=dict)
    campaign_by_day: dict = field(default_factory=dict)
    campaign_by_day_by_channel: dict = field(default_factory=dict)
    combined_by_status: dict = field(default_factory=dict)
    combined_by_channel_by_status: dict = field(default_factory=dict)
    combined_by_day: dict = field(default_factory=dict)
    combined_by_day_by_channel: dict = field(default_factory=dict)

    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def days(self): return (self.end_date - self.start_date).days + 1
    @property
    def current_total(self): return self.total.current
    @property
    def prior_total(self): return self.total.prior

    current = property(lambda self: self.current_reminder)  # noqa: E731
    prior = property(lambda self: self.prior_reminder)  # noqa: E731
    previous = property(lambda self: self.prior_reminder)  # noqa: E731

    @property
    def by_day(self):
        """Alias for ``reminder_by_day`` (the reminder side)."""
        return self.reminder_by_day

    @property
    def by_day_by_channel(self):
        """Alias for ``reminder_by_day_by_channel``."""
        return self.reminder_by_day_by_channel

    @property
    def by_status(self):
        """Reminder ``by_status`` deltas (the reminder side)."""
        return self.reminder_by_status

    @property
    def by_channel_by_status(self):
        """Reminder cross-tab deltas (the reminder side)."""
        return self.reminder_by_channel_by_status

    @property
    def deltas(self):
        return {"total": self.total, "reminder_total": self.reminder_total,
                "campaign_total": self.campaign_total,
                "reminder_by_channel": self.reminder_by_channel,
                "campaign_by_channel": self.campaign_by_channel,
                "combined_by_channel": self.combined_by_channel,
                "reminder_by_day": self.reminder_by_day,
                "reminder_by_day_by_channel":
                    self.reminder_by_day_by_channel,
                "by_day": self.reminder_by_day,
                "by_day_by_channel": self.reminder_by_day_by_channel,
                "reminder_by_status": self.reminder_by_status,
                "campaign_by_status": self.campaign_by_status,
                "by_status": self.reminder_by_status,
                "reminder_by_channel_by_status":
                    self.reminder_by_channel_by_status,
                "campaign_by_channel_by_status":
                    self.campaign_by_channel_by_status,
                "by_channel_by_status":
                    self.reminder_by_channel_by_status,
                "campaign_by_day": self.campaign_by_day,
                "campaign_by_day_by_channel":
                    self.campaign_by_day_by_channel,
                "combined_by_status": self.combined_by_status,
                "combined_by_channel_by_status":
                    self.combined_by_channel_by_status,
                "combined_by_day": self.combined_by_day,
                "combined_by_day_by_channel":
                    self.combined_by_day_by_channel}

    def as_dict(self):
        by = lambda d: {k: v.as_dict() for k, v in d.items()}  # noqa: E731
        by_day = {d.isoformat(): v.as_dict()
                  for d, v in self.reminder_by_day.items()}
        by_day_by_channel = {
            d.isoformat(): by(cells)
            for d, cells in self.reminder_by_day_by_channel.items()}
        cross = lambda d: {str(k): by(v) for k, v in d.items()}  # noqa: E731
        campaign_by_day = {d.isoformat(): v.as_dict()
                           for d, v in self.campaign_by_day.items()}
        campaign_by_day_by_channel = {
            d.isoformat(): by(cells)
            for d, cells in self.campaign_by_day_by_channel.items()}
        combined_by_day = {d.isoformat(): v.as_dict()
                           for d, v in self.combined_by_day.items()}
        combined_by_day_by_channel = {
            d.isoformat(): by(cells)
            for d, cells in self.combined_by_day_by_channel.items()}
        return {"salon_id": self.salon_id, "start_date": self.start_date,
                "end_date": self.end_date,
                "prior_start_date": self.prior_start_date,
                "prior_end_date": self.prior_end_date,
                "total": self.total.as_dict(),
                "reminder_total": self.reminder_total.as_dict(),
                "campaign_total": self.campaign_total.as_dict(),
                "reminder_by_channel": by(self.reminder_by_channel),
                "campaign_by_channel": by(self.campaign_by_channel),
                "combined_by_channel": by(self.combined_by_channel),
                "reminder_by_day": by_day,
                "reminder_by_day_by_channel": by_day_by_channel,
                "by_day": by_day,
                "by_day_by_channel": by_day_by_channel,
                "reminder_by_status": by(self.reminder_by_status),
                "campaign_by_status": by(self.campaign_by_status),
                "by_status": by(self.reminder_by_status),
                "reminder_by_channel_by_status":
                    cross(self.reminder_by_channel_by_status),
                "campaign_by_channel_by_status":
                    cross(self.campaign_by_channel_by_status),
                "by_channel_by_status":
                    cross(self.reminder_by_channel_by_status),
                "campaign_by_day": campaign_by_day,
                "campaign_by_day_by_channel":
                    campaign_by_day_by_channel,
                "combined_by_status": by(self.combined_by_status),
                "combined_by_channel_by_status":
                    cross(self.combined_by_channel_by_status),
                "combined_by_day": combined_by_day,
                "combined_by_day_by_channel":
                    combined_by_day_by_channel}


def prior_send_totals(salon, start=None, end=None, **kwargs):
    """Return the prior-period send-totals comparison for ``salon``.

    Call as ``(salon, first, last)`` or ``(salon, day)`` for one
    day; ``date_from``/``date_to``, ``start_date``/``end_date``
    and ``since``/``until`` are accepted as aliases. Dates may be
    ``date``, ``datetime``, or ISO strings. Read-only.
    """
    if salon is None:
        raise ValueError("prior_send_totals needs a salon")
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
    cur_r, pri_r = send_totals(salon, first, last), send_totals(salon, p_start, p_end)
    cur_c = campaign_send_totals(salon, first, last)
    pri_c = campaign_send_totals(salon, p_start, p_end)

    def _by_channel(cur, pri, prefix):
        channels = list(cur.by_channel) + [
            ch for ch in pri.by_channel if ch not in cur.by_channel]
        return {ch: _delta(f"{prefix}_{ch}", cur.by_channel.get(ch, 0),
                           pri.by_channel.get(ch, 0)) for ch in channels}

    def _union_map(cur_map, pri_map, prefix):
        keys = list(cur_map) + [k for k in pri_map if k not in cur_map]
        return {k: _delta(f"{prefix}_{k}", cur_map.get(k, 0),
                          pri_map.get(k, 0)) for k in keys}

    def _cross(cur, pri, prefix):
        channels = list(cur.by_channel_by_status) + [
            ch for ch in pri.by_channel_by_status
            if ch not in cur.by_channel_by_status]
        out = {}
        for ch in channels:
            cur_cells = cur.by_channel_by_status.get(ch, {})
            pri_cells = pri.by_channel_by_status.get(ch, {})
            statuses = list(cur_cells) + [
                s for s in pri_cells if s not in cur_cells]
            out[ch] = {
                s: _delta(f"{prefix}_channel_{ch}_status_{s}",
                          cur_cells.get(s, 0), pri_cells.get(s, 0))
                for s in statuses}
        return out

    def _by_day(cur, pri, prefix):
        # Verbatim from the source's own by_day /
        # by_day_by_channel for both windows, zero-filled to
        # the union of both windows' days.
        union_days = sorted(set(cur.by_day) | set(pri.by_day))
        by_day = {
            day: _delta(f"{prefix}_day_{day.isoformat()}",
                        cur.by_day.get(day, 0), pri.by_day.get(day, 0))
            for day in union_days}
        by_day_by_channel = {}
        for day in union_days:
            cur_cells = cur.by_day_by_channel.get(day, {})
            pri_cells = pri.by_day_by_channel.get(day, {})
            channels = list(cur_cells) + [
                ch for ch in pri_cells if ch not in cur_cells]
            by_day_by_channel[day] = {
                ch: _delta(f"{prefix}_day_{day.isoformat()}_{ch}",
                           cur_cells.get(ch, 0), pri_cells.get(ch, 0))
                for ch in channels}
        return by_day, by_day_by_channel

    reminder_by_day, reminder_by_day_by_channel = _by_day(
        cur_r, pri_r, "reminder")
    campaign_by_day, campaign_by_day_by_channel = _by_day(
        cur_c, pri_c, "campaign")

    reminder_by_channel = _by_channel(cur_r, pri_r, "reminder")
    campaign_by_channel = _by_channel(cur_c, pri_c, "campaign")
    combined = {ch: _delta(
        f"combined_{ch}", cur_r.by_channel.get(ch, 0) + cur_c.by_channel.get(ch, 0),
        pri_r.by_channel.get(ch, 0) + pri_c.by_channel.get(ch, 0))
        for ch in reminder_by_channel}
    reminder_by_status = _union_map(
        cur_r.by_status, pri_r.by_status, "reminder_status")
    campaign_by_status = _union_map(
        cur_c.by_status, pri_c.by_status, "campaign_status")
    reminder_cross = _cross(cur_r, pri_r, "reminder")
    campaign_cross = _cross(cur_c, pri_c, "campaign")
    # Combined view: sum the two sources' own breakdowns
    # cell-by-cell for both windows, as combined_by_channel does.
    statuses = list(reminder_by_status) + [
        s for s in campaign_by_status if s not in reminder_by_status]
    combined_by_status = {s: _delta(
        f"combined_status_{s}",
        cur_r.by_status.get(s, 0) + cur_c.by_status.get(s, 0),
        pri_r.by_status.get(s, 0) + pri_c.by_status.get(s, 0))
        for s in statuses}
    combined_cross = {}
    cross_channels = list(reminder_cross) + [
        ch for ch in campaign_cross if ch not in reminder_cross]
    for ch in cross_channels:
        cur_r_cells = cur_r.by_channel_by_status.get(ch, {})
        pri_r_cells = pri_r.by_channel_by_status.get(ch, {})
        cur_c_cells = cur_c.by_channel_by_status.get(ch, {})
        pri_c_cells = pri_c.by_channel_by_status.get(ch, {})
        cell_statuses = (
            list(cur_r_cells) + [s for s in pri_r_cells if s not in cur_r_cells]
            + [s for s in cur_c_cells
               if s not in cur_r_cells and s not in pri_r_cells]
            + [s for s in pri_c_cells
               if s not in cur_r_cells and s not in pri_r_cells
               and s not in cur_c_cells])
        combined_cross[ch] = {s: _delta(
            f"combined_channel_{ch}_status_{s}",
            cur_r_cells.get(s, 0) + cur_c_cells.get(s, 0),
            pri_r_cells.get(s, 0) + pri_c_cells.get(s, 0))
            for s in cell_statuses}
    union_days = sorted(
        set(cur_r.by_day) | set(pri_r.by_day)
        | set(cur_c.by_day) | set(pri_c.by_day))
    combined_by_day = {day: _delta(
        f"combined_day_{day.isoformat()}",
        cur_r.by_day.get(day, 0) + cur_c.by_day.get(day, 0),
        pri_r.by_day.get(day, 0) + pri_c.by_day.get(day, 0))
        for day in union_days}
    combined_by_day_by_channel = {}
    for day in union_days:
        sources = (cur_r.by_day_by_channel.get(day, {}),
                   pri_r.by_day_by_channel.get(day, {}),
                   cur_c.by_day_by_channel.get(day, {}),
                   pri_c.by_day_by_channel.get(day, {}))
        channels = []
        for cells in sources:
            channels += [ch for ch in cells if ch not in channels]
        combined_by_day_by_channel[day] = {ch: _delta(
            f"combined_day_{day.isoformat()}_{ch}",
            sources[0].get(ch, 0) + sources[2].get(ch, 0),
            sources[1].get(ch, 0) + sources[3].get(ch, 0))
            for ch in channels}
    return PriorSendTotalsComparison(
        salon=salon, start_date=first, end_date=last,
        prior_start_date=p_start, prior_end_date=p_end,
        current_reminder=cur_r, prior_reminder=pri_r,
        current_campaign=cur_c, prior_campaign=pri_c,
        total=_delta("total", cur_r.total + cur_c.total, pri_r.total + pri_c.total),
        reminder_total=_delta("reminder_total", cur_r.total, pri_r.total),
        campaign_total=_delta("campaign_total", cur_c.total, pri_c.total),
        reminder_by_channel=reminder_by_channel,
        campaign_by_channel=campaign_by_channel, combined_by_channel=combined,
        reminder_by_day=reminder_by_day,
        reminder_by_day_by_channel=reminder_by_day_by_channel,
        reminder_by_status=reminder_by_status,
        campaign_by_status=campaign_by_status,
        reminder_by_channel_by_status=reminder_cross,
        campaign_by_channel_by_status=campaign_cross,
        campaign_by_day=campaign_by_day,
        campaign_by_day_by_channel=campaign_by_day_by_channel,
        combined_by_status=combined_by_status,
        combined_by_channel_by_status=combined_cross,
        combined_by_day=combined_by_day,
        combined_by_day_by_channel=combined_by_day_by_channel)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_send_totals = prior_send_totals
compare_send_totals = prior_send_totals
get_prior_send_totals = prior_send_totals
