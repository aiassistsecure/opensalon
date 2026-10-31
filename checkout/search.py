"""Read-only sale search service for checkout.

Backend only — no views, templates, or UI.

:func:`search_sales` finds one salon's sales by any combination
of:

* a client name fragment — matched case-insensitively against
  the client's first name, last name, and full "first last"
  name (via the ``Sale.client`` relation; walk-in sales with no
  client never match a name search);
* a local date range — whole local days in the salon's timezone
  (``Salon.timezone``, falling back to UTC), inclusive at both
  ends; either bound may be omitted for an open-ended range.
  A sale belongs to the day of its ``completed_at`` when set,
  otherwise its ``created_at`` — the attribution the summary and
  insights services already use;
* a minimum total — the sale's computed total (the sum of its
  items' line totals, the same derivation as :attr:`Sale.total`;
  totals are never stored) must be at least the amount given.

Results are ordered newest first (``-created_at``, ``-id`` — the
``Sale`` model's own ordering) and each returned sale carries a
``search_total`` attribute with its computed total as a
``Decimal``.

Voided sales are excluded unless ``include_voided=True`` is
passed explicitly. Only the given salon's sales are ever
returned. Read-only: nothing is created, updated, or deleted.

Core stays provider-agnostic: no payment-provider SDK, field,
or name appears here.
"""
import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce, Concat

from .models import Sale

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")

__all__ = ["search_sales", "find_sales"]


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
    raise ValueError("sale search dates must be dates")


def _day_start(day, tz):
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)


def _parse_min_total(value):
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("min_total must be a decimal amount") from None
    if amount < 0:
        raise ValueError("min_total must not be negative")
    return amount.quantize(_CENTS)


def search_sales(salon, client_name=None, date_from=None, date_to=None,
                 min_total=None, include_voided=False):
    """Return ``salon``'s sales matching every given filter.

    All filters are optional and combine (AND). ``client_name``
    is a case-insensitive fragment of the client's first, last,
    or full name; blank means no name filter. ``date_from`` /
    ``date_to`` are dates (or datetimes, judged by their date in
    the salon's timezone) bounding the sale's local day,
    inclusive; either may be omitted. ``min_total`` is a decimal
    amount the sale's computed total must reach. Voided sales
    are excluded unless ``include_voided`` is true.

    Returns a list of :class:`Sale` objects, newest first, each
    annotated with ``search_total``. No match is an empty list,
    never ``None``. Read-only.
    """
    if salon is None:
        raise ValueError("search_sales needs a salon")
    tz = _salon_tz(salon)
    minimum = _parse_min_total(min_total)

    qs = Sale.objects.filter(salon=salon)
    if not include_voided:
        qs = qs.exclude(status=Sale.Status.VOIDED)

    fragment = str(client_name).strip() if client_name else ""
    if fragment:
        qs = qs.annotate(
            _full_name=Concat(
                F("client__first_name"), Value(" "),
                F("client__last_name"),
            )
        ).filter(
            Q(client__first_name__icontains=fragment)
            | Q(client__last_name__icontains=fragment)
            | Q(_full_name__icontains=fragment)
        )

    start_dt = end_dt = None
    if date_from is not None:
        start_dt = _day_start(_as_day(date_from, tz), tz)
    if date_to is not None:
        end_dt = _day_start(_as_day(date_to, tz), tz) + datetime.timedelta(
            days=1
        )
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise ValueError("date_to must not be before date_from")
    if start_dt is not None or end_dt is not None:
        window = Q()
        done = Q(completed_at__isnull=False)
        open_ = Q(completed_at__isnull=True)
        if start_dt is not None:
            done &= Q(completed_at__gte=start_dt)
            open_ &= Q(created_at__gte=start_dt)
        if end_dt is not None:
            done &= Q(completed_at__lt=end_dt)
            open_ &= Q(created_at__lt=end_dt)
        qs = qs.filter(done | open_)

    qs = qs.annotate(
        search_total=Coalesce(
            Sum(F("items__unit_price") * F("items__quantity")), _ZERO
        )
    )
    if minimum is not None:
        qs = qs.filter(search_total__gte=minimum)

    sales = list(qs.order_by("-created_at", "-id"))
    for sale in sales:
        sale.search_total = Decimal(sale.search_total).quantize(_CENTS)
    return sales


find_sales = search_sales
