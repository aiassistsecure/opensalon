"""Stock adjustment history CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's stock adjustments as a
plain, JSON-serializable list of dicts
(:func:`export_stock_adjustments`) and as a CSV string
(:func:`export_stock_adjustments_csv`) built from that same list,
so the two formats can never disagree — one source of truth.

Adjustments are NOT recomputed or stored separately: an adjustment
is exactly one ``StockMovement`` of kind ``ADJUSTMENT`` recorded by
:func:`catalog.adjust.adjust_stock`, carrying the signed delta and
the caller's reason verbatim in its ``note``. Every row here comes
verbatim from those movements, filtered to ``kind=ADJUSTMENT`` —
no other movement kind is included, and no fields are invented.

Columns are only fields the adjustment records actually carry:

- ``id``: the movement's id.
- ``product_id`` / ``product_name`` / ``sku`` / ``barcode``: from
  the movement's product.
- ``quantity_delta``: the movement's signed delta.
- ``note``: the movement's note (the adjustment reason).
- ``created_at``: the movement's timestamp, ISO-8601.

Range semantics: ``start`` / ``end`` filter on ``created_at`` and
may each be a ``date``, a ``datetime``, or ``None`` (unbounded).
The range is start-inclusive and end-exclusive after
normalisation: a ``date`` start means the start of that day, and
a ``date`` end means the start of the *following* day, so passing
two dates includes the whole end day. A ``datetime`` is used as
given (naive datetimes are interpreted in the current time zone).
Ordering is deterministic: by ``created_at``, then id (the model's
own ordering).
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from catalog.models import StockMovement

__all__ = [
    "ADJUST_FIELDNAMES",
    "ADJUSTMENT_FIELDNAMES",
    "ADJUST_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stock_adjustments",
    "export_stock_adjustments_csv",
    "stock_adjustments_csv",
    "adjustment_csv",
]

#: Column / key order shared by the dict export and the CSV export.
ADJUST_FIELDNAMES = [
    "id",
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "quantity_delta",
    "note",
    "created_at",
]

ADJUSTMENT_FIELDNAMES = ADJUST_FIELDNAMES
ADJUST_EXPORT_FIELDNAMES = ADJUST_FIELDNAMES
EXPORT_FIELDNAMES = ADJUST_FIELDNAMES


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _adjustments_in_range(salon, start, end):
    salon_id = getattr(salon, "pk", salon)
    queryset = (
        StockMovement.objects.filter(
            product__salon_id=salon_id,
            kind=StockMovement.Kind.ADJUSTMENT,
        )
        .select_related("product")
        .order_by("created_at", "id")
    )
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None:
        queryset = queryset.filter(created_at__gte=start_bound)
    if end_bound is not None:
        queryset = queryset.filter(created_at__lt=end_bound)
    return queryset


def _record(movement):
    product = movement.product
    return {
        "id": movement.pk,
        "product_id": product.pk,
        "product_name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "quantity_delta": int(movement.quantity_delta),
        "note": movement.note,
        "created_at": movement.created_at.isoformat(),
    }


def export_stock_adjustments(salon, start=None, end=None):
    """Return ``salon``'s stock adjustments in the range as dicts.

    Each entry is a dict with exactly :data:`ADJUST_FIELDNAMES`
    keys. Only ``salon``'s ``ADJUSTMENT`` movements are included,
    ordered by ``created_at``, then id. See the module docstring
    for range semantics. A range with no adjustments exports as
    ``[]``. Records nothing.
    """
    return [_record(m) for m in _adjustments_in_range(salon, start, end)]


def export_stock_adjustments_csv(salon, start=None, end=None):
    """Return ``salon``'s stock adjustments in the range as CSV.

    The header row is :data:`ADJUST_FIELDNAMES` and every data row
    comes from :func:`export_stock_adjustments` with the same
    arguments, so the CSV and list exports always agree. A range
    with no adjustments exports as the header row alone. Lines end
    with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ADJUST_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_stock_adjustments(salon, start=start, end=end):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
stock_adjustments_csv = export_stock_adjustments_csv
adjustment_csv = export_stock_adjustments_csv
