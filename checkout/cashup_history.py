"""Read-only cashup history service for checkout.

Backend only — no views, templates, or UI. Reads the stored
``Cashup`` snapshots themselves back as history (unlike
:mod:`checkout.cashup_detail`, which recomputes from payments):
every cashup a salon took in a date range, plus a range summary.

Semantics (deliberate):

* A cashup belongs to the period it closes out, so it is in the
  range when ``[period_start, period_end]`` overlaps the window.
  Date arguments mean whole local days in the salon's timezone
  (``Salon.timezone``, falling back to UTC), inclusive at both
  ends; datetimes are an inclusive instant window.
* Multiple cashups per day are normal and all are returned:
  a cashup is a snapshot, not a lock. Nothing here locks or
  mutates anything; every entry reports ``is_locked == False``.
* Tender totals come from the stored ``tender_totals`` mapping
  (money as strings), parsed to ``Decimal`` and zero-filled for
  every core tender. Summary sums are sums of the snapshots —
  the stored rows are the one source of truth here.
* Variance vs expected is reported only when a record actually
  carries expected figures. The current ``Cashup`` model has no
  expected field, so ``expected_*`` / ``variance*`` are ``None``
  (unknown), never a fabricated ``0.00``. If an
  ``expected_tender_totals`` / ``expected_totals`` mapping or an
  ``expected_total`` is present, variance is actual - expected.

An empty range is an empty list with a zeroed summary, never
``None``. Core stays provider-agnostic: grouping is by the core
``Payment.Method`` tender slug only.
"""
import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Cashup, Payment

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")
__all__ = [
    "CashupHistory", "CashupHistoryEntry", "CashupRangeSummary",
    "cashup_history", "cashups_in_range", "list_cashups",
]


def _money(value):
    try:
        return Decimal(str(value)).quantize(_CENTS)
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO


def _parse_tender_map(raw):
    """Parse a stored ``{slug: amount}`` map; core tenders zero-filled."""
    out = {method: _ZERO for method in Payment.Method.values}
    if isinstance(raw, dict):
        for slug, amount in raw.items():
            out[str(slug)] = _money(amount)
    return out


def _expected_for(cashup):
    """Return ``(expected_by_tender_or_None, expected_total_or_None)``."""
    for attr in ("expected_tender_totals", "expected_totals"):
        raw = getattr(cashup, attr, None)
        if isinstance(raw, dict) and raw:
            parsed = _parse_tender_map(raw)
            return parsed, sum(parsed.values(), _ZERO).quantize(_CENTS)
    raw_total = getattr(cashup, "expected_total", None)
    if raw_total is None:
        raw = getattr(cashup, "expected", None)
        if isinstance(raw, dict) and raw:
            parsed = _parse_tender_map(raw)
            return parsed, sum(parsed.values(), _ZERO).quantize(_CENTS)
        if raw is not None and not isinstance(raw, (dict, list)):
            raw_total = raw
    if raw_total is not None:
        return None, _money(raw_total)
    return None, None


@dataclass(frozen=True)
class CashupHistoryEntry:
    """One stored cashup, with tender totals and variance."""

    cashup: object
    tender_totals: dict = field(default_factory=dict)
    total: Decimal = _ZERO
    expected_tender_totals: object = None
    expected_total: object = None
    variance_by_tender: object = None
    variance: object = None

    @property
    def id(self):
        return getattr(self.cashup, "pk", None)

    cashup_id = id

    @property
    def salon_id(self):
        return getattr(self.cashup, "salon_id", None)

    @property
    def period_start(self):
        return self.cashup.period_start

    @property
    def period_end(self):
        return self.cashup.period_end

    @property
    def created_at(self):
        return getattr(self.cashup, "created_at", None)

    @property
    def note(self):
        return getattr(self.cashup, "note", "")

    @property
    def by_tender(self):
        return self.tender_totals

    @property
    def has_expected(self):
        return self.expected_total is not None

    has_variance = has_expected

    @property
    def is_locked(self):
        return False

    locked = is_locked


@dataclass(frozen=True)
class CashupRangeSummary:
    """Range summary: how many cashups, total taken by tender."""

    count: int = 0
    total: Decimal = _ZERO
    by_tender: dict = field(default_factory=dict)
    expected_total: object = None
    variance: object = None
    variance_by_tender: object = None

    @property
    def cashup_count(self):
        return self.count

    @property
    def tender_totals(self):
        return self.by_tender

    @property
    def total_taken(self):
        return self.total


