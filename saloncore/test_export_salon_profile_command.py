import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from saloncore.salon_profile_export import export_salon_profile_csv


class ExportSalonProfileCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", tagline="Hello",
            primary_color="#123456")

    def _run(self, *args, **kwargs):
        out = io.StringIO()
        call_command("export_salon_profile", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_exports_profile_to_stdout(self):
        text = self._run(salon_id=self.salon.pk)
        self.assertEqual(text, export_salon_profile_csv(self.salon))
        self.assertIn("Example Salon", text)
        self.assertIn("#123456", text)

    def test_output_writes_file_and_not_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "salon.csv")
            text = self._run(salon_id=self.salon.pk, output=path)
            self.assertEqual(text, "")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), export_salon_profile_csv(self.salon))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=999999)

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "salon.csv")
            with self.assertRaises(CommandError):
                self._run(salon_id=self.salon.pk, output=path)
