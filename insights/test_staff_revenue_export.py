import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.staff_revenue import revenue_by_staff
from insights.staff_revenue_export import (
    STAFF_REVENUE_FIELDNAMES,
    export_staff_revenue_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class StaffRevenueExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff_a = StaffMember.objects.create(
            salon=self.salon, display_name="Alice"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Olga"
        )
        self.client_a = Client.objects.create(
            salon=self.salon, first_name="Ann", last_name="A"
        )
        self.client_b = Client.objects.create(
            salon=self.salon, first_name="Ben", last_name="B"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, client, staff, *, day_offset=0):
        start = datetime(2026, 11, 2 + day_offset, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=staff, service=self.cut,
            start=start, end=start + timedelta(minutes=45),
        )

    def _sale(self, client=None, *, salon=None, day_offset=0):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client,
            status=Sale.Status.COMPLETED,
        )
        stamp = datetime(2026, 11, 2 + day_offset, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        sale.refresh_from_db()
        return sale

    def _rows(self, salon=None, start=START, end=END):
        text = export_staff_revenue_csv(salon or self.salon, start, end)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_and_attributed_row_match_service(self):
        self._appt(self.client_a, self.staff_a, day_offset=1)
        sale = self._sale(self.client_a, day_offset=1)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("85.00"), service=self.cut,
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, quantity=1,
            unit_price=Decimal("24.00"),
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERIES, quantity=1,
            unit_price=Decimal("150.00"),
        )
        text = export_staff_revenue_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, STAFF_REVENUE_FIELDNAMES)
        self.assertEqual(
            STAFF_REVENUE_FIELDNAMES,
            ["staff_name", "service_revenue", "retail_revenue",
             "series_revenue", "total"],
        )
        rows = self._rows()
        service_rows = revenue_by_staff(self.salon, START, END)
        self.assertEqual(len(rows), len(service_rows))
        self.assertEqual(rows, [{
            "staff_name": "Alice",
            "service_revenue": "85.00",
            "retail_revenue": "24.00",
            "series_revenue": "150.00",
            "total": "259.00",
        }])
        self.assertEqual(Decimal(rows[0]["total"]), service_rows[0].total)

    def test_unattributed_bucket_row_present(self):
        sale = self._sale(self.client_b, day_offset=3)  # no appointment
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("30.00"), service=self.cut,
        )
        rows = self._rows()
        self.assertEqual(rows, [{
            "staff_name": "Unattributed",
            "service_revenue": "30.00",
            "retail_revenue": "0.00",
            "series_revenue": "0.00",
            "total": "30.00",
        }])

    def test_series_only_sale_exports_series_column(self):
        self._appt(self.client_a, self.staff_a, day_offset=2)
        sale = self._sale(self.client_a, day_offset=2)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERIES, quantity=1,
            unit_price=Decimal("200.00"),
        )
        rows = self._rows()
        self.assertEqual(rows, [{
            "staff_name": "Alice",
            "service_revenue": "0.00",
            "retail_revenue": "0.00",
            "series_revenue": "200.00",
            "total": "200.00",
        }])

    def test_period_passthrough(self):
        self._appt(self.client_a, self.staff_a, day_offset=0)
        sale = self._sale(self.client_a, day_offset=0)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("40.00"), service=self.cut,
        )
        self._appt(self.client_a, self.staff_a, day_offset=5)
        late = self._sale(self.client_a, day_offset=5)
        SaleItem.objects.create(
            sale=late, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("99.00"), service=self.cut,
        )
        rows = self._rows(start=START, end=date(2026, 11, 2))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], "40.00")

    def test_salon_scoping(self):
        other_client = Client.objects.create(
            salon=self.other, first_name="Ora", last_name="O"
        )
        self._appt(other_client, self.other_staff, day_offset=0)
        sale = self._sale(other_client, salon=self.other, day_offset=0)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("70.00"), service=self.cut,
        )
        self.assertEqual(self._rows(), [])
        other_rows = self._rows(salon=self.other)
        self.assertEqual([r["staff_name"] for r in other_rows], ["Olga"])
        self.assertEqual(other_rows[0]["total"], "70.00")

    def test_empty_is_header_only_and_read_only(self):
        text = export_staff_revenue_csv(self.salon, START, END)
        self.assertEqual(
            list(csv.reader(io.StringIO(text))), [STAFF_REVENUE_FIELDNAMES]
        )
        self._appt(self.client_a, self.staff_a, day_offset=0)
        self._sale(self.client_a, day_offset=0)
        before = Sale.objects.count()
        export_staff_revenue_csv(self.salon, START, END)
        self.assertEqual(Sale.objects.count(), before)
