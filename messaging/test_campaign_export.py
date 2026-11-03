"""Campaign verbatim export: stored Campaign rows, incl. body/updated_at."""
import csv
import io
from datetime import datetime
from datetime import timezone as dt_timezone

from django.test import TestCase

from messaging.campaign_export import (
    CAMPAIGN_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    campaign_export_row,
    campaigns_csv,
    export_campaign,
    export_campaign_csv,
    export_campaigns,
    export_campaigns_csv,
)
from messaging.models import Campaign
from saloncore.models import Salon

SENT_AT = datetime(2026, 10, 3, 9, 0, tzinfo=dt_timezone.utc)


class CampaignExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Campaign Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.email = Campaign.objects.create(
            salon=self.salon, name="November News",
            channel=Campaign.Channel.EMAIL, subject="Hello",
            body="News body, with comma\nand a second line",
            status=Campaign.Status.DRAFT)
        self.sms = Campaign.objects.create(
            salon=self.salon, name="November Offer",
            channel=Campaign.Channel.SMS, subject="",
            body="Offer body", status=Campaign.Status.SENT,
            sent_at=SENT_AT)

    def test_header_and_dict_keys(self):
        text = export_campaigns_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], CAMPAIGN_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, CAMPAIGN_EXPORT_FIELDNAMES)
        self.assertIn("body", CAMPAIGN_EXPORT_FIELDNAMES)
        self.assertIn("updated_at", CAMPAIGN_EXPORT_FIELDNAMES)
        records = export_campaigns(self.salon)
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(list(record.keys()),
                             CAMPAIGN_EXPORT_FIELDNAMES)
        self.assertIs(export_campaign, export_campaigns)
        self.assertIs(export_campaign_csv, export_campaigns_csv)
        self.assertIs(campaigns_csv, export_campaigns_csv)

    def test_rows_verbatim_incl_body_and_updated_at(self):
        by_name = {r["name"]: r for r in export_campaigns(self.salon)}
        self.assertEqual(by_name["November News"], {
            "id": self.email.pk, "salon_id": self.salon.pk,
            "name": "November News", "channel": "email",
            "subject": "Hello",
            "body": "News body, with comma\nand a second line",
            "status": "draft", "sent_at": None,
            "created_at": self.email.created_at.isoformat(),
            "updated_at": self.email.updated_at.isoformat()})
        sms = by_name["November Offer"]
        self.assertEqual(sms["body"], "Offer body")
        self.assertEqual(sms["subject"], "")
        self.assertEqual(sms["status"], "sent")
        self.assertEqual(sms["sent_at"], SENT_AT.isoformat())
        self.assertEqual(sms["updated_at"],
                         self.sms.updated_at.isoformat())
        self.assertEqual(campaign_export_row(self.email),
                         by_name["November News"])

    def test_csv_round_trips_body_verbatim(self):
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(self.salon))))
        by_name = {r["name"]: r for r in parsed}
        self.assertEqual(by_name["November News"]["body"],
                         "News body, with comma\nand a second line")
        self.assertEqual(by_name["November News"]["sent_at"], "")
        self.assertEqual(by_name["November Offer"]["sent_at"],
                         SENT_AT.isoformat())

    def test_model_ordering_newest_first(self):
        records = export_campaigns(self.salon)
        self.assertEqual([r["id"] for r in records],
                         [self.sms.pk, self.email.pk])

    def test_salon_scoping_empty_and_none(self):
        Campaign.objects.create(
            salon=self.other, name="Elsewhere", channel="email",
            subject="Hi", body="Body")
        self.assertEqual(len(export_campaigns(self.salon)), 2)
        self.assertEqual(len(export_campaigns(self.other)), 1)
        self.assertEqual(export_campaigns(self.other)[0]["name"],
                         "Elsewhere")
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_campaigns(empty), [])
        self.assertEqual(
            export_campaigns_csv(empty),
            ",".join(CAMPAIGN_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_campaigns(None), [])
        self.assertEqual(
            export_campaigns_csv(None),
            ",".join(CAMPAIGN_EXPORT_FIELDNAMES) + "\n")

    def test_no_send_count_or_aggregates(self):
        for record in export_campaigns(self.salon):
            self.assertNotIn("send_count", record)
