"""Tests for the demo-mode banner in the app shell."""
from django.test import TestCase, override_settings
from django.urls import reverse

from saloncore.models import Salon


class DemoBannerTests(TestCase):
    def setUp(self):
        Salon.objects.create(name="Demo Salon")

    @override_settings(DEMO_MODE=True)
    def test_banner_renders_in_demo_mode(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertContains(
            response, "Demo mode — sample salon with invented data")

    @override_settings(DEMO_MODE=False)
    def test_banner_absent_when_demo_mode_off(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertNotContains(response, "demo-banner")
