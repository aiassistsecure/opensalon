"""Product search service for the catalog.

Backend only — no views, templates, or UI.

:func:`search_products` is the one product lookup for staff typing
(or a keyboard-wedge scanner delivering) a single query string:

* ``name`` matches case-insensitively by substring (``icontains``)
  — a partial product name finds the product.
* ``sku`` matches exactly — a partial SKU is not a match.
* ``barcode`` matches exactly — a partial barcode, or one digit
  off, is not a match. Exactness matters here: a truncated scanner
  read must not silently pick a different product.

Results are always scoped to one salon (the same name, SKU, or
barcode in another salon is never returned), inactive products are
excluded unless ``include_inactive=True``, and ordering is
deterministic: by name, then id.
"""
from django.db.models import Q

from catalog.models import Product


def search_products(salon, query, include_inactive=False):
    """Return products of ``salon`` matching ``query``.

    ``query`` is stripped before matching; a blank, whitespace-only,
    or ``None`` query matches nothing and returns an empty queryset.

    A product matches when its name contains ``query``
    (case-insensitive) or its SKU or barcode equals ``query``
    exactly. Inactive products are excluded by default; pass
    ``include_inactive=True`` to include them.

    Returns a queryset of :class:`catalog.models.Product` ordered
    by name, then id, so results are deterministic.
    """
    # Non-string queries are coerced so a scanner-delivered numeric
    # code can be passed straight in; None/blank matches nothing.
    text = "" if query is None else str(query).strip()
    if not text:
        return Product.objects.none()
    products = Product.objects.filter(salon=salon).filter(
        Q(name__icontains=text) | Q(sku=text) | Q(barcode=text)
    )
    if not include_inactive:
        products = products.filter(active=True)
    return products.order_by("name", "id")
