"""Prior-period comparison for the no-show report.

Backend only, read-only. Built ON TOP of
:func:`bookings.noshow.noshow_report` — that service's figures
verbatim for both windows; this wrapper counts nothing itself.
Distinct source from :mod:`bookings.noshow_rate` (counts +
late-cancel rates; its prior exists separately). Prior period
is the equal-length window immediately before
``[start_date, end_date]``. Counts carry current/prior/delta/
percent_change (Decimal, 2 places, ROUND_HALF_UP; ``None``
when prior is zero). ``rate`` is the source's float fraction:
delta is ``current - prior`` as a float, percent_change the
same rule (``None`` when prior rate is zero). ``by_staff`` /
``by_client`` are unions of both windows, zero-filled on the
missing side, name order. The source's past-only denominator
rule applies to both windows verbatim — the same ``now`` is
passed to both calls. A reversed window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from bookings.availability import _tz
from bookings.noshow import ClientNoShow, StaffNoShow, noshow_report

__all__ = ["MetricDelta", "ComponentDelta", "NoShowDelta", "StaffPriorNoShow",
           "ClientPriorNoShow", "PriorNoShowReport", "PriorNoShow",
           "prior_noshow_report", "prior_noshow", "prior_period_noshow",
           "compare_noshow", "get_prior_noshow"]
_CENTS = Decimal("0.01")

@dataclass(frozen=True)
class MetricDelta:
    """One metric in both periods, with its change."""

    component: str
    current: object = None
    prior: object = None
    delta: object = None
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

ComponentDelta = MetricDelta
NoShowDelta = MetricDelta

def _dec(value): return Decimal(str(value))

def _pct_change(current, prior):
    if prior is None or _dec(prior) == 0:
        return None
    return ((_dec(current) - _dec(prior)) / _dec(prior) * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)

def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior), int(current) - int(prior), _pct_change(current, prior))

def _rate_delta(name, current, prior):
    return MetricDelta(name, float(current), float(prior), float(_dec(current) - _dec(prior)), _pct_change(current, prior))

@dataclass(frozen=True)
class StaffPriorNoShow:
    staff_member_id: int = None
    staff_name: str = ""
    current: object = None
    prior: object = None
    no_show_count: MetricDelta = None
    denominator: MetricDelta = None
    rate: MetricDelta = None

    @property
    def display_name(self): return self.staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                "no_show_count": self.no_show_count.as_dict(),
                "denominator": self.denominator.as_dict(), "rate": self.rate.as_dict()}

@dataclass(frozen=True)
class ClientPriorNoShow:
    client_id: int = None
    client_name: str = ""
    current: object = None
    prior: object = None
    no_show_count: MetricDelta = None
    denominator: MetricDelta = None
    rate: MetricDelta = None

    @property
    def display_name(self): return self.client_name

    def as_dict(self):
        return {"client_id": self.client_id, "client_name": self.client_name,
                "no_show_count": self.no_show_count.as_dict(),
                "denominator": self.denominator.as_dict(), "rate": self.rate.as_dict()}

@dataclass(frozen=True)
class PriorNoShowReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    now: object = None
    current: object = None
    prior: object = None
    no_show_count: MetricDelta = None
    denominator: MetricDelta = None
    rate: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)
    by_client: tuple = field(default_factory=tuple)

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days
    @property
    def count(self): return self.no_show_count

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "no_show_count": self.no_show_count.as_dict(),
                "denominator": self.denominator.as_dict(), "rate": self.rate.as_dict(),
                "by_staff": [s.as_dict() for s in self.by_staff],
                "by_client": [c.as_dict() for c in self.by_client]}

PriorNoShow = PriorNoShowReport

def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

def _deltas(cls_args, c, p):
    return dict(
        no_show_count=_count_delta("no_show_count", c.no_show_count, p.no_show_count),
        denominator=_count_delta("denominator", c.denominator, p.denominator),
        rate=_rate_delta("rate", c.rate, p.rate), **cls_args)

def prior_noshow_report(salon, date_from=None, date_to=None, *, start_date=None, end_date=None, now=None, **kwargs):
    """Return the no-show comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)``, or with
    ``start_date=``/``end_date=`` aliases (``start``/``end``/
    ``since``/``until``). ``now`` forwards verbatim to both
    source calls. Raises ``ValueError`` if missing/reversed.
    """
    if date_from is None:
        date_from = start_date or kwargs.pop("start", kwargs.pop("since", None))
    if date_to is None:
        date_to = end_date or kwargs.pop("end", kwargs.pop("until", None))
    if "now" in kwargs:
        now = kwargs.pop("now")
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if date_from is None:
        raise ValueError("Both start_date and end_date are required.")
    if date_to is None:
        date_to = date_from
    if salon is not None:
        tz = _tz(salon)
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
    first, last = _as_date(date_from, tz), _as_date(date_to, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    length = (last - first).days + 1
    p_end, p_start = first - timedelta(days=1), first - timedelta(days=length)
    now = now or timezone.now()
    current = noshow_report(salon, first, last, now=now)
    prior = noshow_report(salon, p_start, p_end, now=now)
    cur_s = {s.staff_member_id: s for s in current.by_staff}
    pri_s = {s.staff_member_id: s for s in prior.by_staff}
    names_s = {s.staff_member_id: s.staff_name for src in (current.by_staff, prior.by_staff) for s in src}
    by_staff = tuple(
        StaffPriorNoShow(current=cur_s.get(k) or StaffNoShow(staff_member_id=k, staff_name=names_s[k]),
                         prior=pri_s.get(k) or StaffNoShow(staff_member_id=k, staff_name=names_s[k]),
                         **_deltas(dict(staff_member_id=k, staff_name=names_s[k]),
                                   cur_s.get(k) or StaffNoShow(), pri_s.get(k) or StaffNoShow()))
        for k in sorted(names_s, key=lambda k: (names_s[k], k)))
    cur_c = {c.client_id: c for c in current.by_client}
    pri_c = {c.client_id: c for c in prior.by_client}
    names_c = {c.client_id: c.client_name for src in (current.by_client, prior.by_client) for c in src}
    by_client = tuple(
        ClientPriorNoShow(current=cur_c.get(k) or ClientNoShow(client_id=k, client_name=names_c[k]),
                          prior=pri_c.get(k) or ClientNoShow(client_id=k, client_name=names_c[k]),
                          **_deltas(dict(client_id=k, client_name=names_c[k]),
                                    cur_c.get(k) or ClientNoShow(), pri_c.get(k) or ClientNoShow()))
        for k in sorted(names_c, key=lambda k: (names_c[k], k)))
    return PriorNoShowReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, now=now, current=current, prior=prior,
        by_staff=by_staff, by_client=by_client,
        **_deltas({}, current, prior))

prior_noshow = prior_noshow_report
prior_period_noshow = prior_noshow_report
compare_noshow = prior_noshow_report
get_prior_noshow = prior_noshow_report
