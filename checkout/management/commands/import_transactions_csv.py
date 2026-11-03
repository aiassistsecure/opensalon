"""Import settled till history from monthly transaction CSV exports.

The salon's book (clients, services, staff, appointments,
products) can be fully imported while the till stays empty —
and every sales report reads the till. This command closes
that gap: it reads a directory of monthly transaction export
CSVs (``transactions-*.csv``, the line-item export a salon can
download from its previous system) and rebuilds the sales they
record as :class:`checkout.Sale` rows with their items and
payments, so the reports have the salon's real history to read.

Mapping — only what the source truly carries:

* One export transaction (``transaction_id``) becomes one
  completed ``Sale``; each of its line rows becomes a
  ``SaleItem``. The export's own line arithmetic is exact —
  ``unit_price * quantity - discount_amount`` equals the
  line's settled net on every row — so items are mapped
  verbatim (price, quantity, recorded discount) and the
  sale total the models derive from the items is the
  settled net, to the cent.
* ``SERVICE`` / ``SPECIAL_OFFER_ITEM`` lines become service
  items, ``PRODUCT`` lines become product items, linked to
  the imported service/product by the export's own ids
  (``Service.external_id`` / ``Product.external_id``) when
  the book carries them; the line's description snapshot is
  kept either way.
* Rows for appointment deposits and cancellation fees are
  NOT revenue lines (a deposit is a prepayment toward a
  future service sale; the fee is reported outside revenue
  by the salon's own books), so they never become items.
  A transaction carrying only such rows creates no sale.
  Both are counted, with amounts, in the summary.
* Void rows (``void`` = 1) are dropped, as the source's
  own settled record drops them.
* A ``REFUND`` transaction carries no reference back to
  the sale it reverses, so it cannot hang off the original
  sale as a :class:`checkout.Refund` record. It is imported
  as its own completed sale with negative lines — the
  source's own shape — so daily summaries net it on the
  day it happened, exactly as the settled books do. Its
  payments are marked refunded. (The export writes refund
  lines with a negative quantity and discount, which the
  models cannot hold; such a line is folded to a positive
  quantity at its exact settled net, so the net survives
  to the cent and only the line's gross/discount split
  is not carried.)
* Payments mirror the export's tender split verbatim
  (``payment_type_names`` / ``payment_type_amounts``):
  cash stays cash, every other tender is an external
  tender — core names no card brand or processor. The
  source transaction id is recorded as each payment's
  ``provider_reference`` (the reference the settling
  system itself knows the settlement by), which is also
  what makes a re-run idempotent: a transaction whose id
  is already on a payment of this salon's sales is
  skipped, never duplicated. Note the source settles
  card tips and tax into its payment amounts without
  itemising them, so a payment can exceed its sale's
  total; payments record how a sale was settled, never
  what was sold, and no report derives revenue from them.
* The client is matched by the export's client id
  (``Client.external_id``). An unmatched transaction
  still imports, with no client — never a fabricated one.
* Tips are not imported: the export's tip columns carry
  no itemised values, and core sales have no tips field.

The files live outside the repo and stay there: the
command takes the directory as an argument and commits
no data. Run summary follows the import_salon_data
precedent (one IMPORT_SUMMARY line, one IMPORT_SKIPPED
line accounting for everything not imported).

With ``--dry-run`` the directory is parsed and counted
exactly as for a real import but NOTHING is written (no
sale, item or payment rows): a JSON dry-run report from
``saloncore.dry_run`` is printed to stdout first — one
report per source file, per-key inferred types, distinct
null / missing / empty-string counts, and the source keys
this importer does not map — followed by the same
IMPORT_SUMMARY / IMPORT_SKIPPED lines a real run would
print, their counts read as would-create counts, and the
command exits 0.
"""
import csv
import io
import json
from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Product
from checkout.models import Payment, Sale, SaleItem
from clients.models import Client
from saloncore.dry_run import build_dry_run_reports
from saloncore.models import Salon, Service

# Every source key this importer actually maps. Anything else in a
# source row is reported as unmapped by --dry-run so nothing is
# silently dropped without being named first.
MAPPED_KEYS = frozenset({
    "transaction_id", "purchased_date", "purchase_time", "client_id",
    "item_type", "description", "quantity", "unit_price",
    "discount_amount", "net_total_amount", "service_id", "product_id",
    "void", "purchase_type", "payment_type_names",
    "payment_type_amounts",
})

REVENUE_KINDS = {
    "SERVICE": SaleItem.Kind.SERVICE,
    "SPECIAL_OFFER_ITEM": SaleItem.Kind.SERVICE,
    "PRODUCT": SaleItem.Kind.PRODUCT,
}


