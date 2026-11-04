"""Campaign audience export: the list behind the audience counts."""
import csv
import io

from django.core.exceptions import ValidationError
from django.test import TestCase

from clients.models import Client
from messaging.campaign_audience_export import (
    AUDIENCE_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    audience_export_row,
    campaign_audience_csv,
    export_campaign_audience,
    export_campaign_audience_csv,
)
from messaging.campaigns import audience_count, audience_queryset
from messaging.models import Campaign
from saloncore.models import Salon


class CampaignAudienceExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Audience Salon",
                                          timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon",
                                          timezone="UTC")
        self._n = 0

    def _client(self, salon=None, **kwargs):
        self._n += 1
        defaults = dict(
            salon=salon or self.salon, first_name=f"C{self._n}",
            last_name="Example", phone="555-0100",
            email=f"c{self._n}@example.com",
            sms_opt_in=False, email_opt_in=False, active=True,
        )
        defaults.update(kwargs)
        return Client.objects.create(**defaults)

    def _campaign(self, salon=None, **kwargs):
        defaults = dict(
            salon=salon or self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello",
        )
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def test_header_and_dict_keys(self):
        client = self._client(sms_opt_in=True)
        campaign = self._campaign()
        text = export_campaign_audience_csv(campaign)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], AUDIENCE_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, AUDIENCE_EXPORT_FIELDNAMES)
        records = export_campaign_audience(campaign)
        self.assertEqual(len(records), 1)
        self.assertEqual(list(records[0].keys()),
                         AUDIENCE_EXPORT_FIELDNAMES)
        self.assertEqual(records[0], {
            "id": client.pk, "salon_id": self.salon.pk,
            "external_id": "", "first_name": client.first_name,
            "last_name": "Example", "email": client.email,
            "phone": "555-0100", "sms_opt_in": True,
            "email_opt_in": False, "active": True,
            "created_at": client.created_at.isoformat()})
        self.assertEqual(audience_export_row(client), records[0])
        self.assertIs(campaign_audience_csv,
                      export_campaign_audience_csv)

    def test_rows_are_exactly_the_audience_queryset(self):
        both = self._client(sms_opt_in=True, email_opt_in=True)
        sms_only = self._client(sms_opt_in=True)
        self._client(email_opt_in=True)
        self._client(sms_opt_in=True, active=False)
        self._client(salon=self.other, sms_opt_in=True)
        campaign = self._campaign(channel=Campaign.Channel.SMS)
        records = export_campaign_audience(campaign)
        self.assertEqual([r["id"] for r in records],
                         [c.pk for c in audience_queryset(campaign)])
        self.assertEqual({r["id"] for r in records},
                         {both.pk, sms_only.pk})
        self.assertEqual(len(records), audience_count(campaign))

    def test_email_channel_uses_email_opt_in(self):
        email_only = self._client(email_opt_in=True)
        self._client(sms_opt_in=True)
        campaign = self._campaign(channel=Campaign.Channel.EMAIL,
                                  subject="Hi")
        records = export_campaign_audience(campaign)
        self.assertEqual([r["id"] for r in records], [email_only.pk])
        self.assertTrue(records[0]["email_opt_in"])
        self.assertFalse(records[0]["sms_opt_in"])

    def test_audience_service_order_is_preserved(self):
        # Client's default order: last_name, then first_name --
        # not insertion order and not id order.
        self._client(last_name="Zephyr", first_name="Ann",
                     sms_opt_in=True)
        self._client(last_name="Alpha", first_name="Zed",
                     sms_opt_in=True)
        self._client(last_name="Alpha", first_name="Amy",
                     sms_opt_in=True)
        campaign = self._campaign()
        names = [(r["last_name"], r["first_name"])
                 for r in export_campaign_audience(campaign)]
        self.assertEqual(names, [("Alpha", "Amy"), ("Alpha", "Zed"),
                                 ("Zephyr", "Ann")])

    def test_csv_agrees_with_dict_export(self):
        self._client(sms_opt_in=True, last_name="Comma, Name")
        self._client(sms_opt_in=True)
        campaign = self._campaign()
        parsed = list(csv.DictReader(io.StringIO(
            export_campaign_audience_csv(campaign))))
        records = export_campaign_audience(campaign)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(row["id"], str(record["id"]))
            self.assertEqual(row["last_name"], record["last_name"])
            self.assertEqual(row["sms_opt_in"],
                             str(record["sms_opt_in"]))
            self.assertEqual(row["created_at"], record["created_at"])

    def test_empty_audience_exports_header_only(self):
        self._client()  # opted out on both channels
        campaign = self._campaign()
        self.assertEqual(export_campaign_audience(campaign), [])
        self.assertEqual(
            export_campaign_audience_csv(campaign),
            ",".join(AUDIENCE_EXPORT_FIELDNAMES) + "\n")

    def test_unsaved_campaign_rejected_by_audience_service(self):
        campaign = Campaign(salon=self.salon, name="Unsaved",
                            channel="sms", body="Hello")
        with self.assertRaises(ValidationError):
            export_campaign_audience(campaign)
