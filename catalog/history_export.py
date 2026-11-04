"""Stock movement history CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing stock history
service (:func:`catalog.history.stock_history`) as a plain,
JSON-serializable list of dicts (:func:`export_stock_history`)
and as a CSV string (:func:`export_stock_history_csv`) built
from that same list, so the two formats can never disagree — one
source of truth.

History is NOT recomputed here: no re-querying, no re-summing.
Every row comes verbatim from the ``HistoryEntry`` objects
returned by :func:`catalog.history.stock_history` with the exact
same arguments (``salon`` and ``product`` — see that service for
its input shapes, the single-Product-argument convenience, and
its validation). Row ordering is the service's: chronological
(``created_at``, then ``id``), and each row's
``running_balance`` is the service's derived balance after that
movement — the last row's balance is the history's final
balance. Salon scoping is the service's: the product is resolved
within the given salon and a product belonging to another salon
raises the service's ``ValueError`` rather than leaking.

Columns are only fields the history actually carries:

- ``id``: the entry's movement id (``entry.movement``).
- ``product_id`` / ``product_name`` / ``sku`` / ``barcode``:
  from the history's product.
- ``kind`` / ``quantity_delta`` / ``note``: copied from the
  entry (the movement's kind, signed delta, and note).
- ``running_balance``: the entry's derived balance after the
  movement.
- ``created_at``: the entry's timestamp, ISO-8601 (a
  ``datetime`` is not JSON-serializable).

Quantities are integers, which are JSON-safe as-is, so no
string conversion is needed; no fields are invented.

Window: both exports also take one optional date window,
``start`` / ``end``, filtering on each entry's ``created_at``.
Each bound may be a ``date``, a ``datetime``, or ``None``
(unbounded, the default). The window is start-inclusive and
end-exclusive after normalisation: a ``date`` start means the
start of that day, and a ``date`` end means the start of the
*following* day, so passing two dates includes the whole end
day. A ``datetime`` is used as given (naive datetimes are
interpreted in the current time zone). With both bounds
``None`` the output is the previous unwindowed output,
byte-identical. The window only selects which entries are
exported: ``running_balance`` stays the history service's
full-ledger balance after each movement (it is NOT recomputed
over the window), and the existing ``product`` filter still
applies and composes with the window (window AND product).
The wrapped :func:`catalog.history.stock_history` service
takes no window arguments, so the window is applied here to
its entries; that service is called unchanged.

Kind filter: both exports also take one optional ``kind``
(default ``None`` = no kind filter, output identical to the
unfiltered export). With a kind, only entries whose stored
``kind`` exactly matches it are exported — ``kind=str(kind)``,
so a ``StockMovement.Kind`` member works, with no case
folding — mirroring the sibling categorical filters. The
kind filter composes (AND) with the product and the window,
and like the window it only selects which entries are
exported: ``running_balance`` stays the full-ledger balance.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from catalog.history import stock_history

__all__ = [
    "HISTORY_FIELDNAMES",
    "STOCK_HISTORY_FIELDNAMES",
    "HISTORY_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stock_history",
    "export_stock_history_csv",
    "history_csv",
    "stock_history_csv",
]

#: Column / key order shared by the dict export and the CSV export.
HISTORY_FIELDNAMES = [
    "id",
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "kind",
    "quantity_delta",
    "note",
    "running_balance",
    "created_at",
]

STOCK_HISTORY_FIELDNAMES = HISTORY_FIELDNAMES
HISTORY_EXPORT_FIELDNAMES = HISTORY_FIELDNAMES
EXPORT_FIELDNAMES = HISTORY_FIELDNAMES


def _record(history, entry):
    product = history.product
    return {
        "id": entry.movement.pk,
        "product_id": product.pk,
        "product_name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "kind": entry.kind,
        "quantity_delta": int(entry.quantity_delta),
        "note": entry.note,
        "running_balance": int(entry.running_balance),
        "created_at": entry.created_at.isoformat(),
    }


def _bound(value, *, is_end):
    """Normalise a window bound to an aware datetime or ``None``."""
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


def export_stock_history(salon, product=None, start=None, end=None,
                         kind=None):
    """Return one product's stock history as a list of dicts.

    Each entry is a dict with exactly :data:`HISTORY_FIELDNAMES`
    keys, built directly from
    :func:`catalog.history.stock_history` called with the same
    arguments, in that service's chronological order. Salon
    scoping and validation are the service's (see the module
    docstring). A product with no movements exports as ``[]``.

    The optional ``start`` / ``end`` window filters on each
    entry's ``created_at`` (see the module docstring for the
    semantics); the default ``None`` bounds export the full
    history, unchanged. The optional ``kind`` filters by exact
    stored kind value (AND with the product and the window);
    ``None`` (the default) applies no kind filter. Records
    nothing.
    """
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    history = stock_history(salon, product)
    return [
        _record(history, entry)
        for entry in history.entries
        if (start_bound is None or entry.created_at >= start_bound)
        and (end_bound is None or entry.created_at < end_bound)
        and (kind is None or entry.kind == str(kind))
    ]


def export_stock_history_csv(salon, product=None, start=None, end=None,
                             kind=None):
    """Return one product's stock history as a CSV string.

    The header row is :data:`HISTORY_FIELDNAMES` and every data
    row comes from :func:`export_stock_history` with the same
    arguments (including the optional ``start`` / ``end``
    window and the optional ``kind`` filter), so the CSV and
    list exports always agree. A product with no movements in
    the window / of the kind exports as the header row alone.
    Lines end with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=HISTORY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_stock_history(
            salon, product, start=start, end=end, kind=kind):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
history_csv = export_stock_history_csv
stock_history_csv = export_stock_history_csv
