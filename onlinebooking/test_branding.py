from django.test import TestCase

from onlinebooking.branding import (
    BRANDING_FIELDS,
    UNBRANDED_BRANDING,
    branding_payload,
    salon_branding,
    salon_branding_for_id,
)
from saloncore.models import Salon

BRANDED = {
    "tagline": "Hair, beautifully.",
    "logo_url": "https://example.com/logo.png",
    "primary_color": "#2F4A3C",
    "accent_color": "#C9A227",
}


class SalonBrandingPayloadTests(TestCase):
    def test_full_branding_used_verbatim(self):
        salon = Salon.objects.create(name="Branded Salon", **BRANDED)
        self.assertEqual(salon_branding(salon), {
            "salon_id": salon.pk,
            "salon_name": "Branded Salon",
            **BRANDED,
            "is_branded": True,
            "fallbacks_applied": [],
        })

    def test_blank_salon_gets_wholly_unbranded_fallback(self):
        salon = Salon.objects.create(name="Plain Salon")
        payload = salon_branding(salon)
        self.assertEqual(payload, {
            "salon_id": salon.pk,
            "salon_name": "Plain Salon",
            **UNBRANDED_BRANDING,
            "is_branded": False,
            "fallbacks_applied": list(BRANDING_FIELDS),
        })
        # No invented identity: no tagline, no logo.
        self.assertEqual(payload["tagline"], "")
        self.assertEqual(payload["logo_url"], "")

    def test_partial_branding_falls_back_per_field(self):
        salon = Salon.objects.create(
            name="Partial Salon", primary_color="#123456")
        payload = salon_branding(salon)
        self.assertEqual(payload["primary_color"], "#123456")
        self.assertEqual(payload["tagline"], UNBRANDED_BRANDING["tagline"])
        self.assertEqual(payload["logo_url"], UNBRANDED_BRANDING["logo_url"])
        self.assertEqual(
            payload["accent_color"], UNBRANDED_BRANDING["accent_color"])
        self.assertTrue(payload["is_branded"])
        self.assertEqual(payload["fallbacks_applied"],
                         ["tagline", "logo_url", "accent_color"])

    def test_whitespace_only_fields_count_as_blank(self):
        salon = Salon.objects.create(
            name="Spaced Salon", tagline="   ", primary_color="  ")
        payload = salon_branding(salon)
        self.assertFalse(payload["is_branded"])
        self.assertEqual(payload["fallbacks_applied"], list(BRANDING_FIELDS))

    def test_surrounding_whitespace_is_stripped(self):
        salon = Salon.objects.create(
            name="Trim Salon", tagline="  Hello.  ")
        self.assertEqual(salon_branding(salon)["tagline"], "Hello.")

    def test_none_salon_returns_unbranded_payload(self):
        self.assertEqual(salon_branding(None), {
            "salon_id": None,
            "salon_name": "",
            **UNBRANDED_BRANDING,
            "is_branded": False,
            "fallbacks_applied": list(BRANDING_FIELDS),
        })

    def test_alias_matches_main_function(self):
        salon = Salon.objects.create(name="Alias Salon", **BRANDED)
        self.assertEqual(branding_payload(salon), salon_branding(salon))

    def test_payload_is_salon_scoped(self):
        branded = Salon.objects.create(name="Branded", **BRANDED)
        plain = Salon.objects.create(name="Plain")
        self.assertEqual(salon_branding(branded)["tagline"],
                         BRANDED["tagline"])
        self.assertEqual(salon_branding(plain)["tagline"], "")
        self.assertEqual(salon_branding_for_id(branded.pk)["logo_url"],
                         BRANDED["logo_url"])
        self.assertFalse(salon_branding_for_id(plain.pk)["is_branded"])

    def test_for_id_unknown_or_none_never_leaks_other_salon(self):
        Salon.objects.create(name="Branded", **BRANDED)
        for bad_id in (None, 999999):
            payload = salon_branding_for_id(bad_id)
            self.assertIsNone(payload["salon_id"])
            self.assertFalse(payload["is_branded"])
            self.assertEqual(payload["primary_color"],
                             UNBRANDED_BRANDING["primary_color"])

    def test_read_only_and_fresh_dict_each_call(self):
        salon = Salon.objects.create(name="Stable Salon", **BRANDED)
        first = salon_branding(salon)
        first["tagline"] = "Mutated by caller"
        first["fallbacks_applied"].append("tagline")
        self.assertEqual(salon_branding(salon)["tagline"], BRANDED["tagline"])
        self.assertEqual(salon_branding(salon)["fallbacks_applied"], [])
        salon.refresh_from_db()
        for field, value in BRANDED.items():
            self.assertEqual(getattr(salon, field), value)
        self.assertEqual(Salon.objects.count(), 1)
