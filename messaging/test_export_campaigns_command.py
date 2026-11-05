"""export_campaigns command: thin wrapper over campaign_export."""
import io
import json
import os
import tempfile
from datetime import date, datetime, timezone

from django.core.management import CommandError, call_command
from django.test import TestCase

from messaging.campaign_export import export_campaigns, export_campaigns_csv
from messaging.models import Campaign
from saloncore.models import Salon


class ExportCampaignsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        Campaign.objects.create(
            salon=self.salon, name="Spring Offer",
            channel="sms", body="Hello body")
        Campaign.objects.create(
            salon=self.salon, name="Spring Email",
            channel="email", subject="Hi", body="Email body")
        Campaign.objects.create(
            salon=self.other, name="Other Campaign",
            channel="sms", body="Elsewhere")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.salon))
        self.assertIn("Hello body", out.getvalue())
        self.assertIn("updated_at", out.getvalue().splitlines()[0])

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.other.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.other))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campaigns.csv")
            call_command("export_campaigns", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_campaigns_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_status_filter_matches_service(self):
        Campaign.objects.create(
            salon=self.salon, name="Sent One", channel="sms",
            body="Sent body", status=Campaign.Status.SENT,
            sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     status="sent", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, status="sent"))
        self.assertIn("Sent One", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_status_filter_no_match_is_header_only(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     status="sent", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, status="sent"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_no_status_matches_unfiltered_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_campaigns_csv(self.salon, status=None))

    def test_channel_filter_matches_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     channel="email", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, channel="email"))
        self.assertIn("Spring Email", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_channel_filter_composes_with_status(self):
        Campaign.objects.create(
            salon=self.salon, name="Sent Email", channel="email",
            body="Sent email body", status=Campaign.Status.SENT,
            sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     channel="email", status="sent", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, channel="email",
                                  status="sent"))
        self.assertIn("Sent Email", out.getvalue())
        self.assertNotIn("Spring Email", out.getvalue())

    def test_channel_filter_no_match_is_header_only(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     channel="EMAIL", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, channel="EMAIL"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_no_channel_matches_unfiltered_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_campaigns_csv(self.salon, channel=None))

    def _dated(self, name, when, salon=None, **kwargs):
        campaign = Campaign.objects.create(
            salon=salon or self.salon, name=name,
            channel=kwargs.pop("channel", "email"),
            subject="Hi", body="Body", **kwargs)
        Campaign.objects.filter(pk=campaign.pk).update(created_at=when)
        return campaign

    def test_date_window_matches_service(self):
        self._dated("Dated One", datetime(
            2026, 10, 3, 12, 0, tzinfo=timezone.utc))
        self._dated("Outside", datetime(
            2026, 10, 9, 12, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     start_date="2026-10-03", end_date="2026-10-03",
                     stdout=out)
        from datetime import date as _date
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon,
                                  start_date=_date(2026, 10, 3),
                                  end_date=_date(2026, 10, 3)))
        self.assertIn("Dated One", out.getvalue())
        self.assertNotIn("Outside", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_date_window_single_bound_and_aliases(self):
        self._dated("Dated One", datetime(
            2026, 10, 3, 12, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", "--salon-id", str(self.salon.pk),
                     "--start-date", "2026-10-03",
                     "--end-date", "2026-10-03", stdout=out)
        self.assertIn("Dated One", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     end_date="2026-10-03", stdout=out)
        self.assertIn("Dated One", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_date_window_composes_with_status_and_channel(self):
        self._dated("Dated Sent SMS", datetime(
            2026, 10, 3, 12, 0, tzinfo=timezone.utc),
            channel="sms", status=Campaign.Status.SENT,
            sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     start_date="2026-10-03", end_date="2026-10-03",
                     status="sent", channel="sms", stdout=out)
        self.assertIn("Dated Sent SMS", out.getvalue())
        self.assertNotIn("Spring Offer", out.getvalue())
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     start_date="2026-10-03", end_date="2026-10-03",
                     status="draft", channel="sms", stdout=out)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_date_window_no_match_is_header_only(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     start_date="2020-01-01", end_date="2020-01-02",
                     stdout=out)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_no_dates_matches_unfiltered_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     stdout=out)
        from datetime import date as _date  # noqa: F401
        self.assertEqual(
            out.getvalue(),
            export_campaigns_csv(self.salon, start_date=None,
                                  end_date=None))

    def test_invalid_date_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_campaigns", salon_id=self.salon.pk,
                         start_date="2026-13-40", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_campaigns", salon_id=self.salon.pk,
                         end_date="not-a-date", stdout=io.StringIO())

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_campaigns",
                         salon_id=self.salon.pk + 1000,
                         stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.csv")
            with self.assertRaises(CommandError):
                call_command("export_campaigns", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.salon))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.salon))
        out = io.StringIO()
        call_command("export_campaigns", "--salon-id", str(self.salon.pk),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_campaigns(self.salon))
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_campaigns(self.salon), indent=2) + "\n")

    def test_json_via_cli_flags(self):
        out = io.StringIO()
        call_command("export_campaigns", "--salon-id", str(self.salon.pk),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_campaigns(self.salon))

    def test_json_composes_with_status_and_channel(self):
        Campaign.objects.create(
            salon=self.salon, name="Sent Email", channel="email",
            body="Sent email body", status=Campaign.Status.SENT,
            sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     format="json", status="sent", channel="email",
                     stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_campaigns(self.salon, status="sent", channel="email"))
        self.assertEqual(
            [row["name"] for row in json.loads(out.getvalue())],
            ["Sent Email"])

    def test_json_composes_with_date_window(self):
        self._dated("Dated One", datetime(
            2026, 10, 3, 12, 0, tzinfo=timezone.utc))
        self._dated("Outside", datetime(
            2026, 10, 9, 12, 0, tzinfo=timezone.utc))
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk,
                     format="json", start_date="2026-10-03",
                     end_date="2026-10-03", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_campaigns(self.salon, start_date=date(2026, 10, 3),
                             end_date=date(2026, 10, 3)))
        self.assertEqual(
            [row["name"] for row in json.loads(out.getvalue())],
            ["Dated One"])

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_campaigns", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("export_campaigns", "--salon-id",
                         str(self.salon.pk), "--format", "xml",
                         stdout=io.StringIO())