def _decimal(value):
    try:
        return Decimal((value or "").strip() or "0")
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _salon_tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _line_values(row):
    """One revenue row's (quantity, unit_price, discount_amount).

    Refund lines carry a negative quantity (and a negative
    discount) — a shape the models cannot hold (quantity and
    discount are non-negative there). Such a line is folded
    to a positive quantity at its exact settled net per unit,
    discount zero: the net — the figure the books reconcile
    on — is exact; only the refund line's own gross/discount
    split is not carried. Shared by the real import and the
    dry-run counter so both count the same lines.
    """
    quantity = int(_decimal(row.get("quantity")))
    unit_price = _decimal(row.get("unit_price"))
    discount = _decimal(row.get("discount_amount"))
    if quantity <= 0:
        quantity = abs(quantity) or 1
        unit_price = (
            _decimal(row.get("net_total_amount")) / quantity
        ).quantize(Decimal("0.01"))
        discount = Decimal("0")
    return quantity, unit_price, discount


def _transaction_when(row, tz):
    """The transaction's local wall-clock moment, made aware."""
    day = datetime.strptime(row["purchased_date"].strip(), "%Y-%m-%d").date()
    raw_time = (row.get("purchase_time") or "").strip()
    wall = time(0, 0)
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            wall = datetime.strptime(raw_time, fmt).time()
            break
        except ValueError:
            continue
    return datetime.combine(day, wall, tzinfo=tz)


