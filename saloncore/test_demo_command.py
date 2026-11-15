"""Tests for the demo management command. Synthetic only."""
import io
import os
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from checkout.models import Payment, Refund, Sale
from clients.models import Client
from saloncore.models import Salon, Service
from team.models import StaffMember


def run_demo():
    out = io.StringIO()
    with mock.patch.dict(os.environ, {"OPENSALON_DEMO": "1"}):
        call_command("demo", stdout=out)
    return out.getvalue()


class DemoCommandTests(TestCase):
    def test_refuses_without_demo_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("demo", stdout=io.StringIO())
        self.assertEqual(Salon.objects.count(), 0)

    def test_seeds_a_populated_salon(self):
        text = run_demo()
        (salon,) = Salon.objects.all()
        self.assertEqual(salon.name, "Demo Salon")
        self.assertEqual(salon.timezone, "America/New_York")
        self.assertEqual(StaffMember.objects.filter(salon=salon).count(), 6)
        self.assertEqual(
            Service.objects.filter(category__salon=salon).count(), 24)
        self.assertEqual(Client.objects.filter(salon=salon).count(), 80)
        self.assertGreater(
            Appointment.objects.filter(
                staff_member__salon=salon).count(), 0)
        self.assertEqual(Sale.objects.filter(salon=salon).count(), 450)
        self.assertGreater(Refund.objects.count(), 0)
        self.assertIn("Demo salon ready", text)

    def test_sale_payments_match_totals(self):
        run_demo()
        for sale in Sale.objects.all():
            paid = sum(
                (p.amount for p in sale.payments.all()), start=0)
            self.assertEqual(paid, sale.total)

    def test_idempotent_second_run_same_counts(self):
        run_demo()
        before = (
            Salon.objects.count(), StaffMember.objects.count(),
            Client.objects.count(), Sale.objects.count(),
            Appointment.objects.count(), Payment.objects.count(),
        )
        run_demo()
        after = (
            Salon.objects.count(), StaffMember.objects.count(),
            Client.objects.count(), Sale.objects.count(),
            Appointment.objects.count(), Payment.objects.count(),
        )
        self.assertEqual(before, after)
