"""Delegated-flag contract tests for messaging commands.

Counterpart of ``catalog/test_dry_run_nedb_safe.py`` for the
messaging app. Six messaging commands carry ``--dry-run``,
in three shapes, and no contract test pinned the delegation:

- flag-delegating: ``send_email_reminders``,
  ``send_sms_reminders`` and ``send_due_reminders`` pass
  ``dry_run`` (and ``within`` from ``--hours``) into their
  service functions -- the flag must arrive verbatim, with
  parser defaults matching the service signatures;
- writer-branching: ``create_campaign`` calls the writer
  ``campaigns.create_campaign`` on a real run and the
  validate-only ``campaigns.validate_create_campaign`` plus
  ``campaigns.audience_for`` on a dry run -- the writer must
  never be entered by a preview;
- sender/deleter-branching: ``send_campaign`` /
  ``discard_campaign`` call their service on a real run and,
  on a dry run, only the read helpers the services themselves
  use (``campaigns.audience_queryset`` /
  ``campaigns.audience_count``) -- the sender/deleter must
  never be entered by a preview, and nothing is written.

Export commands carry no ``--dry-run`` and are excluded:
their delegation is already pinned by their own command
tests. Fixtures are tiny synthetic records.
"""
import io
import inspect
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.campaign_send import CampaignSendSummary
from messaging.campaigns import (
    DiscardSummary, audience_queryset, create_campaign,
    discard_campaign, validate_create_campaign)
from messaging.dispatch import (
    ReminderDispatchSummary, send_due_reminders)
from messaging.email_reminders import (
    EmailDeliverySummary, send_due_email_reminders)
from messaging.management.commands.create_campaign import (
    Command as CreateCampaignCommand)
from messaging.management.commands.discard_campaign import (
    Command as DiscardCampaignCommand)
from messaging.management.commands.send_campaign import (
    Command as SendCampaignCommand)
from messaging.management.commands.send_due_reminders import (
    Command as SendDueCommand)
from messaging.management.commands.send_email_reminders import (
    Command as SendEmailCommand)
from messaging.management.commands.send_sms_reminders import (
    Command as SendSmsCommand)
from messaging.models import Campaign, CampaignSend, ReminderSend
from messaging.sms_reminders import (
    SmsDeliverySummary, send_due_sms_reminders)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

EMAIL_CMD = "messaging.management.commands.send_email_reminders"
SMS_CMD = "messaging.management.commands.send_sms_reminders"
DUE_CMD = "messaging.management.commands.send_due_reminders"
CREATE_CMD = "messaging.management.commands.create_campaign"
DISCARD_CMD = "messaging.management.commands.discard_campaign"
SEND_CMD = "messaging.management.commands.send_campaign"


def _run(name, *args):
    out = io.StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


def _defaults(command_cls, prog, args):
    parser = command_cls().create_parser("manage.py", prog)
    return parser.parse_args(list(args))


class ReminderDelegationTests(TestCase):
    """(a)+(c) the reminder commands delegate the flag."""

    def test_email_command_delegates_defaults(self):
        summary = EmailDeliverySummary(sent=2, skipped_not_opted_in=1)
        with mock.patch(
                f"{EMAIL_CMD}.send_due_email_reminders",
                return_value=summary) as service:
            text = _run("send_email_reminders")
        service.assert_called_once_with(
            now=None, within=timedelta(hours=24), dry_run=False)
        self.assertIn("2 sent", text)
        self.assertNotIn("Dry run", text)

    def test_email_command_delegates_dry_run_and_hours(self):
        summary = EmailDeliverySummary(sent=2, skipped_not_opted_in=1)
        with mock.patch(
                f"{EMAIL_CMD}.send_due_email_reminders",
                return_value=summary) as service:
            text = _run(
                "send_email_reminders", "--hours", "48", "--dry-run")
        service.assert_called_once_with(
            now=None, within=timedelta(hours=48), dry_run=True)
        self.assertIn("Dry run", text)
        self.assertIn("2 would send", text)

    def test_sms_command_delegates_defaults_and_dry_run(self):
        summary = SmsDeliverySummary(sent=1, skipped_missing_phone=1)
        with mock.patch(
                f"{SMS_CMD}.send_due_sms_reminders",
                return_value=summary) as service:
            text = _run("send_sms_reminders")
        service.assert_called_once_with(
            now=None, within=timedelta(hours=24), dry_run=False)
        self.assertIn("1 sent", text)
        with mock.patch(
                f"{SMS_CMD}.send_due_sms_reminders",
                return_value=summary) as service:
            text = _run("send_sms_reminders", "--dry-run")
        service.assert_called_once_with(
            now=None, within=timedelta(hours=24), dry_run=True)
        self.assertIn("1 would send", text)

    def test_combined_command_delegates_dry_run_and_hours(self):
        summary = ReminderDispatchSummary(
            email=EmailDeliverySummary(sent=1),
            sms=SmsDeliverySummary(sent=1))
        with mock.patch(
                f"{DUE_CMD}.send_due_reminders",
                return_value=summary) as service:
            text = _run("send_due_reminders", "--hours", "6", "--dry-run")
        service.assert_called_once_with(
            now=None, within=timedelta(hours=6), dry_run=True)
        self.assertIn("Dry run", text)
        self.assertIn("2 would send", text)

    def test_parser_defaults_match_service_signatures(self):
        cases = (
            (SendEmailCommand, "send_email_reminders",
             send_due_email_reminders),
            (SendSmsCommand, "send_sms_reminders",
             send_due_sms_reminders),
            (SendDueCommand, "send_due_reminders", send_due_reminders),
        )
        for command_cls, prog, service in cases:
            with self.subTest(command=prog):
                options = _defaults(command_cls, prog, [])
                params = inspect.signature(service).parameters
                self.assertEqual(options.hours, 24)
                self.assertIs(options.dry_run, False)
                self.assertIs(options.now, None)
                self.assertIs(params["now"].default, None)
                self.assertEqual(
                    params["within"].default, timedelta(hours=options.hours))
                self.assertIs(params["dry_run"].default, False)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com")
