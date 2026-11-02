import io
import os
import tempfile
from datetime import date

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.refunds_net_export import export_refunds_net_csv
from saloncore.models import Salon

START = date(2026, 11, 2)
END = date(2026, 11, 8)


class ExportRefundsNetCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_stdout_matches_service_export(self):
        out = io.StringIO()
        call_command("export_refunds_net", salon_id=self.salon.pk,
                     start_date=START.isoformat(),
                     end_date=END.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_refunds_net_csv(self.salon, START, END))

    def test_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_refunds_net", salon_id=self.salon.pk,
                         start_date=START.isoformat(),
                         end_date=END.isoformat(), output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(),
                    export_refunds_net_csv(self.salon, START, END))

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_refunds_net", salon_id=999999,
                         start_date=START.isoformat(),
                         end_date=END.isoformat())

    def test_reversed_window_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_refunds_net", salon_id=self.salon.pk,
                         start_date=END.isoformat(),
                         end_date=START.isoformat())
