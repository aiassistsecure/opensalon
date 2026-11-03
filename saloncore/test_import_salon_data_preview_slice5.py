"""import_salon_data --dry-run slice-5 preview (cycle 145).

Slice-5 sections (sales, sale_items, sale_payments, refunds,
cashups, receipts) gain the same read-only import_preview as
slices 1-4, mirroring the writer's identity rules. Refunds,
cashups and receipts are get_or_create in the writer, so an
existing row never previews as would-update. Writer never
entered in dry-run.
"""
import io
import json
import tempfile
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Product
from checkout.models import (
    Cashup, Payment, Receipt, Refund, Sale, SaleItem)
from clients.models import Client
from saloncore.management.commands.import_salon_data import SECTIONS
from saloncore.models import Salon, Service, ServiceCategory
from saloncore.test_import_salon_data import _minimal_data

SLICE5 = ("sales", "sale_items", "sale_payments", "refunds",
          "cashups", "receipts")
MODELS = (Sale, SaleItem, Payment, Refund, Cashup, Receipt)
def _dt(hour, minute=0):
    return datetime(2026, 11, 2, hour, minute,
                    tzinfo=dt_timezone.utc)


AT = _dt(15)


def _data():
    data = _minimal_data()
    data["products"] = [
        {"id": 90, "salon_id": 1, "external_id": "prod-1",
         "name": "Shampoo", "sku": "SKU-1", "barcode": "111",
         "price": "24.50", "active": True}]
    data["sales"] = [
        {"id": 200, "salon_id": 1, "client_id": 50,
         "client_external_id": "cli-1", "status": "completed",
         "discount_amount": "10.00",
         "created_at": "2026-11-02T15:00:00+00:00",
         "completed_at": "2026-11-02T15:05:00+00:00",
         "voided_at": None, "void_reason": ""}]
    data["sale_items"] = [
        {"id": 201, "sale_id": 200, "kind": "service",
         "service_id": 20, "service_external_id": "svc-1",
         "product_id": None, "product_external_id": None,
         "description": "Single Process", "quantity": 1,
         "unit_price": "85.00", "discount_amount": "5.00"}]
    data["sale_payments"] = [
        {"id": 202, "sale_id": 200, "method": "cash",
         "amount": "80.00", "status": "completed",
         "created_at": "2026-11-02T15:01:00+00:00"}]
    data["refunds"] = [
        {"id": 203, "sale_id": 200, "amount": "10.00",
         "reason": "Goodwill", "tender": "cash",
         "created_at": "2026-11-02T16:00:00+00:00"}]
    data["cashups"] = [
        {"id": 204, "salon_id": 1,
         "period_start": "2026-11-02T09:00:00+00:00",
         "period_end": "2026-11-02T17:00:00+00:00",
         "tender_totals": {"cash": "80.00"}, "total": "80.00",
         "note": "", "created_at": "2026-11-02T17:05:00+00:00"}]
    data["receipts"] = [
        {"id": 205, "sale_id": 200, "salon_name": "TF6 Salon",
         "lines": [{"description": "Single Process",
                    "kind": "service", "quantity": 1,
                    "unit_price": "85.00", "line_total": "80.00"}],
         "total": "80.00",
         "tender": [{"method": "cash", "amount": "80.00",
                     "status": "completed"}],
         "recipient_email": "",
         "issued_at": "2026-11-02T15:02:00+00:00",
         "sent_at": None}]
    return data


