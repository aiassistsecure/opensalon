import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, ServiceCategory, StaffLevel
from saloncore.structure_export import (
    export_service_categories_csv,
    export_staff_levels_csv,
    export_structure_csv,
)


class ExportStructureCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=2, active=False)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)

    def _run(self, *args, **kwargs):
        out = io.StringIO()
        call_command("export_structure", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_default_exports_both_sections_to_stdout(self):
        text = self._run(salon_id=self.salon.pk)
        self.assertEqual(text, export_structure_csv(self.salon))
        self.assertIn("Color", text)
        self.assertIn("Level 6", text)

    def test_section_categories_only(self):
        text = self._run(salon_id=self.salon.pk, section="categories")
        self.assertEqual(text, export_service_categories_csv(self.salon))
        self.assertIn("Color", text)
        self.assertNotIn("Level 6", text)

    def test_section_levels_only(self):
        text = self._run(salon_id=self.salon.pk, section="levels")
        self.assertEqual(text, export_staff_levels_csv(self.salon))
        self.assertIn("Level 6", text)
        self.assertNotIn("Color", text)

    def test_empty_salon_writes_headers_only(self):
        empty = Salon.objects.create(name="Empty Salon")
        text = self._run(salon_id=empty.pk)
        self.assertEqual(text, export_structure_csv(empty))
        self.assertNotIn("Color", text)

    def test_output_writes_file_and_not_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "structure.csv")
            text = self._run(salon_id=self.salon.pk, output=path)
            self.assertEqual(text, "")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), export_structure_csv(self.salon))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=999999)

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "structure.csv")
            with self.assertRaises(CommandError):
                self._run(salon_id=self.salon.pk, output=path)
