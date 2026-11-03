"""Single-product update service for the catalog.

Backend only — no views, templates, or UI.

Companion to :mod:`catalog.add_product`: that module is the
validated single-record creation path; this module is the
validated single-record update path for an existing product in
one salon's scope. All fields are optional with a ``None``
sentinel — an omitted field is left unchanged, and calling with
no fields at all is refused (there is no silent no-op update).

Updatable fields: ``name``, ``price``, ``sku``, ``barcode``,
``active``. Validation reuses ``add_product``'s cleaners
verbatim, so creation and update can never disagree about what
a valid name, code, price, or active flag is, and a non-blank
barcode must stay unique within the salon — excluding the
product itself, so keeping its own barcode is fine.

Stock is EXCLUDED: stock is derived from ``StockMovement`` rows
(they own stock; there is no stock field on ``Product``), so
this service never touches movements. ``external_id`` and
``payload`` are EXCLUDED: they are source-system identity and
verbatim source shape, immutable through this path.
"""
from django.db import transaction

from catalog.add_product import (
    _BARCODE_LIMIT,
    _SKU_LIMIT,
    _clean_active,
    _clean_code,
    _clean_name,
    _clean_price,
    _clean_salon,
)
from catalog.models import Product

__all__ = ["update_product", "validate_update_product"]

_FIELDS = ("name", "price", "sku", "barcode", "active")


def _clean_product(salon, product):
    if not isinstance(product, Product) or product.pk is None:
        raise ValueError("product must be a saved Product instance")
    if product.salon_id != salon.pk:
        raise ValueError("product belongs to a different salon")
    return product


def validate_update_product(salon, product, name=None, price=None,
                            sku=None, barcode=None, active=None):
    """Validate an ``update_product`` call, writing nothing.

    Performs every check :func:`update_product` performs and
    returns the cleaned fields the writer would store, as a dict
    with keys ``salon``, ``product``, plus one key per field
    actually given (``None`` means omitted/unchanged, so omitted
    fields are absent). Raises the same ``ValueError`` the writer
    would raise. Writes nothing, so it is safe for ``--dry-run``
    previews on every backend (including NEDB, where a
    rolled-back transaction does not undo writes).
    """
    salon = _clean_salon(salon)
    product = _clean_product(salon, product)
    given = dict(name=name, price=price, sku=sku, barcode=barcode,
                 active=active)
    if all(value is None for value in given.values()):
        raise ValueError("at least one field must be given")
    cleaned = dict(salon=salon, product=product)
    if name is not None:
        cleaned["name"] = _clean_name(name)
    if price is not None:
        cleaned["price"] = _clean_price(price)
    if sku is not None:
        cleaned["sku"] = _clean_code(sku, "sku", _SKU_LIMIT)
    if barcode is not None:
        cleaned["barcode"] = _clean_code(
            barcode, "barcode", _BARCODE_LIMIT)
    if active is not None:
        cleaned["active"] = _clean_active(active)
    if cleaned.get("barcode") and Product.objects.filter(
            salon=salon, barcode=cleaned["barcode"]).exclude(
            pk=product.pk).exists():
        raise ValueError(
            f"barcode {cleaned['barcode']!r} is already used by "
            f"another product in salon {salon.pk}")
    return cleaned


def update_product(salon, product, name=None, price=None, sku=None,
                   barcode=None, active=None):
    """Update one product in ``salon`` and return it.

    Only fields given (non-``None``) are considered; only fields
    whose cleaned value actually differs are written, via
    ``save(update_fields=[...])``. Raises ``ValueError`` —
    changing nothing — for an unsaved/cross-salon salon or
    product, no fields given, a blank/over-long name, an
    over-long SKU or barcode, an unparseable/negative price, a
    non-boolean ``active``, or a non-blank ``barcode`` already
    carried by another product in the same salon.
    """
    with transaction.atomic():
        cleaned = validate_update_product(
            salon, product, name=name, price=price, sku=sku,
            barcode=barcode, active=active)
        product = cleaned["product"]
        changed = [field for field in _FIELDS
                   if field in cleaned
                   and cleaned[field] != getattr(product, field)]
        if changed:
            for field in changed:
                setattr(product, field, cleaned[field])
            product.save(update_fields=changed)
        return product
