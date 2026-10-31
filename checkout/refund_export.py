"""Read-only refund CSV export service for checkout.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a refund, sale, or
payment; it only reads stored ``Refund`` records back.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one salon's refunds in an
inclusive local-date range as a plain, JSON-serializable list of
dicts (:func:`export_refunds`) and as a CSV string
(:func:`export_refunds_csv`) built from that same list, so the
two formats can never disagree — one source of truth. Every row
has exactly :data:`EXPORT_FIELDNAMES` keys:

* ``id`` / ``refund_id`` — the refund's primary key;
* ``salon_id`` — the salon of the refund's sale (``Refund``
  carries no salon of its own; the salon is read through its
  sale, never invented);
* ``sale_id`` — the sale the refund was recorded against;
* ``created_at`` — when the money was returned, as an ISO-8601
  string; this is the timestamp the range filters on;
* ``amount`` — money as a string to two decimal places (e.g.
  ``"20.50"``), because ``Decimal`` is not JSON-serializable
  and no money value is ever passed through a float;
* ``reason`` — the refund's stored reason (blank when none was
  recorded);
* ``tender`` — the refund's stored core tender slug
  (``Payment.Method``, e.g. ``"cash"`` / ``"external"``).

No other field is exported, because the ``Refund`` model
carries no other tender/method detail: core stays
provider-agnostic — no payment-provider SDK, field, or name
appears here, and no provider reference is invented.

Range semantics: ``date_from`` / ``date_to`` are inclusive
whole local days in the salon's timezone (``Salon.timezone``,
falling back to UTC), judged on the refund's ``created_at``
(the same day attribution as :mod:`checkout.refund_report`):
the window is [start of ``date_from``, start of the day after
``date_to``) in that timezone. ``date_to`` may be omitted for a
single-day export. Datetimes are reduced to their date in the
salon timezone, as in :mod:`bookings.export`. A reversed range
exports as ``[]`` / a header-only CSV.

Ordering is deterministic and chronological: oldest first
(``created_at``, then ``id``) — export order, so rows can be
appended to an external ledger without re-sorting. An empty
range exports as ``[]`` / the CSV header row alone, never
``None``.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Refund

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_refunds",
    "export_refunds_csv",
    "export_refund_rows",
    "refund_export_row",
    "refunds_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "refund_id",
    "salon_id",
    "sale_id",
    "created_at",
    "amount",
    "reason",
    "tender",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def refund_export_row(refund):
    """Return one stored ``refund`` as an export row dict."""
    return {
        "id": refund.pk,
        "refund_id": refund.pk,
        "salon_id": refund.sale.salon_id if refund.sale_id else None,
        "sale_id": refund.sale_id,
        "created_at": (
            refund.created_at.isoformat() if refund.created_at else None
        ),
        "amount": _money(refund.amount),
        "reason": refund.reason,
        "tender": refund.tender,
    }


def export_refunds(salon, date_from, date_to=None):
    """Return ``salon``'s refund rows in a date range, as dicts.

    ``date_from`` / ``date_to`` are inclusive whole local days
    in the salon's timezone; ``date_to`` defaults to
    ``date_from`` (a single-day export). Rows are ordered oldest
    first (``created_at``, then ``id``). An empty or reversed
    range, a missing salon, or a missing start date exports as
    ``[]``. Read-only.
    """
    if salon is None or date_from is None:
        return []
    tz = _tz_for(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return []
    window_start = datetime.datetime.combine(
        first, datetime.time.min, tzinfo=tz
    )
    window_end = datetime.datetime.combine(
        last + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
    )
    refunds = (
        Refund.objects.filter(
            sale__salon=salon,
            created_at__gte=window_start,
            created_at__lt=window_end,
        )
        .select_related("sale")
        .order_by("created_at", "id")
    )
    return [refund_export_row(refund) for refund in refunds]


def export_refunds_csv(salon, date_from, date_to=None):
    """Return ``salon``'s refunds in a date range as a CSV string.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_refunds` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header row alone. Lines end
    with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_refunds(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_refund_rows = export_refunds
refunds_csv = export_refunds_csv
