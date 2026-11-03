import csv
import io
import json

from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory
from saloncore.search import search_services
from saloncore.search_export import (
    EXPORT_FIELDNAMES,
    export_search_services,
    export_search_services_csv,
    search_export_row,
)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.hair = ServiceCategory.objects.create(
            salon=self.salon, name="Hair", sort_order=1)
        self.color = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=2)
        self.other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair", sort_order=1)

    def make_service(self, name, category=None, active=True, **kw):
        return Service.objects.create(
            category=category or self.hair, name=name,
            service_minutes=kw.pop("service_minutes", 45),
            processing_minutes=kw.pop("processing_minutes", 10),
            finishing_minutes=kw.pop("finishing_minutes", 5),
            active=active, **kw)

    def test_header_and_row_values(self):
        svc = self.make_service(
            "Balayage", category=self.color, description="Full",
            external_id="EXT-1")
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["id", "service_id", "salon_id", "category_id",
             "category_name", "name", "description", "external_id",
             "service_minutes", "processing_minutes",
             "finishing_minutes", "total_minutes", "active"])
        rows = export_search_services(self.salon, "balayage")
        self.assertEqual(rows, [{
            "id": svc.pk, "service_id": svc.pk,
            "salon_id": self.salon.pk,
            "category_id": self.color.pk, "category_name": "Color",
            "name": "Balayage", "description": "Full",
            "external_id": "EXT-1", "service_minutes": 45,
            "processing_minutes": 10, "finishing_minutes": 5,
            "total_minutes": 60, "active": True,
        }])
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        self.assertEqual(json.loads(json.dumps(rows)), rows)
        text = export_search_services_csv(self.salon, "balayage")
        self.assertEqual(
            text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        csv_rows = _rows(text)
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]["name"], "Balayage")
        self.assertEqual(csv_rows[0]["category_name"], "Color")
        self.assertTrue(text.endswith("\n"))

    def test_rows_match_service(self):
        self.make_service("A Deluxe Cut")
        self.make_service("B Deluxe Cut")
        self.make_service("Plain Trim")
        for query in ("Deluxe", "Hair", "Color"):
            expected = list(search_services(self.salon, query))
            rows = export_search_services(self.salon, query)
            self.assertEqual(
                [r["service_id"] for r in rows],
                [s.pk for s in expected])
            self.assertEqual(
                rows, [search_export_row(s) for s in expected])

    def test_salon_isolation(self):
        foreign = self.make_service(
            "Haircut", category=self.other_cat)
        own = self.make_service("Haircut Deluxe")
        rows = export_search_services(self.salon, "Haircut")
        self.assertNotIn(foreign.pk, [r["service_id"] for r in rows])
        self.assertEqual([r["service_id"] for r in rows], [own.pk])
        self.assertEqual(
            [r["service_id"] for r in
             export_search_services(self.other, "Haircut")],
            [foreign.pk])

    def test_no_match_and_blank_query(self):
        self.make_service("Haircut")
        self.assertEqual(export_search_services(self.salon, "nope"), [])
        self.assertEqual(export_search_services(self.salon, ""), [])
        self.assertEqual(export_search_services(self.salon, None), [])
        text = export_search_services_csv(self.salon, "nope")
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(_rows(text), [])

    def test_ordering_and_inactive_passthrough(self):
        b = self.make_service("B Deluxe Cut")
        a = self.make_service("A Deluxe Cut")
        retired = self.make_service("Aardvark Deluxe", active=False)
        rows = export_search_services(self.salon, "Deluxe")
        self.assertEqual(
            [r["service_id"] for r in rows], [a.pk, b.pk])
        rows = export_search_services(
            self.salon, "Deluxe", include_inactive=True)
        self.assertEqual(
            [r["service_id"] for r in rows],
            [a.pk, retired.pk, b.pk])
        self.assertFalse(rows[1]["active"])

    def test_read_only(self):
        self.make_service("Haircut")
        export_search_services(self.salon, "Haircut")
        export_search_services_csv(self.salon, "Haircut")
        self.assertEqual(Service.objects.count(), 1)