@dataclass(frozen=True)
class CashupHistory:
    """A salon's cashups in a range, plus the range summary."""

    salon: object
    date_from: object
    date_to: object
    entries: list = field(default_factory=list)
    summary: CashupRangeSummary = field(default_factory=CashupRangeSummary)

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def cashups(self):
        return [entry.cashup for entry in self.entries]

    @property
    def items(self):
        return self.entries

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index):
        return self.entries[index]

    @property
    def count(self):
        return self.summary.count

    cashup_count = count

    @property
    def total(self):
        return self.summary.total

    total_taken = total

    @property
    def by_tender(self):
        return self.summary.by_tender

    tender_totals = by_tender

    @property
    def expected_total(self):
        return self.summary.expected_total

    @property
    def variance(self):
        return self.summary.variance

    @property
    def variance_by_tender(self):
        return self.summary.variance_by_tender

    @property
    def start(self):
        return self.date_from

    @property
    def end(self):
        return self.date_to


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_day(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, datetime.date):
        return value
    raise ValueError("cashup history needs a date for its range")


def _window(date_from, date_to, tz):
    """Return (start_dt, end_dt, inclusive_end, start_label, end_label)."""
    if date_from is None or date_to is None:
        raise ValueError("cashup history needs both a range start and end")
    if isinstance(date_from, datetime.date) and not isinstance(
        date_from, datetime.datetime
    ):
        start_day, end_day = _as_day(date_from, tz), _as_day(date_to, tz)
        if end_day < start_day:
            raise ValueError("range end must not be before its start")
        start_dt = datetime.datetime.combine(
            start_day, datetime.time.min, tzinfo=tz
        )
        end_dt = start_dt + datetime.timedelta(
            days=(end_day - start_day).days + 1
        )
        return start_dt, end_dt, False, start_day, end_day
    if date_to < date_from:
        raise ValueError("range end must not be before its start")
    return date_from, date_to, True, date_from, date_to


def _entry_for(cashup):
    tender_totals = _parse_tender_map(getattr(cashup, "tender_totals", None))
    total = _money(getattr(cashup, "total", _ZERO))
    exp_by, exp_total = _expected_for(cashup)
    variance = variance_by = None
    if exp_total is not None:
        variance = (total - exp_total).quantize(_CENTS)
        if exp_by is not None:
            variance_by = {
                slug: (tender_totals.get(slug, _ZERO) - amt).quantize(_CENTS)
                for slug, amt in exp_by.items()
            }
    return CashupHistoryEntry(
        cashup=cashup, tender_totals=tender_totals, total=total,
        expected_tender_totals=exp_by, expected_total=exp_total,
        variance_by_tender=variance_by, variance=variance,
    )


_cashup_entry = _entry_for  # alias used by variance-branch tests


def cashup_history(salon, date_from, date_to):
    """Return the :class:`CashupHistory` for ``salon`` over a range.

    Dates are inclusive whole local days in the salon's timezone;
    datetimes are an inclusive instant window. A cashup counts when
    the period it closes out overlaps the window. Multiple cashups
    on one day are all returned, newest period first. Only that
    salon's cashups count. Read-only.
    """
    if salon is None:
        raise ValueError("cashup_history needs a salon")
    start_dt, end_dt, inclusive, start_label, end_label = _window(
        date_from, date_to, _salon_tz(salon)
    )
    qs = Cashup.objects.filter(salon=salon, period_end__gte=start_dt)
    if inclusive:
        qs = qs.filter(period_start__lte=end_dt)
    else:
        qs = qs.filter(period_start__lt=end_dt)
    entries = [
        _entry_for(c)
        for c in qs.order_by("-period_start", "-created_at", "-id")
    ]
    by_tender = {method: _ZERO for method in Payment.Method.values}
    for entry in entries:
        for slug, amount in entry.tender_totals.items():
            by_tender[slug] = (by_tender.get(slug, _ZERO) + amount).quantize(
                _CENTS
            )
    total = sum((e.total for e in entries), _ZERO).quantize(_CENTS)

    exp_total = variance = variance_by = None
    if entries and all(e.expected_total is not None for e in entries):
        exp_total = sum(
            (e.expected_total for e in entries), _ZERO
        ).quantize(_CENTS)
        variance = (total - exp_total).quantize(_CENTS)
        if all(e.variance_by_tender is not None for e in entries):
            variance_by = {
                slug: sum(
                    (e.variance_by_tender.get(slug, _ZERO) for e in entries),
                    _ZERO,
                ).quantize(_CENTS)
                for slug in by_tender
            }
    summary = CashupRangeSummary(
        count=len(entries), total=total, by_tender=by_tender,
        expected_total=exp_total, variance=variance,
        variance_by_tender=variance_by,
    )
    return CashupHistory(
        salon=salon, date_from=start_label, date_to=end_label,
        entries=entries, summary=summary,
    )


list_cashups = cashup_history
cashups_in_range = cashup_history
