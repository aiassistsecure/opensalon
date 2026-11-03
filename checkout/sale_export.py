"""Verbatim Sale CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. One source of truth: every row is a stored
:class:`checkout.models.Sale` row, verbatim -- until now the
sale header (above all its whole-sale ``discount_amount``)
rendered standalone only as aggregates, search hits, or inside
a receipt snapshot; verbatim it existed only in the salon_data
bundle's ``sales`` section. This module does not compute
totals, search, or aggregate anything.

Columns are exactly the model's concrete fields, in model
field order, using each field's ``attname`` (money as a string
to two decimal places, timestamps as ISO-8601 strings, as in
:mod:`checkout.refund_export`). No payment-provider field
appears here: ``provider_reference`` lives on ``Payment``, not
a sale, and stays out by design -- payments are
provider-agnostic in core.

Scoping: ``salon`` directly (a sale carries its own salon), in
``id`` order. Optional ``date_from``/``date_to`` are inclusive
whole local days in the salon's timezone, judged on the sale's
own ``created_at``; ``date_to`` may be omitted for a single
day. A reversed range or a missing salon exports as ``[]`` /
the header row alone. Lines end ``"\n"``.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Sale

__all__ = [
    "EXPORT_FIELDNAMES",
    "SALE_EXPORT_FIELDNAMES",
    "export_sales",
    "export_sales_csv",
    "sale_export_row",
    "sales_csv",
]

#: Exactly ``Sale``'s concrete fields (attnames), in model
#: field order; tests guard this against ``_meta.concrete_fields``.
SALE_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "client_id",
    "status",
    "discount_amount",
    "created_at",
    "completed_at",
    "voided_at",
    "void_reason",
]
EXPORT_FIELDNAMES = SALE_EXPORT_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    if value is None:
        return None
    return str(Decimal(value).quantize(_CENTS))


def _iso(value):
    return value.isoformat() if value else None


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def sale_export_row(sale):
    """Return one stored ``sale`` as a verbatim row dict."""
    return {
        "id": sale.pk,
        "salon_id": sale.salon_id,
        "client_id": sale.client_id,
        "status": sale.status,
        "discount_amount": _money(sale.discount_amount),
        "created_at": _iso(sale.created_at),
        "completed_at": _iso(sale.completed_at),
        "voided_at": _iso(sale.voided_at),
        "void_reason": sale.void_reason,
    }


def export_sales(salon, date_from=None, date_to=None):
    """Return ``salon``'s sales verbatim as dicts (see module)."""
    if salon is None:
        return []
    salon_id = getattr(salon, "pk", salon)
    if salon_id is None:
        return []
    sales = Sale.objects.filter(salon_id=salon_id).order_by("id")
    if date_from is not None:
        tz = _tz_for(salon)
        first = _as_local_date(date_from, tz)
        last = _as_local_date(date_to, tz) if date_to is not None else first
        if last < first:
            return []
        window_start = datetime.datetime.combine(
            first, datetime.time.min, tzinfo=tz
        )
        window_end = datetime.datetime.combine(
            last + datetime.timedelta(days=1),
            datetime.time.min, tzinfo=tz,
        )
        sales = sales.filter(
            created_at__gte=window_start,
            created_at__lt=window_end,
        )
    return [sale_export_row(sale) for sale in sales]


def export_sales_csv(salon, date_from=None, date_to=None):
    """Return ``salon``'s sales as a CSV string.

    The header row is :data:`SALE_EXPORT_FIELDNAMES` and every
    data row is rendered from :func:`export_sales` with the same
    arguments, so the CSV and the dict export can never disagree.
    Lines end with ``"\\n"``. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SALE_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_sales(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
sales_csv = export_sales_csv