class Command(BaseCommand):
    help = (
        "Import settled sales history from a directory of monthly "
        "transaction export CSVs (transactions-*.csv)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "directory",
            help="Directory holding transactions-*.csv export files.",
        )
        parser.add_argument(
            "--salon",
            type=int,
            default=None,
            help="Salon id to import into (default: the only salon).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print a JSON dry-run report (saloncore.dry_run) "
                 "for the source files plus the IMPORT_SUMMARY / "
                 "IMPORT_SKIPPED counts a real run would produce, "
                 "and write nothing.")

    def _resolve_salon(self, salon_id):
        if salon_id is not None:
            try:
                return Salon.objects.get(pk=salon_id)
            except Salon.DoesNotExist:
                raise CommandError(f"No salon with id {salon_id}.")
        salons = list(Salon.objects.order_by("pk"))
        if len(salons) == 1:
            return salons[0]
        if not salons:
            raise CommandError("No salon exists to import into.")
        raise CommandError(
            "More than one salon exists; pass --salon <id> "
            f"({' ,'.join(f'{s.pk}={s.name}' for s in salons)})."
        )

    def handle(self, *args, **options):
        salon = self._resolve_salon(options["salon"])
        directory = Path(options["directory"])
        files = sorted(directory.glob("transactions-*.csv"))
        if not files:
            raise CommandError(
                f"No transactions-*.csv files in {directory}."
            )
        tz = _salon_tz(salon)
        clients = {
            c.external_id: c
            for c in Client.objects.filter(salon=salon).exclude(external_id="")
        }
        services = {
            s.external_id: s
            for s in Service.objects.filter(
                category__salon=salon
            ).exclude(external_id="")
        }
        products = {
            p.external_id: p
            for p in Product.objects.filter(salon=salon).exclude(external_id="")
        }
        known_refs = set(
            Payment.objects.filter(
                sale__salon=salon
            ).exclude(provider_reference="").values_list(
                "provider_reference", flat=True
            )
        )

        stats = defaultdict(int)
        stats["excluded_amount"] = Decimal("0")
        transactions = {}
        file_records = {}
        for path in files:
            stats["files"] += 1
            # Real exports arrive in both UTF-8 and Latin-1 (older
            # monthly files carry accented names in Latin-1 bytes);
            # decode strictly as UTF-8 first, fall back to Latin-1,
            # which maps every byte, so a name is never mangled by
            # a replacement character.
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            rows = list(csv.DictReader(io.StringIO(text)))
            file_records[str(path)] = rows
            for row in rows:
                stats["rows_read"] += 1
                txn_id = (row.get("transaction_id") or "").strip()
                if not txn_id:
                    stats["rows_without_id"] += 1
                    continue
                transactions.setdefault(txn_id, []).append(row)

        if options["dry_run"]:
            # Zero writes: the schema report reads only the rows
            # parsed above; the counting loop below only reads
            # the salon's existing book (clients, services,
            # products, known payment references).
            self.stdout.write(json.dumps(
                build_dry_run_reports({
                    name: (rows, MAPPED_KEYS)
                    for name, rows in file_records.items()
                }),
                indent=2, sort_keys=True))

        for txn_id, rows in transactions.items():
            stats["transactions"] += 1
            live = [r for r in rows if (r.get("void") or "").strip() != "1"]
            stats["void_rows"] += len(rows) - len(live)
            if not live:
                stats["skipped_void"] += 1
                continue
            revenue = [
                r for r in live
                if (r.get("item_type") or "").strip() in REVENUE_KINDS
            ]
            for r in live:
                if (r.get("item_type") or "").strip() not in REVENUE_KINDS:
                    stats["excluded_lines"] += 1
                    stats["excluded_amount"] += _decimal(r.get("net_total_amount"))
            if not revenue:
                stats["skipped_nonrevenue"] += 1
                continue
            if txn_id in known_refs:
                stats["sales_existing"] += 1
                continue
            try:
                if options["dry_run"]:
                    self._count_transaction(
                        tz, txn_id, live, revenue, clients, stats,
                    )
                else:
                    self._import_transaction(
                        salon, tz, txn_id, live, revenue,
                        clients, services, products, stats,
                    )
            except Exception as exc:  # one bad transaction
                # never aborts the import — it is counted,
                # named, and left for a later re-run.
                stats["failed"] += 1
                self.stderr.write(
                    f"FAILED transaction {txn_id}: {exc}"
                )
                continue
            known_refs.add(txn_id)

        self.stdout.write(
            "IMPORT_SUMMARY "
            f"files={stats['files']} rows_read={stats['rows_read']} "
            f"transactions={stats['transactions']} "
            f"sales_created={stats['sales_created']} "
            f"sales_existing={stats['sales_existing']} "
            f"refund_sales={stats['refund_sales']} "
            f"items_created={stats['items_created']} "
            f"payments_created={stats['payments_created']} "
            f"clients_unmatched={stats['clients_unmatched']}"
        )
        self.stdout.write(
            "IMPORT_SKIPPED "
            f"void_transactions={stats['skipped_void']} "
            f"void_rows={stats['void_rows']} "
            f"nonrevenue_transactions={stats['skipped_nonrevenue']} "
            f"excluded_lines={stats['excluded_lines']} "
            f"excluded_amount={stats['excluded_amount']} "
            f"rows_without_id={stats['rows_without_id']} "
            f"failed_transactions={stats['failed']}"
        )
        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: no transactions were imported from {directory}"
            )
        else:
            self.stdout.write(f"Imported transactions from {directory}")

    def _count_transaction(self, tz, txn_id, live, revenue,
                           clients, stats):
        """Dry-run twin of ``_import_transaction``: count, never write.

        Mirrors the real import's order and arithmetic — client
        match, moment parse (a bad moment fails the transaction
        exactly as in a real run), one would-create item per
        revenue row via the shared ``_line_values`` fold, and
        the tender split via the shared ``_tender_parts`` over
        the would-be sale total — so the summary counts are the
        counts a real run on the same data produces.
        """
        first = live[0]
        is_refund = (first.get("purchase_type") or "").strip() == "REFUND"
        client = clients.get((first.get("client_id") or "").strip())
        if client is None:
            stats["clients_unmatched"] += 1
        _transaction_when(first, tz)
        total = Decimal("0")
        for row in revenue:
            quantity, unit_price, discount = _line_values(row)
            total += quantity * unit_price - discount
            stats["items_created"] += 1
        stats["payments_created"] += len(
            self._tender_parts(first, total))
        stats["sales_created"] += 1
        if is_refund:
            stats["refund_sales"] += 1

    def _import_transaction(self, salon, tz, txn_id, live, revenue,
                            clients, services, products, stats):
        first = live[0]
        is_refund = (first.get("purchase_type") or "").strip() == "REFUND"
        client = clients.get((first.get("client_id") or "").strip())
        if client is None:
            stats["clients_unmatched"] += 1
        when = _transaction_when(first, tz)
        with transaction.atomic():
            sale = Sale.objects.create(
                salon=salon,
                client=client,
                status=Sale.Status.COMPLETED,
                completed_at=when,
            )
            # created_at is auto_now_add; the sale happened at
            # the source moment, not at import time, and day
            # attribution falls back to created_at — set it
            # directly so the record tells the truth.
            Sale.objects.filter(pk=sale.pk).update(created_at=when)
            sale.created_at = when
            for row in revenue:
                kind = REVENUE_KINDS[(row.get("item_type") or "").strip()]
                quantity, unit_price, discount = _line_values(row)
                item = SaleItem(
                    sale=sale,
                    kind=kind,
                    description=(row.get("description") or "").strip()[:200],
                    quantity=quantity,
                    unit_price=unit_price,
                    discount_amount=discount,
                )
                if kind == SaleItem.Kind.SERVICE:
                    item.service = services.get(
                        (row.get("service_id") or "").strip()
                    )
                else:
                    item.product = products.get(
                        (row.get("product_id") or "").strip()
                    )
                item.save()
                stats["items_created"] += 1
            for method, amount in self._tender_parts(first, sale.total):
                Payment.objects.create(
                    sale=sale,
                    method=method,
                    amount=amount,
                    status=(
                        Payment.Status.REFUNDED
                        if is_refund else Payment.Status.COMPLETED
                    ),
                    provider_reference=txn_id,
                )
                stats["payments_created"] += 1
        stats["sales_created"] += 1
        if is_refund:
            stats["refund_sales"] += 1

    @staticmethod
    def _tender_parts(first_row, sale_total):
        """The source's tender split as (method, amount) pairs.

        Cash keeps its name; every other tender is an external
        tender. When the split is absent or unreadable, fall
        back to one external payment of ``sale_total`` so the
        settlement is still on record.
        """
        names = (first_row.get("payment_type_names") or "").split(";")
        amounts = (first_row.get("payment_type_amounts") or "").split(";")
        parts = []
        for name, amount in zip(names, amounts):
            name = name.strip()
            if not name or not amount.strip():
                continue
            parts.append((
                Payment.Method.CASH
                if name.lower() == "cash" else Payment.Method.EXTERNAL,
                _decimal(amount),
            ))
        if not parts:
            parts = [(Payment.Method.EXTERNAL, sale_total)]
        return parts
