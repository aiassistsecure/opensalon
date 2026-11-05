import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from onlinebooking.branding_export import export_branding, export_branding_csv
from saloncore.models import Salon


class ExportBrandingCommandTests(TestCase):
    def setUp(self):
        self.branded = Salon.objects.create(
            name="Branded Salon", tagline="Hair, beautifully.",
            primary_color="#2F4A3C")
        self.plain = Salon.objects.create(name="Plain Salon")

    def _run(self, *args, **kwargs):
        out = io.StringIO()
        call_command("export_branding", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_exports_derived_payload_to_stdout(self):
        text = self._run(salon_id=self.plain.pk)
        self.assertEqual(text, export_branding_csv(self.plain))
        # Derived, not stored: the fallback colour is exported
        # even though the salon stored a blank.
        self.assertIn("#212121", text)
        self.assertIn("tagline;logo_url;primary_color;accent_color", text)

    def test_exports_branded_salon_to_stdout(self):
        text = self._run(salon_id=self.branded.pk)
        self.assertEqual(text, export_branding_csv(self.branded))
        self.assertIn("Hair, beautifully.", text)
        self.assertIn("#2F4A3C", text)

    def test_output_writes_file_and_not_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "branding.csv")
            text = self._run(salon_id=self.branded.pk, output=path)
            self.assertEqual(text, "")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), export_branding_csv(self.branded))

    def test_default_format_is_csv_byte_identical(self):
        text = self._run(salon_id=self.plain.pk)
        self.assertEqual(text, export_branding_csv(self.plain))

    def test_explicit_csv_matches_service(self):
        text = self._run(salon_id=self.branded.pk, format="csv")
        self.assertEqual(text, export_branding_csv(self.branded))
        out = io.StringIO()
        call_command(
            "export_branding", "--salon-id", str(self.branded.pk),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_branding_csv(self.branded))

    def test_json_parses_and_equals_dict_service(self):
        row = export_branding(self.plain)
        text = self._run(salon_id=self.plain.pk, format="json")
        self.assertEqual(json.loads(text), row)
        self.assertEqual(
            text, json.dumps(row, indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertIn("#212121", text)
        self.assertIn("tagline", text)

    def test_json_for_branded_salon_matches_dict_service(self):
        row = export_branding(self.branded)
        text = self._run(salon_id=self.branded.pk, format="json")
        self.assertEqual(json.loads(text), row)
        out = io.StringIO()
        call_command(
            "export_branding", "--salon-id", str(self.branded.pk),
            "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), row)

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "branding.json")
            text = self._run(
                salon_id=self.branded.pk, format="json", output=path)
            self.assertEqual(text, "")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    json.load(fh), export_branding(self.branded))

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=self.branded.pk, format="xml")
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_branding", "--salon-id", str(self.branded.pk),
                "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=999999)

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "branding.csv")
            with self.assertRaises(CommandError):
                self._run(salon_id=self.branded.pk, output=path)
