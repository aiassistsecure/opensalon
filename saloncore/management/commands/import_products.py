"""Import a Phorest product-catalog export into catalog.Product.

Type-faithful mapping (the importer's fidelity rules):

* money enters as ``Decimal(str(source))`` — never float arithmetic;
* ids, barcodes and codes stay strings, verbatim;
* brand / category / type labels are stored exactly as the source
  spells them (including the source's own inconsistencies);
* the whole source record is preserved verbatim in ``payload``;
* stock on hand becomes ONE opening StockMovement per newly created
  product (movements are the stock truth; a re-run never re-adds).

Resumable like the other importers: a product whose mapped fields
already match is counted ``unchanged`` and left alone.
"""
import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product, StockMovement
from saloncore.models import Salon


def _money(value):
    """Decimal from a source money value, or None when absent/bad."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


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


def _mapped(record):
    """The mapped field set for one source product record."""
    price = _money(record.get("price"))
    # Missing "archived" means not archived; a present value must
    # parse strictly (raises ValueError, counted as skipped by the
    # caller) rather than being truthiness-guessed.
    archived = (
        _parse_strict_bool(record["archived"])
        if "archived" in record else False
    )
    return {
        "name": (record.get("name") or "")[:160],
        "sku": _coerce_id_string(record.get("code"))[:64],
        "barcode": _coerce_id_string(record.get("barcode"))[:64],
        "price": price if price is not None else Decimal("0.00"),
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
        for record in records:
            if not isinstance(record, dict):
                skipped += 1
                continue
            try:
                external_id = _coerce_id_string(record.get("productId"))
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
            except ValueError:
                # Strict-bool failure (e.g. junk "archived") or an
                # unstringifiable code/barcode: counted as skipped,
                # never guessed.
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
                on_hand = record.get("quantityInStock") or 0
                if isinstance(on_hand, (int, float)) and int(on_hand) > 0:
                    StockMovement.objects.create(
                        product=product,
                        kind=StockMovement.Kind.RECEIVE,
                        quantity_delta=int(on_hand),
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

        self.stdout.write(
            f"products: {{'created': {created}, 'updated': {updated}, "
            f"'unchanged': {unchanged}, 'skipped': {skipped}, "
            f"'opening_stock_movements': {stocked}, "
            f"'total': {len(records)}}}"
        )
