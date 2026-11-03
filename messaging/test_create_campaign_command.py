"""Tests for the create_campaign command + service.

The command is a thin wrapper around
``messaging.campaigns.create_campaign``: these tests pin that
a real run creates exactly one DRAFT campaign through that
service, that ``--dry-run`` creates none but prints the
audience count resolved via ``messaging.campaigns.audience_for``
for the named channel, and that invalid channel, empty body,
empty name, missing email subject, and unknown salon surface
as ``CommandError`` with nothing created. Nothing is ever
sent: no CampaignSend rows and no mail on either path.
Fixtures are tiny synthetic records -- unit logic only.
"""
import io

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase, override_settings

from clients.models import Client
from messaging.campaigns import (
    audience_for, create_campaign, validate_create_campaign)
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CreateCampaignCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")
        self.other = Salon.objects.create(name="Salon Two")
        self._n = 0

    def _client(self, salon=None, **kwargs):
        self._n += 1
        defaults = dict(
            salon=salon or self.salon, first_name=f"C{self._n}",
            last_name="Example", phone="555-0100",
            email=f"c{self._n}@example.com",
            sms_opt_in=False, email_opt_in=False, active=True)
        defaults.update(kwargs)
        return Client.objects.create(**defaults)

    def _run(self, *args, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("stdout", out)
        call_command("create_campaign", *args, **kwargs)
        return out.getvalue()

    def test_command_registered(self):
        self.assertIn("create_campaign", get_commands())

    def test_real_run_creates_exactly_one_draft_sms(self):
        self._client(sms_opt_in=True)
        text = self._run(
            salon_id=self.salon.pk, name="Spring Offer",
            channel="sms", body="Hello clients")
        self.assertEqual(Campaign.objects.count(), 1)
        (campaign,) = Campaign.objects.all()
        self.assertEqual(campaign.salon, self.salon)
        self.assertEqual(campaign.name, "Spring Offer")
        self.assertEqual(campaign.channel, Campaign.Channel.SMS)
        self.assertEqual(campaign.subject, "")
        self.assertEqual(campaign.body, "Hello clients")
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIsNone(campaign.sent_at)
        self.assertIn("Created draft campaign", text)
        self.assertIn("audience 1", text)
        self.assertEqual(CampaignSend.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_real_run_email_with_subject_string_args(self):
        text = self._run(
            "--salon-id", str(self.salon.pk), "--name", "News",
            "--channel", "email", "--subject", "November News",
            "--body", "Body text")
        self.assertEqual(Campaign.objects.count(), 1)
        (campaign,) = Campaign.objects.all()
        self.assertEqual(campaign.channel, Campaign.Channel.EMAIL)
        self.assertEqual(campaign.subject, "November News")
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIn(str(campaign.pk), text)

    def test_service_creates_draft_directly(self):
        campaign = create_campaign(
            self.salon, "Direct", "sms", body="Hi")
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_dry_run_creates_none_and_prints_sms_audience(self):
        self._client(sms_opt_in=True)
        self._client(sms_opt_in=True, email_opt_in=True)
        self._client(email_opt_in=True)               # not sms audience
        self._client(sms_opt_in=True, active=False)   # inactive excluded
        self._client(salon=self.other, sms_opt_in=True)  # other salon
        expected = audience_for(self.salon, "sms").count()
        self.assertEqual(expected, 2)
        text = self._run(
            salon_id=self.salon.pk, name="Preview", channel="sms",
            body="Hello", dry_run=True)
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertIn("Dry run", text)
        self.assertIn(f"audience {expected}", text)
        self.assertEqual(CampaignSend.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_email_audience_and_flag_form(self):
        self._client(email_opt_in=True)
        self._client(sms_opt_in=True)
        text = self._run(
            "--salon-id", str(self.salon.pk), "--name", "News",
            "--channel", "email", "--subject", "Hi",
            "--body", "Body", "--dry-run")
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertIn("Dry run", text)
        self.assertIn("audience 1", text)

    def test_dry_run_leaves_existing_campaign_count_unchanged(self):
        # NEDB regression: dry-run must write nothing at all, so a
        # pre-existing campaign's count is unchanged (not just 0).
        existing = create_campaign(
            self.salon, "Existing", "sms", body="Already here")
        self._client(sms_opt_in=True)
        text = self._run(
            salon_id=self.salon.pk, name="Preview", channel="sms",
            body="Hello", dry_run=True)
        self.assertIn("Dry run", text)
        self.assertIn("audience 1", text)
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(
            list(Campaign.objects.values_list("pk", flat=True)),
            [existing.pk])
        self.assertEqual(CampaignSend.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_validation_matches_real_run_and_writes_nothing(self):
        create_campaign(self.salon, "Existing", "sms", body="Here")
        cases = [
            dict(name="Bad", channel="pigeon", body="Hello"),
            dict(name="Empty", channel="sms", body=""),
            dict(name="Empty", channel="sms", body="   "),
            dict(name="  ", channel="sms", body="Hello"),
            dict(name="News", channel="email", body="Body"),
            dict(name="x" * 201, channel="sms", body="Hello"),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(CommandError):
                    self._run(
                        salon_id=self.salon.pk, dry_run=True, **kwargs)
                self.assertEqual(Campaign.objects.count(), 1)
        with self.assertRaises(CommandError):
            self._run(
                salon_id=999999, name="Ghost", channel="sms",
                body="Hello", dry_run=True)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_validate_helper_writes_nothing_and_returns_unsaved(self):
        campaign = validate_create_campaign(
            self.salon, "  Preview  ", "sms", body="Hello")
        self.assertIsNone(campaign.pk)
        self.assertEqual(campaign.name, "Preview")
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertEqual(Campaign.objects.count(), 0)
        with self.assertRaises(ValidationError):
            validate_create_campaign(
                self.salon, "Bad", "pigeon", body="Hello")
        self.assertEqual(Campaign.objects.count(), 0)

    def test_invalid_channel_is_error_and_creates_nothing(self):
        for extra in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                self._run(
                    salon_id=self.salon.pk, name="Bad",
                    channel="pigeon", body="Hello", **extra)
        self.assertEqual(Campaign.objects.count(), 0)
        with self.assertRaises(ValidationError):
            create_campaign(self.salon, "Bad", "pigeon", body="Hello")
        self.assertEqual(Campaign.objects.count(), 0)

    def test_empty_body_is_error_and_creates_nothing(self):
        for body in ("", "   "):
            for extra in ({}, {"dry_run": True}):
                with self.assertRaises(CommandError):
                    self._run(
                        salon_id=self.salon.pk, name="Empty",
                        channel="sms", body=body, **extra)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_empty_name_and_missing_email_subject_are_errors(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.pk, name="  ", channel="sms",
                body="Hello")
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.pk, name="News", channel="email",
                body="Body")
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.pk, name="News", channel="email",
                body="Body", dry_run=True)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_unknown_salon_is_error_and_creates_nothing(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=999999, name="Ghost", channel="sms",
                body="Hello")
        self.assertEqual(Campaign.objects.count(), 0)