class ReminderDryRunSenderNotEnteredTests(TestCase):
    """(b) a reminder dry run enters no sender and writes nothing."""

    def setUp(self):
        salon = Salon.objects.create(name="Dry Salon")
        staff = StaffMember.objects.create(
            salon=salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=45)
        client = Client.objects.create(
            salon=salon, first_name="Test", last_name="Example",
            phone="555-0100", email="a@example.com",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(hours=2)
        Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

    def test_email_dry_run_opens_no_connection_and_records_nothing(self):
        with mock.patch(
                "messaging.email_reminders.get_connection") as connection:
            text = _run("send_email_reminders", "--dry-run")
        connection.assert_not_called()
        self.assertIn("1 would send", text)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ReminderSend.objects.count(), 0)

    def test_sms_dry_run_never_calls_single_sender(self):
        with mock.patch(
                "messaging.sms_reminders.send_sms_reminder") as sender:
            text = _run("send_sms_reminders", "--dry-run")
        sender.assert_not_called()
        self.assertIn("1 would send", text)
        self.assertEqual(ReminderSend.objects.count(), 0)

    def test_combined_dry_run_enters_neither_sender(self):
        with mock.patch(
                "messaging.email_reminders.get_connection") as connection, \
                mock.patch(
                "messaging.sms_reminders.send_sms_reminder") as sender:
            text = _run("send_due_reminders", "--dry-run")
        connection.assert_not_called()
        sender.assert_not_called()
        self.assertIn("2 would send", text)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ReminderSend.objects.count(), 0)


