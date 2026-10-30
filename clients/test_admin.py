from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clients.admin import ClientAdmin, ClientNoteAdmin
from clients.models import Client, ClientNote
from saloncore.models import Salon


class ClientAdminRegistrationTests(TestCase):
    def test_client_and_note_registered(self):
        self.assertIn(Client, admin.site._registry)
        self.assertIn(ClientNote, admin.site._registry)
        self.assertIsInstance(admin.site._registry[Client], ClientAdmin)
        self.assertIsInstance(admin.site._registry[ClientNote], ClientNoteAdmin)

    def test_client_search_fields_cover_name_email_phone(self):
        model_admin = admin.site._registry[Client]
        for field in ("first_name", "last_name", "email", "phone"):
            self.assertIn(field, model_admin.search_fields)

    def test_client_list_filter_covers_opt_ins(self):
        model_admin = admin.site._registry[Client]
        self.assertIn("sms_opt_in", model_admin.list_filter)
        self.assertIn("email_opt_in", model_admin.list_filter)

    def test_note_admin_shows_author_body_created(self):
        model_admin = admin.site._registry[ClientNote]
        for field in ("author_name", "body", "created_at"):
            self.assertIn(field, model_admin.list_display)
        self.assertIn("created_at", model_admin.readonly_fields)


class ClientAdminChangelistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="pw"
        )
        salon = Salon.objects.create(name="Fake Salon")
        cls.alice = Client.objects.create(
            salon=salon,
            first_name="Alice",
            last_name="Fakeworth",
            email="alice.fake@example.com",
            phone="555-0111",
            sms_opt_in=True,
        )
        cls.bob = Client.objects.create(
            salon=salon,
            first_name="Bob",
            last_name="Pretend",
            email="bob.pretend@example.com",
            phone="555-0222",
            email_opt_in=True,
        )
        ClientNote.objects.create(
            client=cls.alice, body="Fake note body.", author_name="Fake Author"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _changelist_names(self, params=""):
        url = reverse("admin:clients_client_changelist") + params
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return list(response.context["cl"].result_list)

    def test_changelist_lists_all_clients(self):
        self.assertEqual(set(self._changelist_names()), {self.alice, self.bob})

    def test_search_by_last_name(self):
        self.assertEqual(self._changelist_names("?q=Fakeworth"), [self.alice])

    def test_search_by_email(self):
        self.assertEqual(
            self._changelist_names("?q=bob.pretend@example.com"), [self.bob]
        )

    def test_search_by_phone(self):
        self.assertEqual(self._changelist_names("?q=555-0111"), [self.alice])

    def test_sms_opt_in_filter(self):
        self.assertEqual(
            self._changelist_names("?sms_opt_in__exact=1"), [self.alice]
        )
        self.assertEqual(self._changelist_names("?sms_opt_in__exact=0"), [self.bob])

    def test_email_opt_in_filter(self):
        self.assertEqual(
            self._changelist_names("?email_opt_in__exact=1"), [self.bob]
        )
        self.assertEqual(
            self._changelist_names("?email_opt_in__exact=0"), [self.alice]
        )

    def test_note_changelist_viewable_and_searchable(self):
        url = reverse("admin:clients_clientnote_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get(url + "?q=Fake+note")
        self.assertEqual(response.status_code, 200)
        results = list(response.context["cl"].result_list)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].author_name, "Fake Author")

    def test_client_change_page_shows_notes_inline(self):
        url = reverse("admin:clients_client_change", args=[self.alice.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fake note body.")
