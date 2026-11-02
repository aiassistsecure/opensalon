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
zero. A reversed window or missing salon raises ``ValueError``.
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
    def deltas(self):
        return {"total": self.total, "reminder_total": self.reminder_total,
                "campaign_total": self.campaign_total,
                "reminder_by_channel": self.reminder_by_channel,
                "campaign_by_channel": self.campaign_by_channel,
                "combined_by_channel": self.combined_by_channel}

    def as_dict(self):
        by = lambda d: {k: v.as_dict() for k, v in d.items()}  # noqa: E731
        return {"salon_id": self.salon_id, "start_date": self.start_date,
                "end_date": self.end_date,
                "prior_start_date": self.prior_start_date,
                "prior_end_date": self.prior_end_date,
                "total": self.total.as_dict(),
                "reminder_total": self.reminder_total.as_dict(),
                "campaign_total": self.campaign_total.as_dict(),
                "reminder_by_channel": by(self.reminder_by_channel),
                "campaign_by_channel": by(self.campaign_by_channel),
                "combined_by_channel": by(self.combined_by_channel)}


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

    reminder_by_channel = _by_channel(cur_r, pri_r, "reminder")
    campaign_by_channel = _by_channel(cur_c, pri_c, "campaign")
    combined = {ch: _delta(
        f"combined_{ch}", cur_r.by_channel.get(ch, 0) + cur_c.by_channel.get(ch, 0),
        pri_r.by_channel.get(ch, 0) + pri_c.by_channel.get(ch, 0))
        for ch in reminder_by_channel}
    return PriorSendTotalsComparison(
        salon=salon, start_date=first, end_date=last,
        prior_start_date=p_start, prior_end_date=p_end,
        current_reminder=cur_r, prior_reminder=pri_r,
        current_campaign=cur_c, prior_campaign=pri_c,
        total=_delta("total", cur_r.total + cur_c.total, pri_r.total + pri_c.total),
        reminder_total=_delta("reminder_total", cur_r.total, pri_r.total),
        campaign_total=_delta("campaign_total", cur_c.total, pri_c.total),
        reminder_by_channel=reminder_by_channel,
        campaign_by_channel=campaign_by_channel, combined_by_channel=combined)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_send_totals = prior_send_totals
compare_send_totals = prior_send_totals
get_prior_send_totals = prior_send_totals
