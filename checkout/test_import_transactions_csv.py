"""Tests for the import_transactions_csv management command.

Fixtures are synthetic export rows written to a temp directory
(unit fixtures only — the pilot path itself runs on the real
exports). The fixture header mirrors the real export's columns
that the command reads.
"""
import csv
import datetime
import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Product
from checkout.models import Payment, Sale, SaleItem
from checkout.summary import daily_sales_summary
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory

HEADER = [
    "transaction_id", "purchased_date", "purchase_time", "client_id",
    "item_type", "description", "quantity", "unit_price",
    "discount_amount", "net_total_amount", "service_id", "product_id",
    "void", "purchase_type", "payment_type_names", "payment_type_amounts",
]


def row(**overrides):
    base = {
        "transaction_id": "txn-1",
        "purchased_date": "2026-10-05",
        "purchase_time": "14:30:00.000",
        "client_id": "client-1",
        "item_type": "SERVICE",
        "description": "Ladies Haircut",
        "quantity": "1",
        "unit_price": "100.00",
        "discount_amount": "0.00",
        "net_total_amount": "100.00",
        "service_id": "svc-1",
        "product_id": "",
        "void": "0",
        "purchase_type": "SALE",
        "payment_type_names": "Credit",
        "payment_type_amounts": "100.00",
    }
    base.update(overrides)
    return base


class ImportTransactionsCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Import Salon", timezone="America/New_York"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Guest",
            external_id="client-1",
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        self.service = Service.objects.create(
            category=category, name="Ladies Haircut",
            service_minutes=60, external_id="svc-1",
        )
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("25.00"),
            external_id="prod-1",
        )
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _write(self, rows, name="transactions-2026-10.csv"):
        path = Path(self.dir.name) / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=HEADER)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return path

    def _run(self):
        out = StringIO()
        call_command(
            "import_transactions_csv", self.dir.name,
            salon=self.salon.pk, stdout=out,
        )
        return out.getvalue()

    def _run_dry(self):
        out = StringIO()
        call_command(
            "import_transactions_csv", self.dir.name,
            salon=self.salon.pk, dry_run=True, stdout=out,
        )
        return out.getvalue()

    @staticmethod
    def _summary_lines(out):
        return [
            line for line in out.splitlines()
            if line.startswith(("IMPORT_SUMMARY", "IMPORT_SKIPPED"))
        ]

    def test_maps_totals_tips_date_and_links(self):
        self._write([
            row(unit_price="100.00", discount_amount="10.00",
                net_total_amount="90.00", payment_type_amounts="90.00"),
            row(item_type="PRODUCT", description="Shampoo",
                service_id="", product_id="prod-1",
                unit_price="25.00", net_total_amount="25.00",
                payment_type_amounts="90.00"),
        ])
        out = self._run()
        self.assertIn("sales_created=1", out)
        sale = Sale.objects.get()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.client, self.client)
        # Line arithmetic: (100 - 10) + 25 = 115 gross-of-tax net,
        # i.e. the settled net the export itself carries.
        self.assertEqual(sale.total, Decimal("115.00"))
        self.assertEqual(sale.discount_total, Decimal("10.00"))
        items = list(sale.items.all())
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].kind, SaleItem.Kind.SERVICE)
        self.assertEqual(items[0].service, self.service)
        self.assertEqual(items[0].discount_amount, Decimal("10.00"))
        self.assertEqual(items[1].kind, SaleItem.Kind.PRODUCT)
        self.assertEqual(items[1].product, self.product)
        # 2026-10-05 14:30 in America/New_York (EDT, UTC-4).
        self.assertEqual(
            sale.completed_at,
            datetime.datetime(
                2026, 10, 5, 14, 30,
                tzinfo=datetime.timezone(datetime.timedelta(hours=-4)),
            ),
        )
        payment = Payment.objects.get()
        self.assertEqual(payment.method, Payment.Method.EXTERNAL)
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertEqual(payment.amount, Decimal("90.00"))
        self.assertEqual(payment.provider_reference, "txn-1")
        summary = daily_sales_summary(
            self.salon, datetime.date(2026, 10, 5)
        )
        self.assertEqual(summary.sales_count, 1)
        self.assertEqual(summary.service_total, Decimal("100.00"))
        self.assertEqual(summary.retail_total, Decimal("25.00"))
        self.assertEqual(summary.net_total, Decimal("115.00"))

    def test_rerun_is_idempotent(self):
        self._write([row()])
        self._run()
        out = self._run()
        self.assertIn("sales_created=0", out)
        self.assertIn("sales_existing=1", out)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_void_rows_and_transactions_are_skipped(self):
        self._write([
            row(transaction_id="txn-void", void="1"),
            row(transaction_id="txn-mixed", void="1",
                description="Voided line"),
            row(transaction_id="txn-mixed", void="0",
                description="Live line", unit_price="40.00",
                net_total_amount="40.00", payment_type_amounts="40.00"),
        ])
        out = self._run()
        self.assertIn("void_transactions=1", out)
        self.assertIn("void_rows=2", out)
        sale = Sale.objects.get()
        self.assertEqual(sale.items.count(), 1)
        self.assertEqual(sale.total, Decimal("40.00"))

    def test_refund_imports_as_negative_sale(self):
        self._write([
            row(transaction_id="txn-sale"),
            row(transaction_id="txn-refund", purchase_type="REFUND",
                unit_price="-100.00", net_total_amount="-100.00",
                payment_type_amounts="-100.00",
                purchased_date="2026-10-07"),
        ])
        out = self._run()
        self.assertIn("refund_sales=1", out)
        refund = Sale.objects.get(
            payments__provider_reference="txn-refund"
        )
        self.assertEqual(refund.total, Decimal("-100.00"))
        payment = refund.payments.get()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual(payment.amount, Decimal("-100.00"))
        day = daily_sales_summary(self.salon, datetime.date(2026, 10, 7))
        self.assertEqual(day.gross_total, Decimal("-100.00"))

    def test_refund_line_with_negative_quantity_folds_to_net(self):
        # The export's refund shape: quantity -1, positive
        # unit price, negative discount — net -4.00 from
        # (20.00 * -1) - (-16.00). The models cannot hold a
        # negative quantity or discount, so the line folds
        # to quantity 1 at the exact net.
        self._write([
            row(transaction_id="txn-refund-qty", purchase_type="REFUND",
                item_type="PRODUCT", description="Returned Shampoo",
                service_id="", product_id="prod-1",
                quantity="-1", unit_price="20.00",
                discount_amount="-16.00", net_total_amount="-4.00",
                payment_type_amounts="-4.00"),
        ])
        self._run()
        item = SaleItem.objects.get()
        self.assertEqual(item.quantity, 1)
        self.assertEqual(item.unit_price, Decimal("-4.00"))
        self.assertEqual(item.discount_amount, Decimal("0.00"))
        self.assertEqual(item.line_total, Decimal("-4.00"))
        self.assertEqual(item.sale.total, Decimal("-4.00"))

    def test_unknown_client_imports_without_client(self):
        self._write([row(client_id="client-not-in-book")])
        out = self._run()
        self.assertIn("clients_unmatched=1", out)
        sale = Sale.objects.get()
        self.assertIsNone(sale.client)

    def test_nonrevenue_lines_never_become_items(self):
        self._write([
            row(transaction_id="txn-deposit", item_type="APPOINTMENT_DEPOSIT",
                description="Booking deposit", service_id="",
                unit_price="30.00", net_total_amount="30.00",
                payment_type_amounts="30.00"),
            row(transaction_id="txn-fee", item_type="CANCELLATION_FEE",
                description="Late cancel", service_id="",
                unit_price="20.00", net_total_amount="20.00",
                payment_type_amounts="20.00"),
        ])
        out = self._run()
        self.assertIn("sales_created=0", out)
        self.assertIn("nonrevenue_transactions=2", out)
        self.assertIn("excluded_amount=50.00", out)
        self.assertEqual(Sale.objects.count(), 0)

    def test_latin1_encoded_export_still_imports(self):
        # Older monthly exports carry accented names as Latin-1
        # bytes; the import must decode them, not crash or mangle.
        path = Path(self.dir.name) / "transactions-2026-10.csv"
        with open(path, "w", newline="", encoding="latin-1") as fh:
            writer = csv.DictWriter(fh, fieldnames=HEADER)
            writer.writeheader()
            writer.writerow(row(description="Café Treatment"))
        self._run()
        item = SaleItem.objects.get()
        self.assertEqual(item.description, "Café Treatment")

    def test_dry_run_writes_nothing_and_counts_match_real_run(self):
        self._write([
            row(),
            row(item_type="PRODUCT", description="Shampoo",
                service_id="", product_id="prod-1",
                unit_price="25.00", net_total_amount="25.00"),
            row(transaction_id="txn-refund", purchase_type="REFUND",
                unit_price="-100.00", net_total_amount="-100.00",
                payment_type_amounts="-100.00"),
            row(transaction_id="txn-void", void="1"),
            row(transaction_id="txn-fee", item_type="CANCELLATION_FEE",
                description="Late cancel", service_id="",
                unit_price="20.00", net_total_amount="20.00",
                payment_type_amounts="20.00"),
            row(transaction_id="txn-unknown",
                client_id="client-not-in-book"),
        ])
        dry_out = self._run_dry()
        # Nothing written: no sales, items or payments, and the
        # pre-existing book is untouched.
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleItem.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 1)
        self.assertIn("Dry run: no transactions were imported", dry_out)
        self.assertIn("files=1 rows_read=6 transactions=5", dry_out)
        self.assertIn("sales_created=3", dry_out)
        self.assertIn("refund_sales=1", dry_out)
        self.assertIn("items_created=4", dry_out)
        self.assertIn("payments_created=3", dry_out)
        self.assertIn("clients_unmatched=1", dry_out)
        self.assertIn("void_transactions=1", dry_out)
        self.assertIn("nonrevenue_transactions=1", dry_out)
        # The dry run's summary lines are exactly the real run's.
        real_out = self._run()
        self.assertEqual(
            self._summary_lines(dry_out), self._summary_lines(real_out))
        self.assertEqual(Sale.objects.count(), 3)
        self.assertEqual(SaleItem.objects.count(), 4)
        self.assertEqual(Payment.objects.count(), 3)

    def test_dry_run_after_real_run_counts_existing_and_writes_nothing(self):
        self._write([row()])
        self._run()
        dry_out = self._run_dry()
        self.assertIn("sales_created=0", dry_out)
        self.assertIn("sales_existing=1", dry_out)
        self.assertIn("items_created=0", dry_out)
        self.assertIn("payments_created=0", dry_out)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_dry_run_json_report_counts_records_and_names_unmapped(self):
        header = HEADER + ["legacy_code"]
        path = Path(self.dir.name) / "transactions-2026-10.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader()
            writer.writerow({**row(), "legacy_code": "LC-1"})
            writer.writerow({
                **row(transaction_id="txn-2"), "legacy_code": "LC-2"})
        out = self._run_dry()
        # The dry-run report is the leading JSON object (house
        # pattern); the summary lines follow it.
        report, _ = json.JSONDecoder().raw_decode(out)
        file_report = report[str(path)]
        self.assertEqual(file_report["record_count"], 2)
        self.assertIn("legacy_code", file_report["unmapped_keys"])
        self.assertNotIn("legacy_code", file_report["mapped_keys"])
        self.assertIn("transaction_id", file_report["mapped_keys"])
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cash_tender_maps_to_cash(self):
        self._write([
            row(payment_type_names="Cash", payment_type_amounts="100.00")
        ])
        self._run()
        self.assertEqual(Payment.objects.get().method, Payment.Method.CASH)
