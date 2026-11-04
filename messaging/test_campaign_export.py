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

    def test_status_filter_dict_and_csv(self):
        records = export_campaigns(self.salon, status="draft")
        self.assertEqual([r["name"] for r in records],
                         ["November News"])
        self.assertEqual(records[0]["status"], "draft")
        records = export_campaigns(self.salon, status="sent")
        self.assertEqual([r["name"] for r in records],
                         ["November Offer"])
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(self.salon, status="sent"))))
        self.assertEqual([r["name"] for r in parsed],
                         ["November Offer"])
        # CSV twin agrees with the dict export, same args.
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(self.salon, status="draft"))))
        self.assertEqual(
            [(r["name"], r["status"]) for r in parsed],
            [(r["name"], r["status"]) for r in
             export_campaigns(self.salon, status="draft")])

    def test_status_filter_accepts_enum_and_defaults_identical(self):
        self.assertEqual(
            export_campaigns(self.salon,
                             status=Campaign.Status.DRAFT),
            export_campaigns(self.salon, status="draft"))
        self.assertEqual(export_campaigns(self.salon, status=None),
                         export_campaigns(self.salon))
        self.assertEqual(export_campaigns_csv(self.salon, status=None),
                         export_campaigns_csv(self.salon))

    def test_status_filter_exact_no_case_folding(self):
        self.assertEqual(export_campaigns(self.salon, status="DRAFT"),
                         [])
        self.assertEqual(export_campaigns(self.salon, status="Sent"),
                         [])
        self.assertEqual(
            export_campaigns_csv(self.salon, status="DRAFT"),
            ",".join(CAMPAIGN_EXPORT_FIELDNAMES) + "\n")

    def test_status_filter_composes_with_salon_scope(self):
        Campaign.objects.create(
            salon=self.other, name="Elsewhere Draft",
            channel="email", subject="Hi", body="Body",
            status=Campaign.Status.DRAFT)
        Campaign.objects.create(
            salon=self.other, name="Elsewhere Sent",
            channel="email", subject="Hi", body="Body",
            status=Campaign.Status.SENT, sent_at=SENT_AT)
        records = export_campaigns(self.other, status="draft")
        self.assertEqual([r["name"] for r in records],
                         ["Elsewhere Draft"])
        self.assertEqual(export_campaigns(None, status="draft"), [])

    def test_channel_filter_dict_and_csv(self):
        records = export_campaigns(self.salon, channel="email")
        self.assertEqual([r["name"] for r in records],
                         ["November News"])
        self.assertEqual(records[0]["channel"], "email")
        records = export_campaigns(self.salon, channel="sms")
        self.assertEqual([r["name"] for r in records],
                         ["November Offer"])
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(self.salon, channel="sms"))))
        self.assertEqual([r["name"] for r in parsed],
                         ["November Offer"])
        # CSV twin agrees with the dict export, same args.
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(self.salon, channel="email"))))
        self.assertEqual(
            [(r["name"], r["channel"]) for r in parsed],
            [(r["name"], r["channel"]) for r in
             export_campaigns(self.salon, channel="email")])

    def test_channel_filter_accepts_enum_and_defaults_identical(self):
        self.assertEqual(
            export_campaigns(self.salon,
                             channel=Campaign.Channel.EMAIL),
            export_campaigns(self.salon, channel="email"))
        self.assertEqual(export_campaigns(self.salon, channel=None),
                         export_campaigns(self.salon))
        self.assertEqual(export_campaigns_csv(self.salon, channel=None),
                         export_campaigns_csv(self.salon))

    def test_channel_filter_exact_no_case_folding(self):
        self.assertEqual(export_campaigns(self.salon, channel="EMAIL"),
                         [])
        self.assertEqual(export_campaigns(self.salon, channel="Sms"),
                         [])
        self.assertEqual(
            export_campaigns_csv(self.salon, channel="EMAIL"),
            ",".join(CAMPAIGN_EXPORT_FIELDNAMES) + "\n")

    def test_channel_filter_composes_with_status_and_salon(self):
        # sms+sent matches only the sms row; sms+draft matches none.
        records = export_campaigns(
            self.salon, status="sent", channel="sms")
        self.assertEqual([r["name"] for r in records],
                         ["November Offer"])
        self.assertEqual(export_campaigns(
            self.salon, status="draft", channel="sms"), [])
        self.assertEqual(export_campaigns(
            self.salon, status="sent", channel="email"), [])
        Campaign.objects.create(
            salon=self.other, name="Elsewhere SMS",
            channel="sms", subject="Hi", body="Body")
        records = export_campaigns(self.other, channel="sms")
        self.assertEqual([r["name"] for r in records],
                         ["Elsewhere SMS"])
        self.assertEqual(export_campaigns(None, channel="sms"), [])

    def _dated(self, name, when, **kwargs):
        campaign = Campaign.objects.create(
            salon=self.salon, name=name,
            channel=kwargs.pop("channel", "email"),
            subject="Hi", body="Body", **kwargs)
        Campaign.objects.filter(pk=campaign.pk).update(created_at=when)
        campaign.refresh_from_db()
        return campaign

    def test_date_window_dict_and_csv(self):
        early = self._dated(
            "Early", datetime(2026, 10, 1, 12, 0,
                              tzinfo=dt_timezone.utc))
        mid = self._dated(
            "Mid", datetime(2026, 10, 3, 23, 59,
                            tzinfo=dt_timezone.utc))
        late = self._dated(
            "Late", datetime(2026, 10, 5, 0, 1,
                             tzinfo=dt_timezone.utc))
        from datetime import date as _date
        records = export_campaigns(
            self.salon, start_date=_date(2026, 10, 3),
            end_date=_date(2026, 10, 3))
        # Whole end day included; setUp rows (created today) excluded.
        self.assertEqual([r["name"] for r in records], ["Mid"])
        parsed = list(csv.DictReader(io.StringIO(
            export_campaigns_csv(
                self.salon, start_date=_date(2026, 10, 3),
                end_date=_date(2026, 10, 3)))))
        self.assertEqual([r["name"] for r in parsed], ["Mid"])
        # CSV twin agrees with dict export, same args.
        self.assertEqual(
            [(r["name"], r["created_at"]) for r in parsed],
            [(r["name"], r["created_at"]) for r in records])

    def test_date_window_open_ended_and_bounds(self):
        from datetime import date as _date
        self._dated("Early", datetime(2026, 10, 1, 12, 0,
                                      tzinfo=dt_timezone.utc))
        self._dated("Late", datetime(2026, 10, 5, 12, 0,
                                     tzinfo=dt_timezone.utc))
        records = export_campaigns(
            self.salon, start_date=_date(2026, 10, 2))
        self.assertEqual([r["name"] for r in records],
                         ["November Offer", "November News", "Late"])
        records = export_campaigns(
            self.salon, end_date=_date(2026, 10, 2))
        self.assertEqual([r["name"] for r in records], ["Early"])
        # Start bound is start-of-day inclusive.
        records = export_campaigns(
            self.salon, start_date=_date(2026, 10, 1),
            end_date=_date(2026, 10, 1))
        self.assertEqual([r["name"] for r in records], ["Early"])

    def test_date_window_defaults_identical_and_aliases(self):
        from datetime import date as _date
        self.assertEqual(
            export_campaigns(self.salon, start_date=None, end_date=None),
            export_campaigns(self.salon))
        self.assertEqual(
            export_campaigns_csv(self.salon, start_date=None,
                                  end_date=None),
            export_campaigns_csv(self.salon))
        day = self.email.created_at.date()
        self.assertEqual(
            export_campaigns(self.salon, start=day, end=day),
            export_campaigns(self.salon, start_date=day, end_date=day))
        self.assertEqual(
            export_campaigns(self.salon, date_from=day, date_to=day),
            export_campaigns(self.salon, start_date=day, end_date=day))
        # String and datetime bounds reduce to the local date.
        self.assertEqual(
            export_campaigns(self.salon, start_date=day.isoformat(),
                             end_date=day.isoformat()),
            export_campaigns(self.salon, start_date=day, end_date=day))
        self.assertEqual(
            export_campaigns(self.salon,
                             start_date=self.email.created_at,
                             end_date=self.email.created_at),
            export_campaigns(self.salon, start_date=day, end_date=day))

    def test_date_window_composes_with_status_channel_salon(self):
        from datetime import date as _date
        self._dated("Dated SMS", datetime(2026, 10, 3, 12, 0,
                                          tzinfo=dt_timezone.utc),
                    channel="sms", status=Campaign.Status.SENT,
                    sent_at=SENT_AT)
        day = _date(2026, 10, 3)
        records = export_campaigns(
            self.salon, start_date=day, end_date=day,
            status="sent", channel="sms")
        self.assertEqual([r["name"] for r in records], ["Dated SMS"])
        self.assertEqual(export_campaigns(
            self.salon, start_date=day, end_date=day,
            status="draft", channel="sms"), [])
        self.assertEqual(export_campaigns(
            None, start_date=day, end_date=day), [])
        other = Campaign.objects.create(
            salon=self.other, name="Elsewhere Dated", channel="email",
            subject="Hi", body="Body")
        Campaign.objects.filter(pk=other.pk).update(
            created_at=datetime(2026, 10, 3, 12, 0,
                                tzinfo=dt_timezone.utc))
        records = export_campaigns(
            self.other, start_date=day, end_date=day)
        self.assertEqual([r["name"] for r in records],
                         ["Elsewhere Dated"])

    def test_date_window_reversed_is_empty(self):
        from datetime import date as _date
        self.assertEqual(export_campaigns(
            self.salon, start_date=_date(2026, 10, 5),
            end_date=_date(2026, 10, 1)), [])
        self.assertEqual(
            export_campaigns_csv(
                self.salon, start_date=_date(2026, 10, 5),
                end_date=_date(2026, 10, 1)),
            ",".join(CAMPAIGN_EXPORT_FIELDNAMES) + "\n")

    def test_no_send_count_or_aggregates(self):
        for record in export_campaigns(self.salon):
            self.assertNotIn("send_count", record)
