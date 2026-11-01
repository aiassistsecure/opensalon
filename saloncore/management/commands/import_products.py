"""Import a Phorest product-catalog export into catalog.Product.

Type-faithful mapping (the importer's fidelity rules):

* money enters as ``Decimal(str(source))`` — never float arithmetic;
* ids, barcodes and codes stay strings, verbatim;
* brand / category / type labels are stored exactly as the source
  spells them (including the source's own inconsistencies);
* the whole source record is preserved verbatim in ``payload``;
* stock on hand becomes ONE opening StockMovement per newly created
  product (movements are the stock truth; a re-run never re-adds);
* ``price`` is REQUIRED: ``Product.price`` cannot hold null, so a
  record whose price is missing, empty or unparseable is a counted
  skip (reported separately as ``skipped_missing_price`` in the
  summary) — never silently imported as 0.00. That is the one
  behaviour for every such row; it differs from ``reorderCost``
  only because ``cost_price`` IS nullable, so a missing cost stays
  None there;
* ``quantityInStock`` must be an integer: a fractional or otherwise
  non-integer value is a counted skip, never truncated via
  ``int(...)`` (2.9 does not become 2);
* ids / codes are never silently truncated (TF-6, mirroring
  ``import_clients`` / ``import_appointments``): a ``productId``,
  ``code`` or ``barcode`` longer than its model field limit makes
  the record a counted skip under ``skipped_id_too_long`` — slicing
  it would turn it into a DIFFERENT id and corrupt identity joins.
  Non-identity labels (name / brand / category / type) keep the
  clients-importer behaviour and are truncated to field length;
* money parsing mirrors ``import_price_book._decimal`` exactly —
  ``Decimal(str(value))``, no local quantize — so the same input
  yields the same Decimal in both importers; cents rounding is
  left to the shared DecimalField(decimal_places=2) storage shape
  both models use.

Resumable like the other importers: a product whose mapped fields
already match is counted ``unchanged`` and left alone.
"""
import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product, StockMovement
from saloncore.models import Salon


def _money(value):
    """Decimal from a source money value, or None when absent/bad.

    Mirrors ``import_price_book._decimal`` exactly (TF-8):
    ``Decimal(str(value))`` with NO quantize here, so the same
    input yields the same Decimal in both importers.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class _MissingPrice(ValueError):
    """The record has no usable price; counted as skipped_missing_price."""


def _stock_quantity(record):
    """Opening stock from ``quantityInStock`` as a strict int.

    Absent/None/empty means 0 (no opening movement), as before.
    An integral value (6, 6.0, "6") returns that int; anything
    fractional (2.9, "2.9") or non-numeric raises ValueError so
    the caller counts the record skipped — the old
    ``int(on_hand)`` silently truncated 2.9 to 2.
    """
    value = record.get("quantityInStock")
    if value is None or value == "":
        return 0
    if isinstance(value, bool) or isinstance(
            value, (dict, list, tuple, set)):
        raise ValueError(
            f"quantityInStock {value!r} is not an integer.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(
            f"quantityInStock {value!r} is not an integer.") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(
            f"quantityInStock {value!r} is not an integer.")
    return int(number)


_STRICT_TRUE_WORDS = {"true", "1", "yes"}
_STRICT_FALSE_WORDS = {"false", "0", "no"}


def _parse_strict_bool(value):
    """Strict bool parse, mirroring import_price_book's CSV parser.

    Bool passthrough; int 1/0; or one of the strings
    "true"/"false"/"1"/"0"/"yes"/"no" (case-insensitive). Anything
    else raises ValueError — never guessed (string "false" is truthy,
    so ``not record.get("archived")`` silently inactivated live
    products).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _STRICT_TRUE_WORDS:
            return True
        if text in _STRICT_FALSE_WORDS:
            return False
    raise ValueError(f"archived {value!r} is not a boolean.")


def _coerce_id_string(value):
    """String form of an id / code / barcode scalar.

    None/missing becomes "" (the caller's missing case). Ints and
    other scalars import as ``str(value)`` — slicing an int raised
    TypeError and aborted the whole import. A value that cannot be
    stringified as an id (dict/list/tuple/set, or a bool) raises
    ValueError so the caller counts the record as skipped — never
    crashed on, never guessed.
    """
    if value is None:
        return ""
    if isinstance(value, bool) or isinstance(
            value, (dict, list, tuple, set)):
        raise ValueError(
            f"id/code value {value!r} is not a stringifiable scalar.")
    return str(value)


_ID_LIMITS = {
    field: Product._meta.get_field(field).max_length
    for field in ("external_id", "sku", "barcode")
}


class _OverlongId(ValueError):
    """An id / code value exceeds its model field limit (TF-6)."""


