"""Read-only sale search CSV export service for checkout.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale; it only
renders results already found by the existing service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.search` service as a plain, JSON-serializable
list of dicts (:func:`export_search_sales`) and as a CSV
string (:func:`export_search_sales_csv`) built from that same
list, so the two formats can never disagree — one source of
truth. The search itself is never reimplemented here: every
row comes verbatim from :func:`checkout.search.search_sales`,
called with the same arguments. No re-querying, no recounting,
and no invented fields.

Every row has exactly :data:`EXPORT_FIELDNAMES` keys:

* ``id`` / ``sale_id`` — the sale's primary key;
* ``salon_id`` — the sale's salon;
* ``client_id`` — the sale's client primary key, or ``None``
  when no client was recorded (walk-in);
* ``status`` — the sale's stored status;
* ``created_at`` — when the sale was created, as an ISO-8601
  string;
* ``completed_at`` — when the sale was completed, as an
  ISO-8601 string or ``None``;
* ``total`` — the sale's ``search_total`` as annotated by the
  search service (the sum of its items' line totals), as a
  string to two decimal places, because ``Decimal`` is not
  JSON-serializable and no money value is ever passed through
  a float.

Filter semantics follow the search service verbatim: the
optional ``client_name`` fragment, inclusive local-day
``date_from`` / ``date_to`` range, ``min_total``, and
``include_voided`` flag are passed through unchanged, and the
service's own errors propagate unchanged (e.g. ``ValueError``
for a missing salon, an invalid ``min_total``, or a reversed
range). Only the given salon's sales are ever exported.

Ordering is deterministic and matches the service: newest
first (``-created_at``, ``-id``). No match exports as ``[]`` /
the CSV header row alone, never ``None``. Lines end with
``"\\n"``. Core stays provider-agnostic — no payment-provider
SDK, field, or name appears here.
"""
import csv
import io
from decimal import Decimal

from .search import search_sales

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_search_sales",
    "export_search_sales_csv",
    "export_search_rows",
    "search_export_row",
    "search_sales_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "sale_id",
    "salon_id",
    "client_id",
    "status",
    "created_at",
    "completed_at",
    "total",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def search_export_row(sale):
    """Return one ``sale`` found by the search service as a row dict."""
    total = getattr(sale, "search_total", None)
    if total is None:
        total = sale.total
    return {
        "id": sale.pk,
        "sale_id": sale.pk,
        "salon_id": sale.salon_id,
        "client_id": sale.client_id,
        "status": sale.status,
        "created_at": (
            sale.created_at.isoformat() if sale.created_at else None
        ),
        "completed_at": (
            sale.completed_at.isoformat() if sale.completed_at else None
        ),
        "total": _money(total),
    }


def export_search_sales(salon, client_name=None, date_from=None,
                        date_to=None, min_total=None,
                        include_voided=False):
    """Return ``salon``'s sales matching the filters, as dicts.

    All arguments are passed verbatim to
    :func:`checkout.search.search_sales`; rows are rendered
    from its results in its own order (newest first). No
    match is ``[]``. The service's errors propagate. Read-only.
    """
    sales = search_sales(
        salon,
        client_name=client_name,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        include_voided=include_voided,
    )
    return [search_export_row(sale) for sale in sales]


def export_search_sales_csv(salon, client_name=None, date_from=None,
                            date_to=None, min_total=None,
                            include_voided=False):
    """Return :func:`export_search_sales` with the same args as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_search_sales` with the same
    arguments, so the CSV and list exports always agree. No
    match exports as the header row alone. Lines end with
    ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_search_sales(
        salon,
        client_name=client_name,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        include_voided=include_voided,
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_search_rows = export_search_sales
search_sales_csv = export_search_sales_csv
