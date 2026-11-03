import csv
import io

from django.test import TestCase

from saloncore.models import Salon
from saloncore.salon_profile_export import (
    SALON_FIELDNAMES,
    SALON_PROFILE_FIELDNAMES,
    export_salon_profile,
    export_salon_profile_csv,
    export_salon_profiles,
    export_salon_profiles_csv,
    salon_profile_csv,
    salon_profile_row,
    salon_profiles_csv,
)


def _full_salon(**kw):
    kw.setdefault("name", "Mint Example")
    kw.setdefault("timezone", "America/New_York")
    kw.setdefault("currency", "EUR")
    kw.setdefault("tagline", "Hair, honestly.")
    kw.setdefault("logo_url", "https://example.com/logo.png")
    kw.setdefault("primary_color", "#123456")
    kw.setdefault("accent_color", "#abcdef")
    return Salon.objects.create(**kw)


class SalonProfileExportTests(TestCase):
    def test_fieldnames_cover_every_model_field(self):
        model_fields = [
            f.name for f in Salon._meta.concrete_fields
        ]
        self.assertEqual(SALON_FIELDNAMES, model_fields)
        self.assertEqual(SALON_PROFILE_FIELDNAMES, model_fields)

    def test_row_matches_created_record_verbatim(self):
        salon = _full_salon()
        row = export_salon_profile(salon)
        self.assertEqual(row, {
            "id": salon.pk, "name": "Mint Example",
            "timezone": "America/New_York", "currency": "EUR",
            "tagline": "Hair, honestly.",
            "logo_url": "https://example.com/logo.png",
            "primary_color": "#123456", "accent_color": "#abcdef",
            "created_at": salon.created_at.isoformat(),
            "updated_at": salon.updated_at.isoformat(),
        })
        self.assertEqual(salon_profile_row(salon), row)

    def test_defaults_and_blank_branding_export_verbatim(self):
        salon = Salon.objects.create(name="Plain Salon")
        row = export_salon_profile(salon)
        self.assertEqual(row["timezone"], "UTC")
        self.assertEqual(row["currency"], "USD")
        self.assertEqual(row["tagline"], "")
        self.assertEqual(row["logo_url"], "")
        self.assertEqual(row["primary_color"], "")
        self.assertEqual(row["accent_color"], "")

    def test_accepts_pk_and_missing_salon_is_none(self):
        salon = _full_salon()
        self.assertEqual(
            export_salon_profile(salon.pk), export_salon_profile(salon))
        self.assertIsNone(export_salon_profile(999999))
        self.assertIsNone(export_salon_profile(None))
        self.assertIsNone(export_salon_profile(Salon(name="Unsaved")))

    def test_profiles_lists_all_in_name_order(self):
        b = _full_salon(name="B Salon")
        a = _full_salon(name="A Salon")
        rows = export_salon_profiles()
        self.assertEqual([r["id"] for r in rows], [a.pk, b.pk])

    def test_csv_agrees_with_dict_export(self):
        salon = _full_salon()
        parsed = list(csv.DictReader(io.StringIO(
            export_salon_profile_csv(salon))))
        row = export_salon_profile(salon)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(
            parsed[0], {k: ("" if v is None else str(v))
                         for k, v in row.items()})
        self.assertIs(salon_profile_csv, export_salon_profile_csv)

    def test_missing_salon_csv_is_header_only(self):
        text = export_salon_profile_csv(999999)
        self.assertEqual(
            text, ",".join(SALON_FIELDNAMES) + "\n")

    def test_profiles_csv_agrees_with_list_export(self):
        _full_salon(name="A Salon")
        _full_salon(name="B Salon")
        parsed = list(csv.DictReader(io.StringIO(
            export_salon_profiles_csv())))
        self.assertEqual(
            [int(r["id"]) for r in parsed],
            [r["id"] for r in export_salon_profiles()])
        self.assertIs(salon_profiles_csv, export_salon_profiles_csv)