def _checked_id_string(value, field):
    """TF-5 string coercion plus TF-6 length check for ``field``.

    Returns the coerced string unchanged when it fits; raises
    ``_OverlongId`` naming the field when it is longer than the
    field's limit, so the caller counts the record skipped under
    ``skipped_id_too_long`` instead of slicing it into a
    different id.
    """
    text = _coerce_id_string(value)
    limit = _ID_LIMITS[field]
    if len(text) > limit:
        raise _OverlongId(
            f"{field} value of {len(text)} characters exceeds "
            f"the {limit}-character limit")
    return text


def _mapped(record):
    """The mapped field set for one source product record."""
    price = _money(record.get("price"))
    if price is None:
        # Product.price is NOT nullable, so there is no honest
        # None to store — and the old fallback stored 0.00 while
        # a missing reorderCost stored None. One behaviour now:
        # counted skip (see the module docstring).
        raise _MissingPrice(
            f"product {record.get('productId')!r} has no usable price")
    # Missing "archived" means not archived; a present value must
    # parse strictly (raises ValueError, counted as skipped by the
    # caller) rather than being truthiness-guessed.
    archived = (
        _parse_strict_bool(record["archived"])
        if "archived" in record else False
    )
    return {
        "name": (record.get("name") or "")[:160],
        "sku": _checked_id_string(record.get("code"), "sku"),
        "barcode": _checked_id_string(
            record.get("barcode"), "barcode"),
        "price": price,
        "active": not archived,
        "brand_name": (record.get("brandName") or "")[:120],
        "category_name": (record.get("categoryName") or "")[:120],
        "product_type": (record.get("type") or "")[:32],
        "cost_price": _money(record.get("reorderCost")),
        "payload": record,
    }


class Command(BaseCommand):
    help = "Import a Phorest product catalog JSON export (verbatim)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the products JSON export.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into.")

    def handle(self, *args, **options):
        try:
            with open(options["path"], encoding="utf-8") as fh:
                records = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read products export: {exc}")
        if not isinstance(records, list):
            raise CommandError("products export must be a JSON list")

        salon, _ = Salon.objects.get_or_create(name=options["salon"])
        created = updated = unchanged = skipped = stocked = 0
        missing_price = 0
        id_too_long = 0
        for record in records:
            if not isinstance(record, dict):
                skipped += 1
                continue
            try:
                external_id = _checked_id_string(
                    record.get("productId"), "external_id")
            except _OverlongId:
                # TF-6: over-long productId — counted skip naming
                # the row via skipped_id_too_long, never a sliced
                # (different) external_id.
                skipped += 1
                id_too_long += 1
                continue
            except ValueError:
                # Unstringifiable productId (e.g. dict/list): counted
                # as skipped, never crashed on, never guessed.
                skipped += 1
                continue
            if not external_id or not record.get("name"):
                skipped += 1
                continue
            try:
                fields = _mapped(record)
                on_hand = _stock_quantity(record)
            except _MissingPrice:
                # No usable price: counted as skipped (and in its
                # own skipped_missing_price counter), never
                # imported as 0.00.
                skipped += 1
                missing_price += 1
                continue
            except _OverlongId:
                # TF-6: over-long code/barcode — counted skip under
                # skipped_id_too_long, never silently truncated.
                skipped += 1
                id_too_long += 1
                continue
            except ValueError:
                # Strict-bool failure (e.g. junk "archived"), an
                # unstringifiable code/barcode, or a non-integer
                # quantityInStock: counted as skipped, never guessed.
                skipped += 1
                continue
            existing = Product.objects.filter(
                salon=salon, external_id=external_id
            ).first()
            if existing is None:
                product = Product.objects.create(
                    salon=salon, external_id=external_id, **fields
                )
                created += 1
                if on_hand > 0:
                    StockMovement.objects.create(
                        product=product,
                        kind=StockMovement.Kind.RECEIVE,
                        quantity_delta=on_hand,
                        note="Opening stock from source import",
                    )
                    stocked += 1
                continue
            if all(getattr(existing, k) == v for k, v in fields.items()):
                unchanged += 1
                continue
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.save()
            updated += 1

        # Summary note: rows with no usable price are counted in
        # BOTH 'skipped' and 'skipped_missing_price' and are never
        # imported (Product.price cannot be null; no 0.00 fallback).
        self.stdout.write(
            f"products: {{'created': {created}, 'updated': {updated}, "
            f"'unchanged': {unchanged}, 'skipped': {skipped}, "
            f"'skipped_missing_price': {missing_price}, "
            f"'skipped_id_too_long': {id_too_long}, "
            f"'opening_stock_movements': {stocked}, "
            f"'total': {len(records)}}}"
        )
