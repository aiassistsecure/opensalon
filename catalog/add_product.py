"""Single-product creation service for the catalog.

Backend only — no views, templates, or UI.

Today ``Product`` rows arrive only via bulk import
(``import_products`` / ``import_salon_data``). This module is the
validated single-record write path: it creates exactly one
product in one salon's scope from its name, SKU, barcode, price,
and active flag.

Barcode uniqueness: the ``Product`` model carries NO database
unique constraint on ``barcode`` (its only constraint is the
conditional ``uniq_product_external_id``), and the bulk importer
keys identity on ``(salon, external_id)``, not barcode. Scan
lookups, however, resolve a barcode to one product within a
salon (see :mod:`catalog.scanning`), so two products in the same
salon sharing a non-blank barcode would make scans ambiguous.
This service is therefore the single source of truth for that
rule: a non-blank barcode must be unique within the salon, and
a duplicate is refused with ``ValueError`` and nothing written.
The same barcode in a *different* salon is fine, and blank
barcodes are exempt (a product may simply have no barcode yet).

Validation mirrors the model/importer field shapes: name is a
non-blank string of at most 160 characters, SKU and barcode are
strings of at most 64 characters (never silently truncated —
an over-long code would become a different code), and price is
parsed exactly as the importer parses money,
``Decimal(str(value))``, never float arithmetic; it must be
finite and non-negative.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction

from catalog.models import Product
from saloncore.models import Salon

__all__ = ["add_product"]

_NAME_LIMIT = Product._meta.get_field("name").max_length
_SKU_LIMIT = Product._meta.get_field("sku").max_length
_BARCODE_LIMIT = Product._meta.get_field("barcode").max_length


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("product name must not be blank")
    text = name.strip()
    if len(text) > _NAME_LIMIT:
        raise ValueError(
            f"product name exceeds {_NAME_LIMIT} characters")
    return text


def _clean_code(value, field, limit):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field} must be a string")
    text = str(value).strip()
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _clean_price(price):
    if price is None or isinstance(price, bool):
        raise ValueError("price is required")
    if isinstance(price, str) and not price.strip():
        raise ValueError("price is required")
    try:
        value = Decimal(str(price))
    except (InvalidOperation, ValueError):
        raise ValueError(f"price {price!r} is not a valid amount") from None
    if not value.is_finite():
        raise ValueError("price must be finite")
    if value < 0:
        raise ValueError("price must not be negative")
    return value


def _clean_active(active):
    if not isinstance(active, bool):
        raise ValueError("active must be a boolean")
    return active


def add_product(salon, name, price, sku="", barcode="", active=True):
    """Create one product in ``salon`` and return it.

    Raises ``ValueError`` — creating nothing — for an unsaved
    salon, a blank/over-long name, an over-long SKU or barcode,
    an unparseable/negative price, a non-boolean ``active``, or
    a non-blank ``barcode`` already carried by another product
    in the same salon.
    """
    salon = _clean_salon(salon)
    name = _clean_name(name)
    price = _clean_price(price)
    sku = _clean_code(sku, "sku", _SKU_LIMIT)
    barcode = _clean_code(barcode, "barcode", _BARCODE_LIMIT)
    active = _clean_active(active)
    with transaction.atomic():
        if barcode and Product.objects.filter(
                salon=salon, barcode=barcode).exists():
            raise ValueError(
                f"barcode {barcode!r} is already used by another "
                f"product in salon {salon.pk}")
        return Product.objects.create(
            salon=salon, name=name, sku=sku, barcode=barcode,
            price=price, active=active)
