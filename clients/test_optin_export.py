import csv
import io
import json

from django.test import TestCase

from clients.models import Client
from clients.optin_export import (
    OPTIN_FIELDNAMES,
    export_optin_summary,
    export_optins,
    export_optins_csv,
    summarize_optins,
)
from saloncore.models import Salon


class OptInExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def make(self, first, last, salon=None, **kw):
        return Client.objects.create(
            salon=salon or self.salon, first_name=first, last_name=last, **kw
        )

    def seed_book(self):
        both = self.make(
            "Amy", "Smith", email="amy@example.com", phone="555-0101",
            sms_opt_in=True, email_opt_in=True,
        )
        sms_only = self.make("Bob", "Adams", sms_opt_in=True)
        email_only = self.make("Cid", "Jones", email_opt_in=True)
        neither = self.make("Dee", "Brown")
        return both, sms_only, email_only, neither

    def test_fieldnames_and_header(self):
        self.assertEqual(
            OPTIN_FIELDNAMES,
            ["id", "salon_id", "first_name", "last_name", "email",
             "phone", "sms_opt_in", "email_opt_in", "active"],
        )
        rows = list(csv.reader(io.StringIO(export_optins_csv(self.salon))))
        self.assertEqual(rows, [OPTIN_FIELDNAMES])

    def test_rows_exact_and_ordered(self):
        both, sms_only, email_only, neither = self.seed_book()
        records = export_optins(self.salon)
        # Ordered by last_name, first_name, id: Adams, Brown, Jones, Smith.
        self.assertEqual(
            [r["id"] for r in records],
            [sms_only.pk, neither.pk, email_only.pk, both.pk],
        )
        self.assertEqual(records[-1], {
            "id": both.pk, "salon_id": self.salon.pk,
            "first_name": "Amy", "last_name": "Smith",
            "email": "amy@example.com", "phone": "555-0101",
            "sms_opt_in": True, "email_opt_in": True, "active": True,
        })
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_csv_matches_list_export(self):
        self.seed_book()
        parsed = list(csv.DictReader(
            io.StringIO(export_optins_csv(self.salon))))
        records = export_optins(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["id"]), record["id"])
            self.assertEqual(row["first_name"], record["first_name"])
            self.assertEqual(row["sms_opt_in"], str(record["sms_opt_in"]))
            self.assertEqual(
                row["email_opt_in"], str(record["email_opt_in"]))

    def test_salon_scoping(self):
        self.make("Amy", "Smith", sms_opt_in=True)
        self.make("Bob", "Adams", salon=self.other,
                  sms_opt_in=True, email_opt_in=True)
        records = export_optins(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["salon_id"], self.salon.pk)
        self.assertEqual(export_optin_summary(self.other)["total"], 1)

    def test_empty_book(self):
        self.assertEqual(export_optins(self.salon), [])
        self.assertEqual(
            export_optins_csv(self.salon),
            ",".join(OPTIN_FIELDNAMES) + "\n",
        )
        self.assertEqual(export_optin_summary(self.salon), {
            "total": 0, "sms_opt_in": 0, "email_opt_in": 0,
            "both_opt_in": 0, "sms_only": 0, "email_only": 0,
            "neither_opt_in": 0,
        })

    def test_summary_consistent_with_rows(self):
        self.seed_book()
        self.make("Eve", "Smith", sms_opt_in=True, email_opt_in=True)
        summary = export_optin_summary(self.salon)
        self.assertEqual(summary, {
            "total": 5, "sms_opt_in": 3, "email_opt_in": 3,
            "both_opt_in": 2, "sms_only": 1, "email_only": 1,
            "neither_opt_in": 1,
        })
        # Derived from the rows themselves, not a second query path.
        self.assertEqual(summary, summarize_optins(export_optins(self.salon)))
        self.assertEqual(
            summary["both_opt_in"] + summary["sms_only"]
            + summary["email_only"] + summary["neither_opt_in"],
            summary["total"],
        )

    def test_summarize_optins_pure(self):
        rows = [
            {"sms_opt_in": True, "email_opt_in": False},
            {"sms_opt_in": False, "email_opt_in": False},
        ]
        self.assertEqual(summarize_optins(rows), {
            "total": 2, "sms_opt_in": 1, "email_opt_in": 0,
            "both_opt_in": 0, "sms_only": 1, "email_only": 0,
            "neither_opt_in": 1,
        })
        self.assertEqual(summarize_optins([])["total"], 0)

    def test_inactive_client_included_with_active_false(self):
        self.make("Amy", "Smith", active=False, email_opt_in=True)
        records = export_optins(self.salon)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["active"])
        self.assertTrue(records[0]["email_opt_in"])

    def test_read_only(self):
        self.seed_book()
        before = Client.objects.count()
        export_optins(self.salon)
        export_optins_csv(self.salon)
        export_optin_summary(self.salon)
        self.assertEqual(Client.objects.count(), before)
