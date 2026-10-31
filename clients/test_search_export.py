import csv
import io
import json
from unittest import mock

from django.test import TestCase

from clients.models import Client
from clients.search import search_clients
from clients.search_export import (
    SEARCH_FIELDNAMES,
    export_search_results,
    export_search_results_csv,
)
from saloncore.models import Salon


class ClientSearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.amy = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            email="amy.smith@example.com", phone="555-0101")
        self.zoe = Client.objects.create(
            salon=self.salon, first_name="Zoe", last_name="Smith",
            email="zoe@example.net", phone="555-0102")
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams",
            email="bob@sample.org", phone="555-0199")
        self.other = Client.objects.create(
            salon=self.other_salon, first_name="Amy", last_name="Smith",
            email="amy.smith@example.com", phone="555-0101")

    def _parsed(self, *args, **kw):
        text = export_search_results_csv(*args, **kw)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_only_when_no_match(self):
        self.assertEqual(
            export_search_results(self.salon, "no-such-text"), [])
        self.assertEqual(
            export_search_results_csv(self.salon, "no-such-text"),
            ",".join(SEARCH_FIELDNAMES) + "\n")

    def test_fieldnames(self):
        self.assertEqual(
            SEARCH_FIELDNAMES,
            ["client_id", "first_name", "last_name", "email", "phone"])

    def test_rows_match_search_service(self):
        for query in ("smith", "EXAMPLE.COM", "555-010", ""):
            expected = [
                {"client_id": c.pk, "first_name": c.first_name,
                 "last_name": c.last_name, "email": c.email,
                 "phone": c.phone}
                for c in search_clients(self.salon, query)
            ]
            self.assertEqual(
                export_search_results(self.salon, query), expected)

    def test_concrete_ordering_and_csv_agree(self):
        records = export_search_results(self.salon, "smith")
        self.assertEqual(records, [
            {"client_id": self.amy.pk, "first_name": "Amy",
             "last_name": "Smith", "email": "amy.smith@example.com",
             "phone": "555-0101"},
            {"client_id": self.zoe.pk, "first_name": "Zoe",
             "last_name": "Smith", "email": "zoe@example.net",
             "phone": "555-0102"},
        ])
        self.assertEqual(self._parsed(self.salon, "smith"), [
            {k: str(v) for k, v in r.items()} for r in records])

    def test_empty_query_returns_all_salon_clients_ordered(self):
        self.assertEqual(
            [r["client_id"] for r in export_search_results(self.salon, "")],
            [self.bob.pk, self.amy.pk, self.zoe.pk])
        self.assertEqual(
            [r["client_id"]
             for r in export_search_results(self.salon, None)],
            [self.bob.pk, self.amy.pk, self.zoe.pk])

    def test_delegates_to_search_service(self):
        with mock.patch(
            "clients.search_export.search_clients",
            wraps=search_clients,
        ) as spy:
            export_search_results(self.salon, "amy")
        spy.assert_called_once_with(self.salon, "amy")

    def test_salon_scoping(self):
        records = export_search_results(self.salon, "amy")
        self.assertEqual([r["client_id"] for r in records], [self.amy.pk])
        self.assertNotIn(
            str(self.other.pk),
            export_search_results_csv(self.salon, "555-0101"))
        other = export_search_results(self.other_salon, "amy")
        self.assertEqual([r["client_id"] for r in other], [self.other.pk])

    def test_json_serializable(self):
        records = export_search_results(self.salon, "")
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_read_only(self):
        before = Client.objects.count()
        export_search_results(self.salon, "smith")
        export_search_results_csv(self.salon, "smith")
        self.assertEqual(Client.objects.count(), before)
