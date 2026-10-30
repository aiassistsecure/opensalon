from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from saloncore.admin import PriceChangeAdmin
from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)

ALL_MODELS = [Salon, ServiceCategory, Service, StaffLevel, ServicePrice, PriceChange]


class AdminRegistrationTests(TestCase):
    def test_all_saloncore_models_registered(self):
        for model in ALL_MODELS:
            self.assertIn(model, admin.site._registry)

    def test_pricechange_registered_with_pricechange_admin(self):
        self.assertIsInstance(admin.site._registry[PriceChange], PriceChangeAdmin)


class PriceChangeAdminReadOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="pw"
        )
        salon = Salon.objects.create(name="Mint On The Avenue")
        category = ServiceCategory.objects.create(name="Haircuts", salon=salon)
        service = Service.objects.create(
            name="Haircut", category=category, service_minutes=45
        )
        level = StaffLevel.objects.create(name="Level 6", salon=salon)
        price = ServicePrice.objects.create(
            service=service, staff_level=level, amount=Decimal("85.00")
        )
        cls.change = PriceChange.objects.create(
            service_price=price,
            old_amount=Decimal("80.00"),
            new_amount=Decimal("85.00"),
            changed_by="tester",
        )

    def setUp(self):
        self.client.force_login(self.superuser)
        self.model_admin = admin.site._registry[PriceChange]
        factory = RequestFactory()
        self.request = factory.get("/admin/")
        self.request.user = self.superuser

    def test_permission_methods_all_false_for_superuser(self):
        self.assertFalse(self.model_admin.has_add_permission(self.request))
        self.assertFalse(
            self.model_admin.has_change_permission(self.request, self.change)
        )
        self.assertFalse(
            self.model_admin.has_delete_permission(self.request, self.change)
        )
        # Viewing the audit trail stays allowed.
        self.assertTrue(
            self.model_admin.has_view_permission(self.request, self.change)
        )

    def test_other_models_remain_writable(self):
        salon_admin = admin.site._registry[Salon]
        self.assertTrue(salon_admin.has_add_permission(self.request))
        self.assertTrue(salon_admin.has_change_permission(self.request))
        self.assertTrue(salon_admin.has_delete_permission(self.request))

    def test_changelist_is_viewable(self):
        url = reverse("admin:saloncore_pricechange_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_view_forbidden(self):
        url = reverse("admin:saloncore_pricechange_add")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_change_view_is_read_only_and_post_forbidden(self):
        url = reverse(
            "admin:saloncore_pricechange_change", args=[self.change.pk]
        )
        # With view-but-not-change permission Django serves a read-only
        # form (200) and rejects any attempt to save through it (403).
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"new_amount": "99.00"})
        self.assertEqual(response.status_code, 403)
        self.change.refresh_from_db()
        self.assertEqual(self.change.new_amount, Decimal("85.00"))

    def test_delete_view_forbidden(self):
        url = reverse(
            "admin:saloncore_pricechange_delete", args=[self.change.pk]
        )
        self.assertEqual(self.client.get(url).status_code, 403)
