import csv
import io
import json
from unittest import mock

from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.search import search_staff
from team.search_export import (
    STAFF_SEARCH_FIELDNAMES,
    export_staff_search_results,
    export_staff_search_results_csv,
)


class StaffSearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.l6 = StaffLevel.objects.create(salon=self.salon, name="Level 6")

    def make(self, name, level=None, salon=None, **kw):
        return StaffMember.objects.create(
            salon=salon or self.salon, display_name=name,
            staff_level=level, **kw)

    def test_fieldnames(self):
        self.assertEqual(STAFF_SEARCH_FIELDNAMES, [
            "id", "staff_id", "salon_id", "external_id", "display_name",
            "staff_level_id", "staff_level_name", "active",
            "online_bookable"])

    def test_header_only_when_no_match(self):
        self.make("Amy Smith", self.l6)
        self.assertEqual(export_staff_search_results(self.salon, "zzz"), [])
        self.assertEqual(
            export_staff_search_results_csv(self.salon, "zzz"),
            ",".join(STAFF_SEARCH_FIELDNAMES) + "\n")

    def test_rows_match_search_service(self):
        amy = self.make("Amy Smith", self.l6, external_id="stf-1")
        bob = self.make("Bob Level 6 Fan")
        for query in ("level 6", "AMY", ""):
            expected = [m.pk for m in search_staff(self.salon, query)]
            records = export_staff_search_results(self.salon, query)
            self.assertEqual([r["id"] for r in records], expected)
        records = export_staff_search_results(self.salon, "amy")
        self.assertEqual(records, [{
            "id": amy.pk, "staff_id": amy.pk, "salon_id": self.salon.pk,
            "external_id": "stf-1", "display_name": "Amy Smith",
            "staff_level_id": self.l6.pk, "staff_level_name": "Level 6",
            "active": True, "online_bookable": True}])
        self.assertEqual(bob.staff_level_id, None)
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_search_results_csv(self.salon, "amy"))))
        self.assertEqual(parsed, [
            {k: str(v) for k, v in records[0].items()}])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_no_level_exports_blank_level_fields(self):
        self.make("Solo Person")
        record = export_staff_search_results(self.salon, "solo")[0]
        self.assertEqual(record["staff_level_id"], None)
        self.assertEqual(record["staff_level_name"], "")

    def test_delegates_to_search_service(self):
        with mock.patch(
            "team.search_export.search_staff", wraps=search_staff
        ) as spy:
            export_staff_search_results(self.salon, "amy", active=True)
        spy.assert_called_once_with(
            self.salon, "amy", active=True, online_bookable=None)

    def test_no_pin_or_email_in_export(self):
        self.make("Amy Smith", self.l6, pin="1234",
                  email="amy@example.com")
        record = export_staff_search_results(self.salon, "amy")[0]
        self.assertNotIn("pin", record)
        self.assertNotIn("email", record)
        text = export_staff_search_results_csv(self.salon, "amy")
        self.assertNotIn("amy@example.com", text)

    def test_salon_isolation_and_flag_passthrough(self):
        mine = self.make("Amy Smith", self.l6, online_bookable=False)
        self.make("Amy Other", salon=self.other)
        self.make("Amy Active", self.l6)
        records = export_staff_search_results(
            self.salon, "amy", online_bookable=False)
        self.assertEqual([r["id"] for r in records], [mine.pk])

    def test_read_only(self):
        self.make("Amy Smith", self.l6)
        before = StaffMember.objects.count()
        export_staff_search_results(self.salon, "amy")
        export_staff_search_results_csv(self.salon, "amy")
        self.assertEqual(StaffMember.objects.count(), before)
