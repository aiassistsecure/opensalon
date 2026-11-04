import csv
import io

from django.test import TestCase

from onlinebooking.branding import BRANDING_FIELDS, UNBRANDED_BRANDING
from onlinebooking.branding_export import (
    BRANDING_EXPORT_FIELDNAMES,
    BRANDING_FIELDNAMES,
    EXPORT_FIELDNAMES,
    branding_csv,
    branding_row,
    export_branding,
    export_branding_csv,
)
from saloncore.models import Salon

BRANDED = {
    "tagline": "Hair, beautifully.",
    "logo_url": "https://example.com/logo.png",
    "primary_color": "#2F4A3C",
    "accent_color": "#C9A227",
}


class BrandingExportTests(TestCase):
    def test_fieldnames_are_exactly_the_payload_keys(self):
        self.assertEqual(BRANDING_FIELDNAMES, [
            "salon_id", "salon_name", "tagline", "logo_url",
            "primary_color", "accent_color", "is_branded",
            "fallbacks_applied",
        ])
        self.assertEqual(BRANDING_EXPORT_FIELDNAMES, BRANDING_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, BRANDING_FIELDNAMES)

    def test_unbranded_salon_exports_derived_fallback_payload(self):
        salon = Salon.objects.create(name="Plain Salon")
        row = export_branding(salon)
        # The derived payload, NOT the stored blanks: fallback
        # colours in place, every field named as fallen back.
        self.assertEqual(row, {
            "salon_id": salon.pk,
            "salon_name": "Plain Salon",
            **UNBRANDED_BRANDING,
            "is_branded": False,
            "fallbacks_applied": list(BRANDING_FIELDS),
        })
        self.assertEqual(row["primary_color"], "#212121")
        self.assertNotEqual(row["primary_color"], salon.primary_color)

    def test_branded_salon_exports_stored_values(self):
        salon = Salon.objects.create(name="Branded Salon", **BRANDED)
        self.assertEqual(export_branding(salon), {
            "salon_id": salon.pk,
            "salon_name": "Branded Salon",
            **BRANDED,
            "is_branded": True,
            "fallbacks_applied": [],
        })

    def test_partial_branding_falls_back_per_field(self):
        salon = Salon.objects.create(
            name="Partial Salon", primary_color="#123456")
        row = export_branding(salon)
        self.assertEqual(row["primary_color"], "#123456")
        self.assertEqual(row["accent_color"],
                         UNBRANDED_BRANDING["accent_color"])
        self.assertTrue(row["is_branded"])
        self.assertEqual(row["fallbacks_applied"],
                         ["tagline", "logo_url", "accent_color"])

    def test_accepts_pk_and_row_matches_export(self):
        salon = Salon.objects.create(name="Pk Salon", **BRANDED)
        self.assertEqual(export_branding(salon.pk), export_branding(salon))
        self.assertEqual(branding_row(salon), export_branding(salon))

    def test_missing_or_unsaved_salon_exports_none(self):
        self.assertIsNone(export_branding(None))
        self.assertIsNone(export_branding(999999))
        self.assertIsNone(export_branding(Salon(name="Unsaved")))

    def test_csv_built_from_the_one_dict(self):
        salon = Salon.objects.create(name="Plain Salon")
        text = export_branding_csv(salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], BRANDING_FIELDNAMES)
        row = export_branding(salon)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(parsed), 1)
        for field in BRANDING_FIELDNAMES:
            if field == "fallbacks_applied":
                self.assertEqual(parsed[0][field],
                                 ";".join(row["fallbacks_applied"]))
            elif field == "salon_id":
                self.assertEqual(parsed[0][field], str(row[field]))
            elif field == "is_branded":
                self.assertEqual(parsed[0][field], str(row[field]))
            else:
                self.assertEqual(parsed[0][field], row[field])

    def test_csv_for_branded_salon(self):
        salon = Salon.objects.create(name="Branded Salon", **BRANDED)
        parsed = list(csv.DictReader(
            io.StringIO(export_branding_csv(salon))))
        self.assertEqual(parsed, [{
            "salon_id": str(salon.pk),
            "salon_name": "Branded Salon",
            **BRANDED,
            "is_branded": "True",
            "fallbacks_applied": "",
        }])

    def test_csv_for_missing_salon_is_header_alone(self):
        self.assertEqual(
            export_branding_csv(999999),
            ",".join(BRANDING_FIELDNAMES) + "\n")

    def test_csv_alias_matches(self):
        salon = Salon.objects.create(name="Alias Salon")
        self.assertEqual(branding_csv(salon), export_branding_csv(salon))

    def test_read_only(self):
        salon = Salon.objects.create(name="Stable Salon", **BRANDED)
        export_branding(salon)
        export_branding_csv(salon)
        salon.refresh_from_db()
        for field, value in BRANDED.items():
            self.assertEqual(getattr(salon, field), value)
        self.assertEqual(Salon.objects.count(), 1)
