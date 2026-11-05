"""Tests for the export_payments management command.

The command is a thin wrapper around
``checkout.payment_export.export_payments_csv`` and
``checkout.payment_export.export_payments``: these tests
pin that its stdout and file output match those services verbatim
(CSV byte-identical, JSON parsing to the dict service's rows),
that it scopes to the requested salon, and that unknown salons,
unknown formats, and unwritable output fail cleanly as
``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.payment_export import export_payments, export_payments_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportPaymentsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._payment(self.salon)
        self._payment(self.other)

    def _payment(self, salon, status=Payment.Status.COMPLETED,
                 method=Payment.Method.CASH):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=_stamp(DAY))
        payment = Payment.objects.create(
            sale=sale, method=method,
            amount=Decimal("85.00"), status=status)
        stamp = _stamp(DAY)
        Payment.objects.filter(pk=payment.pk).update(
            created_at=stamp, updated_at=stamp)
        payment.refresh_from_db()
        return payment

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, NEXT))

    def test_stdout_single_day_when_end_date_omitted(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, None))
        self.assertEqual(
            out.getvalue(), export_payments_csv(self.salon, DAY))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_payments_csv(self.salon, DAY, DAY))
        self.assertNotEqual(text, export_payments_csv(self.other, DAY, DAY))
        # Header + exactly this salon's one payment row.
        self.assertEqual(len(text.strip().splitlines()), 2)
        self.assertIn(f",{self.salon.pk},", text)
        other_out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.other.pk,
            start_date=DAY, end_date=DAY, stdout=other_out)
        self.assertIn(f",{self.other.pk},", other_out.getvalue())
        self.assertNotEqual(other_out.getvalue(), text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "payments.csv")
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_payments_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_sale_id_filters_to_one_sale(self):
        first = self._payment(self.salon)
        self._payment(self.salon)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=first.sale_id,
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, sale=first.sale))
        # Header + exactly that sale's one payment row.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)
        self.assertIn(f",{first.sale_id},", out.getvalue())

    def test_sale_id_via_cli_flag(self):
        first = self._payment(self.salon)
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--sale-id", str(first.sale_id), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, sale=first.sale))

    def test_no_sale_id_is_salon_wide_default(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_payments_csv(self.salon, DAY, DAY))
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, sale=None))

    def test_status_filters_to_matching_payments(self):
        self._payment(self.salon, status=Payment.Status.REFUNDED)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, status="completed",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, status="completed"))
        # Header + exactly the one completed payment from setUp.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_status_via_cli_flag(self):
        self._payment(self.salon, status=Payment.Status.PENDING)
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--status", "pending", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, status="pending"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_status_composes_with_sale_id(self):
        refunded = self._payment(
            self.salon, status=Payment.Status.REFUNDED)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=refunded.sale_id,
            status="completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(
                self.salon, DAY, DAY, sale=refunded.sale,
                status="completed"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_no_status_is_default(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, status=None))

    def test_method_filters_to_matching_payments(self):
        self._payment(self.salon, method=Payment.Method.EXTERNAL)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, method="cash",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, method="cash"))
        # Header + exactly the one cash payment from setUp.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_method_via_cli_flag(self):
        self._payment(self.salon, method=Payment.Method.EXTERNAL)
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--method", "external", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, method="external"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_method_composes_with_sale_id_and_status(self):
        external = self._payment(
            self.salon, method=Payment.Method.EXTERNAL)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=external.sale_id,
            status="completed", method="cash", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(
                self.salon, DAY, DAY, sale=external.sale,
                status="completed", method="cash"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_no_method_is_default(self):
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY, method=None))

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(),
            export_payments_csv(self.salon, DAY, DAY))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_payments_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        self._payment(self.salon)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_payments(self.salon, DAY, DAY))
        # Exactly this salon's two payment rows, no header line.
        self.assertEqual(len(json.loads(out.getvalue())), 2)

    def test_json_via_cli_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_payments", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_payments(self.salon, DAY, DAY))

    def test_json_composes_with_sale_id_status_method_and_window(self):
        external = self._payment(
            self.salon, method=Payment.Method.EXTERNAL)
        out = io.StringIO()
        call_command(
            "export_payments", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=external.sale_id,
            status="completed", method="cash", format="json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_payments(
                self.salon, DAY, DAY, sale=external.sale,
                status="completed", method="cash"))
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "payments.json")
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_payments(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="xml",
                stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", DAY.isoformat(),
                "--format", "xml", stdout=io.StringIO())

    def test_unknown_sale_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, sale_id=999999,
                stdout=io.StringIO())

    def test_sale_from_other_salon_raises_command_error(self):
        theirs = self._payment(self.other)
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, sale_id=theirs.sale_id,
                stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "missing-dir", "payments.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_payments", salon_id=self.salon.pk,
                    start_date=DAY, end_date=DAY, output=bad,
                    stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_payments", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