class ImportSalonDataPreviewSlice5Tests(TestCase):
    def write_data(self, data):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        return fh.name

    def run_dry(self, data):
        out = io.StringIO()
        call_command("import_salon_data", self.write_data(data),
                     dry_run=True, stdout=out)
        return json.loads(out.getvalue())

    def counts(self):
        return {m.__name__: m.objects.count() for m in MODELS}

    def store_matching(self):
        salon = Salon.objects.create(
            name="TF6 Salon", timezone="UTC", currency="USD")
        category = ServiceCategory.objects.create(
            salon=salon, name="Color", sort_order=1, active=True)
        service = Service.objects.create(
            category=category, external_id="svc-1",
            name="Single Process", service_minutes=45, active=True)
        Product.objects.create(
            salon=salon, external_id="prod-1", name="Shampoo",
            sku="SKU-1", barcode="111", price=Decimal("24.50"),
            active=True)
        client = Client.objects.create(
            salon=salon, external_id="cli-1", first_name="Ada",
            last_name="Optin", active=True)
        sale = Sale.objects.create(
            salon=salon, client=client, status="completed",
            discount_amount=Decimal("10.00"),
            completed_at=_dt(15, 5))
        Sale.objects.filter(pk=sale.pk).update(created_at=AT)
        SaleItem.objects.create(
            sale=sale, kind="service", service=service,
            description="Single Process", quantity=1,
            unit_price=Decimal("85.00"),
            discount_amount=Decimal("5.00"))
        payment = Payment.objects.create(
            sale=sale, method="cash", amount=Decimal("80.00"),
            status="completed")
        Payment.objects.filter(pk=payment.pk).update(
            created_at=_dt(15, 1))
        Refund.objects.create(
            sale=sale, amount=Decimal("10.00"), reason="Goodwill",
            tender="cash")
        Refund.objects.filter(sale=sale).update(
            created_at=_dt(16))
        cashup = Cashup.objects.create(
            salon=salon, period_start=_dt(9), period_end=_dt(17),
            tender_totals={"cash": "80.00"},
            total=Decimal("80.00"), note="")
        Cashup.objects.filter(pk=cashup.pk).update(
            created_at=_dt(17, 5))
        Receipt.objects.create(
            sale=sale, salon_name="TF6 Salon",
            lines=[{"description": "Single Process"}],
            total=Decimal("80.00"), tender=[],
            recipient_email="")
        return sale

    def test_preview_present_on_slice5_sections_only(self):
        reports = self.run_dry(_data())
        self.assertEqual(set(reports), set(SECTIONS))
        for section in SLICE5:
            self.assertIn("import_preview", reports[section], section)

    def test_would_create_all_slice5_on_empty_db(self):
        reports = self.run_dry(_data())
        for section in SLICE5:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_data())
        for section in SLICE5:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_only_where_writer_updates(self):
        self.store_matching()
        data = _data()
        data["sales"][0]["discount_amount"] = "12.00"
        data["sale_items"][0]["quantity"] = 2
        data["sale_payments"][0]["amount"] = "90.00"
        data["refunds"][0]["amount"] = "11.00"
        data["cashups"][0]["total"] = "81.00"
        data["receipts"][0]["total"] = "81.00"
        reports = self.run_dry(data)
        for section in SLICE5[:3]:
            self.assertEqual(
                reports[section]["import_preview"]["would_update"],
                1, section)
        # Refund amount is part of its get_or_create natural
        # key: a different amount is a new refund, not an update.
        refund = reports["refunds"]["import_preview"]
        self.assertEqual(
            (refund["would_create"], refund["would_update"]), (1, 0))
        # Cashup/receipt defaults are creation-only snapshots:
        # an existing row is returned untouched — never updated.
        for section in ("cashups", "receipts"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_update"], preview["would_unchanged"]),
                (0, 1), section)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _data()
        data["sales"].append(dict(data["sales"][0], id=210))
        data["sale_payments"].append(
            dict(data["sale_payments"][0], id=211, amount="85.00"))
        data["refunds"].append(dict(data["refunds"][0], id=212))
        data["receipts"].append(dict(data["receipts"][0], id=213))
        reports = self.run_dry(data)
        sale = reports["sales"]["import_preview"]
        self.assertEqual(
            (sale["would_create"], sale["would_unchanged"]), (1, 1))
        pay = reports["sale_payments"]["import_preview"]
        self.assertEqual(
            (pay["would_create"], pay["would_update"]), (1, 1))
        for section in ("refunds", "receipts"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_create"], preview["would_unchanged"]),
                (1, 1), section)

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _data()
        data["sales"][0]["discount_amount"] = "12.00"  # would-update
        data["refunds"].append(
            {"id": 214, "sale_id": 200, "amount": "3.00",
             "reason": "", "tender": "cash",
             "created_at": "2026-11-02T18:00:00+00:00"})  # would-create
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(
            Sale.objects.get().discount_amount, Decimal("10.00"))
