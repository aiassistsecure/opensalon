"""Verbatim SaleItem CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. One source of truth: every row is a stored
:class:`checkout.models.SaleItem` row, verbatim -- until now
its fields rendered standalone only as aggregates or inside a
receipt snapshot; verbatim they existed only in the salon_data
bundle's ``sale_items`` section. This module does not compute
totals, search, or aggregate anything.

Columns are exactly the model's concrete fields, in model
field order, using each field's ``attname`` (money as a string
to two decimal places, as in :mod:`checkout.refund_export`).
No payment-provider field appears here: ``provider_reference``
lives on ``Payment``, not a sale item, and stays out by design.

Scoping: ``sale__salon`` (a sale item carries no salon of its
own), in the model's own ordering (``id``). Optional
``date_from``/``date_to`` are inclusive whole local days in
the salon's timezone, judged on the parent sale's
``created_at`` (a sale item carries no timestamp); ``date_to``
may be omitted for a single day. A reversed range or a missing
salon exports as ``[]`` / the header row alone. Lines end
``"\n"``.

Per-sale filter: both export functions accept an optional
``sale`` (default ``None``). With ``None`` the output is the
salon-wide export, unchanged. With a sale, only that sale's
items are included; the date window still applies, and the
salon filter (``sale__salon``) still applies, so a sale from
another salon exports as empty.

Kind filter: both export functions accept an optional
``kind`` (default ``None`` = no kind filter, output
byte-identical to the unfiltered export). With a kind, only
items whose stored ``kind`` exactly matches it are included
-- the core :class:`SaleItem.Kind` slugs only (``service`` /
``product`` / ``series``); no provider concept enters here.
The kind filter composes (AND) with the date window and the
per-sale filter.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import SaleItem

__all__ = [
    "EXPORT_FIELDNAMES",
    "SALE_ITEM_EXPORT_FIELDNAMES",
    "export_sale_items",
    "export_sale_items_csv",
    "sale_item_export_row",
    "sale_items_csv",
]

#: Exactly ``SaleItem``'s concrete fields (attnames), in model
#: field order; tests guard this against ``_meta.concrete_fields``.
SALE_ITEM_EXPORT_FIELDNAMES = [
    "id",
    "sale_id",
    "kind",
    "service_id",
    "product_id",
    "description",
    "quantity",
    "unit_price",
    "discount_amount",
]
EXPORT_FIELDNAMES = SALE_ITEM_EXPORT_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    if value is None:
        return None
    return str(Decimal(value).quantize(_CENTS))


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def sale_item_export_row(item):
    """Return one stored ``item`` as a verbatim row dict."""
    return {
        "id": item.pk,
        "sale_id": item.sale_id,
        "kind": item.kind,
        "service_id": item.service_id,
        "product_id": item.product_id,
        "description": item.description,
        "quantity": item.quantity,
        "unit_price": _money(item.unit_price),
        "discount_amount": _money(item.discount_amount),
    }


def export_sale_items(salon, date_from=None, date_to=None, sale=None,
                      kind=None):
    """Return ``salon``'s sale items verbatim as dicts (see module).

    ``sale`` is optional: the default ``None`` is the salon-wide
    export, unchanged. When a sale is given, only that sale's
    items are included; a sale belonging to another salon
    exports as ``[]`` because the ``sale__salon`` filter still
    applies.

    ``kind`` is optional: the default ``None`` applies no kind
    filter, unchanged. When a kind is given, only items whose
    stored ``kind`` exactly matches it are included; it
    composes (AND) with the date window and ``sale``.
    """
    if salon is None:
        return []
    salon_id = getattr(salon, "pk", salon)
    if salon_id is None:
        return []
    items = SaleItem.objects.filter(sale__salon_id=salon_id)
    if sale is not None:
        items = items.filter(sale=sale)
    if kind is not None:
        items = items.filter(kind=kind)
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
        items = items.filter(
            sale__created_at__gte=window_start,
            sale__created_at__lt=window_end,
        )
    return [sale_item_export_row(item) for item in items]


def export_sale_items_csv(salon, date_from=None, date_to=None, sale=None,
                          kind=None):
    """Return ``salon``'s sale items as a CSV string.

    The header row is :data:`SALE_ITEM_EXPORT_FIELDNAMES` and
    every data row is rendered from :func:`export_sale_items`
    with the same arguments, so the CSV and the dict export can
    never disagree. Lines end with ``"\\n"``. Read-only.

    ``sale`` is optional and passed through to
    :func:`export_sale_items`: the default ``None`` is the
    salon-wide export, unchanged; a given sale exports only
    that sale's items.

    ``kind`` is optional and passed through likewise: the
    default ``None`` applies no kind filter, unchanged; a
    given kind exports only items of that stored kind.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SALE_ITEM_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_sale_items(salon, date_from, date_to, sale=sale,
                                    kind=kind):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
sale_items_csv = export_sale_items_csv
