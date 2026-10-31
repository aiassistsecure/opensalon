"""Read-only product search CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a product; it only
renders results already found by the existing service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`catalog.search` service as a plain, JSON-serializable
list of dicts (:func:`export_search_products`) and as a CSV
string (:func:`export_search_products_csv`) built from that
same list, so the two formats can never disagree — one source
of truth. The search itself is never reimplemented here: every
row comes verbatim from :func:`catalog.search.search_products`,
called with the same arguments. No re-querying, no recounting,
and no invented fields.

Every row has exactly :data:`EXPORT_FIELDNAMES` keys, all
fields the search service's ``Product`` results actually carry:

* ``id`` / ``product_id`` — the product's primary key;
* ``salon_id`` — the product's salon;
* ``name`` — the product name;
* ``sku`` / ``barcode`` — the product's SKU / barcode (blank
  when unset);
* ``price`` — the product's retail price, as a string to two
  decimal places, because ``Decimal`` is not JSON-serializable
  and no money value is ever passed through a float;
* ``active`` — whether the product is active.

Filter semantics follow the search service verbatim: ``name``
matches case-insensitively by substring, ``sku`` and ``barcode``
match exactly, a blank/``None`` query matches nothing, and
inactive products are excluded unless ``include_inactive=True``
is passed through unchanged. Only the given salon's products
are ever exported.

Ordering is deterministic and matches the service: by name,
then id. No match exports as ``[]`` / the CSV header row alone,
never ``None``. Lines end with ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from catalog.search import search_products

__all__ = [
    "EXPORT_FIELDNAMES",
    "SEARCH_FIELDNAMES",
    "export_search_products",
    "export_search_products_csv",
    "export_search_rows",
    "search_export_row",
    "search_products_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "product_id",
    "salon_id",
    "name",
    "sku",
    "barcode",
    "price",
    "active",
]

SEARCH_FIELDNAMES = EXPORT_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def search_export_row(product):
    """Return one ``product`` found by the search service as a row dict."""
    return {
        "id": product.pk,
        "product_id": product.pk,
        "salon_id": product.salon_id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "price": _money(product.price),
        "active": bool(product.active),
    }


def export_search_products(salon, query, include_inactive=False):
    """Return ``salon``'s products matching ``query``, as dicts.

    All arguments are passed verbatim to
    :func:`catalog.search.search_products`; rows are rendered
    from its results in its own order (name, then id). No
    match is ``[]``. Read-only.
    """
    products = search_products(
        salon, query, include_inactive=include_inactive
    )
    return [search_export_row(product) for product in products]


def export_search_products_csv(salon, query, include_inactive=False):
    """Return :func:`export_search_products` with the same args as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_search_products` with the same
    arguments, so the CSV and list exports always agree. No
    match exports as the header row alone. Lines end with
    ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_search_products(
        salon, query, include_inactive=include_inactive
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_search_rows = export_search_products
search_products_csv = export_search_products_csv