class CampaignFixture(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")

    def _campaign(self, **kwargs):
        defaults = dict(
            salon=self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello")
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)


class CreateCampaignDelegationTests(CampaignFixture):
    """(a)+(b)+(c) create_campaign writer vs validate-only."""

    def _args(self):
        return ("--salon-id", str(self.salon.pk), "--name", "Promo",
                "--channel", "sms", "--body", "Hello")

    def test_real_run_delegates_to_writer_verbatim(self):
        created = SimpleNamespace(pk=77, channel="sms", name="Promo")
        audience = mock.Mock()
        audience.count.return_value = 2
        with mock.patch(
                f"{CREATE_CMD}.create_campaign",
                return_value=created) as writer, mock.patch(
                f"{CREATE_CMD}.audience_for",
                return_value=audience) as audience_for:
            text = _run("create_campaign", *self._args())
        writer.assert_called_once_with(
            self.salon, "Promo", "sms", subject="", body="Hello")
        audience_for.assert_called_once_with(self.salon, "sms")
        self.assertIn("Created draft campaign 77", text)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_dry_run_uses_validate_only_and_never_the_writer(self):
        audience = mock.Mock()
        audience.count.return_value = 3
        with mock.patch(
                f"{CREATE_CMD}.create_campaign") as writer, mock.patch(
                f"{CREATE_CMD}.validate_create_campaign") as validate, \
                mock.patch(
                f"{CREATE_CMD}.audience_for",
                return_value=audience) as audience_for:
            text = _run("create_campaign", *self._args(), "--dry-run")
        writer.assert_not_called()
        validate.assert_called_once_with(
            self.salon, "Promo", "sms", subject="", body="Hello")
        audience_for.assert_called_once_with(self.salon, "sms")
        self.assertIn("Dry run", text)
        self.assertIn("audience 3", text)
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertEqual(CampaignSend.objects.count(), 0)

    def test_validate_signature_matches_writer_signature(self):
        def shape(func):
            return [
                (p.name, p.default)
                for p in inspect.signature(func).parameters.values()]
        self.assertEqual(
            shape(validate_create_campaign), shape(create_campaign))
        options = _defaults(
            CreateCampaignCommand, "create_campaign", self._args())
        params = inspect.signature(create_campaign).parameters
        self.assertIs(options.dry_run, False)
        self.assertEqual(options.subject, params["subject"].default)


class DiscardCampaignDelegationTests(CampaignFixture):
    """(a)+(b) discard_campaign deleter vs read-only count."""

    def test_real_run_delegates_to_deleter_verbatim(self):
        campaign = self._campaign()
        summary = DiscardSummary(
            campaign_id=campaign.pk, name=campaign.name,
            channel="sms", audience_count=2)
        with mock.patch(
                f"{DISCARD_CMD}.discard_campaign",
                return_value=summary) as deleter:
            text = _run(
                "discard_campaign", "--campaign-id", str(campaign.pk))
        deleter.assert_called_once_with(campaign)
        self.assertIn("Discarded draft campaign", text)

    def test_dry_run_counts_via_service_helper_and_never_deletes(self):
        campaign = self._campaign()
        with mock.patch(
                f"{DISCARD_CMD}.discard_campaign") as deleter, mock.patch(
                f"{DISCARD_CMD}.audience_count",
                return_value=4) as counter:
            text = _run(
                "discard_campaign", "--campaign-id", str(campaign.pk),
                "--dry-run")
        deleter.assert_not_called()
        counter.assert_called_once_with(campaign)
        self.assertIn("Dry run", text)
        self.assertIn("audience 4", text)
        self.assertTrue(Campaign.objects.filter(pk=campaign.pk).exists())

    def test_service_has_no_dry_run_flag_and_first_param_matches(self):
        discard_params = inspect.signature(discard_campaign).parameters
        self.assertNotIn("dry_run", discard_params)
        self.assertEqual(list(discard_params), ["campaign"])
        options = _defaults(
            DiscardCampaignCommand, "discard_campaign",
            ["--campaign-id", "1"])
        self.assertIs(options.dry_run, False)


class SendCampaignDelegationTests(CampaignFixture):
    """(a)+(b) send_campaign sender vs service audience read."""

    def test_real_run_delegates_to_sender_verbatim(self):
        campaign = self._campaign()
        summary = CampaignSendSummary(
            campaign_id=campaign.pk, channel="sms", sent=1)
        with mock.patch(
                f"{SEND_CMD}.send_campaign",
                return_value=summary) as sender:
            text = _run(
                "send_campaign", "--campaign-id", str(campaign.pk))
        sender.assert_called_once_with(campaign)
        self.assertIn("1 sent", text)

    def test_dry_run_reuses_service_audience_and_never_sends(self):
        Client.objects.create(
            salon=self.salon, first_name="C1", last_name="Example",
            phone="555-0100", email="c1@example.com",
            sms_opt_in=True, active=True)
        campaign = self._campaign()
        with mock.patch(f"{SEND_CMD}.send_campaign") as sender, \
                mock.patch(
                    f"{SEND_CMD}.audience_queryset",
                    wraps=audience_queryset) as audience:
            text = _run(
                "send_campaign", "--campaign-id", str(campaign.pk),
                "--dry-run")
        sender.assert_not_called()
        audience.assert_called_once_with(campaign)
        self.assertIn("Dry run", text)
        self.assertIn("1 would send", text)
        self.assertEqual(CampaignSend.objects.count(), 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIsNone(campaign.sent_at)

    def test_parser_default_and_service_shape(self):
        from messaging.campaign_send import send_campaign as service
        self.assertNotIn(
            "dry_run", inspect.signature(service).parameters)
        options = _defaults(
            SendCampaignCommand, "send_campaign", ["--campaign-id", "1"])
        self.assertIs(options.dry_run, False)
        self.assertEqual(options.campaign_id, 1)
