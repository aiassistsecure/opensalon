import csv
import io

from django.test import TestCase

from clients.dedupe import find_duplicate_candidates
from clients.dedupe_export import (
    DEDUPE_FIELDNAMES,
    export_duplicate_candidates,
    export_duplicate_candidates_csv,
)
from clients.models import Client
from saloncore.models import Salon


def make(salon, first, last, **kw):
    return Client.objects.create(
        salon=salon, first_name=first, last_name=last, **kw
    )


class DedupeExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.amy = make(self.salon, "Amy", "Smith",
                        email="Amy@Example.com", phone="555-0101")
        self.amy2 = make(self.salon, "Amelia", "Smith",
                         email=" amy@example.com ", phone="555-9999")
        self.bob = make(self.salon, "Bob", "Adams",
                        email="bob@example.com", phone="(555) 010-2222")
        self.bob2 = make(self.salon, "Robert", "Adams",
                         email="robert@example.com",
                         phone="+1 555.010.2222")
        self.zoe = make(self.salon, "Zoe", "Lee",
                        email="zoe@example.com", phone="555-3333")
        self.other_amy = make(self.other, "Amy", "Smith",
                              email="amy@example.com", phone="555-7777")

    def _parsed(self, *args, **kw):
        return list(csv.DictReader(
            io.StringIO(export_duplicate_candidates_csv(*args, **kw))))

    def test_header_and_columns(self):
        self.assertEqual(
            DEDUPE_FIELDNAMES,
            ["key_type", "key", "client_id", "first_name", "last_name"],
        )
        rows = list(csv.reader(io.StringIO(
            export_duplicate_candidates_csv(salon=self.salon))))
        self.assertEqual(rows[0], DEDUPE_FIELDNAMES)

    def test_empty_is_header_only(self):
        empty = Salon.objects.create(name="Empty Salon")
        self.assertEqual(export_duplicate_candidates(salon=empty), [])
        self.assertEqual(
            export_duplicate_candidates_csv(salon=empty),
            ",".join(DEDUPE_FIELDNAMES) + "\n",
        )

    def test_rows_match_service_output(self):
        groups = find_duplicate_candidates(salon=self.salon)
        expected = [
            {
                "key_type": g["key_type"],
                "key": g["key"],
                "client_id": c.pk,
                "first_name": c.first_name,
                "last_name": c.last_name,
            }
            for g in groups for c in g["clients"]
        ]
        records = export_duplicate_candidates(salon=self.salon)
        self.assertEqual(records, expected)
        # Concrete expectation: email group (Amelia before Amy by
        # ordering), then phone group (Bob before Robert).
        self.assertEqual(records, [
            {"key_type": "email", "key": "amy@example.com",
             "client_id": self.amy2.pk, "first_name": "Amelia",
             "last_name": "Smith"},
            {"key_type": "email", "key": "amy@example.com",
             "client_id": self.amy.pk, "first_name": "Amy",
             "last_name": "Smith"},
            {"key_type": "phone", "key": "5550102222",
             "client_id": self.bob.pk, "first_name": "Bob",
             "last_name": "Adams"},
            {"key_type": "phone", "key": "5550102222",
             "client_id": self.bob2.pk, "first_name": "Robert",
             "last_name": "Adams"},
        ])
        parsed = self._parsed(salon=self.salon)
        self.assertEqual(parsed, [
            {k: str(v) for k, v in r.items()} for r in records
        ])
        # Unique client never appears.
        self.assertNotIn(self.zoe.pk, [r["client_id"] for r in records])

    def test_salon_isolation(self):
        records = export_duplicate_candidates(salon=self.salon)
        self.assertNotIn(
            self.other_amy.pk, [r["client_id"] for r in records])
        self.assertEqual(export_duplicate_candidates(salon=self.other), [])
        self.assertEqual(
            export_duplicate_candidates_csv(salon=self.other),
            ",".join(DEDUPE_FIELDNAMES) + "\n",
        )
        # Unscoped, the shared email group includes the other salon.
        unscoped = export_duplicate_candidates()
        self.assertIn(
            self.other_amy.pk, [r["client_id"] for r in unscoped])

    def test_read_only_never_merges_or_deletes(self):
        before = Client.objects.count()
        export_duplicate_candidates(salon=self.salon)
        export_duplicate_candidates_csv(salon=self.salon)
        self.assertEqual(Client.objects.count(), before)
        self.assertTrue(Client.objects.filter(pk=self.amy.pk).exists())
        self.assertTrue(Client.objects.filter(pk=self.amy2.pk).exists())
