"""Store-first creates: a booking is a store play first.

The founder's law, on the last write that still waited on
the node: the day book's booking modal used to POST and hold
the block until the reply — on the pilot's NEDB that wait was
the ten seconds, whatever coat it wore. Now the block is
born in the embedded store under a temporary ref and the
create drains through the apply endpoint, whose answer names
the real id and carries the true pack entry for the rename.

These tests pin the node's half: the create kind under the
same creation core as the book endpoint, the per-op answer
(id + entry identical to the pack's own), and the replay
guard — a re-sent birth (its ack died with the tab) is
answered with the original, never a twin."""

import datetime
import json
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

STATIC = Path(__file__).parent / "static" / "webui"


class StoreCreateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        cat = ServiceCategory.objects.create(salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=cat, name="Full Highlight and Haircut",
            service_minutes=150,
        )
        self.guest = Client.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta",
            phone="407-555-0100",
        )
        self.url = reverse("webui:daybook_apply")

    def apply(self, ops):
        resp = self.client.post(
            self.url,
            data=json.dumps({"ops": ops}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["results"]

    def create_op(self, **kw):
        op = {
            "kind": "create",
            "ref": "tmp_1_abc",
            "staff_member_id": self.member.pk,
            "service_id": self.service.pk,
            "date": "2026-11-07",
            "time": "10:00",
            "client_id": self.guest.pk,
        }
        op.update(kw)
        return op

    def test_a_create_op_books_and_names_the_birth(self):
        (result,) = self.apply([self.create_op()])
        self.assertTrue(result["ok"])
        appt = Appointment.objects.get()
        self.assertEqual(result["id"], appt.pk)
        self.assertEqual(appt.client, self.guest)
        self.assertEqual(appt.staff_member, self.member)
        from webui.views import _tz

        start = appt.start.astimezone(_tz(self.salon))
        self.assertEqual((start.hour, start.minute), (10, 0))
        # The entry is the pack's own word for this appointment.
        entry = result["entry"]
        self.assertEqual(entry["id"], appt.pk)
        self.assertEqual(entry["client"], "Jaime Orta")
        self.assertEqual(entry["service"], "Full Highlight and Haircut")
        self.assertEqual(entry["start_min"], 600)
        self.assertEqual(entry["end_min"], 750)

    def test_a_resent_birth_is_answered_with_the_original(self):
        (first,) = self.apply([self.create_op()])
        (second,) = self.apply([self.create_op()])
        self.assertTrue(second["ok"])
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_a_resent_new_client_birth_makes_no_twin(self):
        op = self.create_op(client_id=None)
        del op["client_id"]
        op["new_client"] = {
            "first_name": "New", "last_name": "Guest",
            "phone": "407-555-0199",
        }
        (first,) = self.apply([op])
        (second,) = self.apply([dict(op)])
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(
            Client.objects.filter(first_name="New").count(), 1
        )

    def test_a_bad_create_never_poisons_its_batch(self):
        results = self.apply([
            self.create_op(service_id=999999),
            self.create_op(ref="tmp_2_def", time="11:00"),
        ])
        self.assertEqual([r["ok"] for r in results], [False, True])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_the_direct_door_still_books(self):
        resp = self.client.post(
            reverse("webui:daybook_book"),
            data=json.dumps({
                "staff_member_id": self.member.pk,
                "service_id": self.service.pk,
                "date": "2026-11-07",
                "time": "09:00",
                "client_id": self.guest.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(Appointment.objects.count(), 1)


class StoreCreateSourceTests(TestCase):
    def test_the_store_births_and_renames(self):
        src = (STATIC / "shadow.js").read_text()
        for pin in [
            'document.addEventListener("os:create"',
            "function createLocal(detail)",
            # plays chained onto an unacked birth hold for its name
            "if (renames[rec.id] == null) break;",
            'emit("os:rename"',
            # adoption never vanishes an unacked birth
            'if (id.indexOf("tmp_") === 0)',
        ]:
            self.assertIn(pin, src)

    def test_the_book_creates_through_the_store(self):
        src = (STATIC / "webui.js").read_text()
        for pin in [
            'new CustomEvent("os:create"',
            "if (createEv.detail.handled) { hide(); return; }",
            'document.addEventListener("os:rename"',
        ]:
            self.assertIn(pin, src)
