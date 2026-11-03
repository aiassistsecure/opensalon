"""Add a persistent client record note to one client.

Usage:
    python manage.py add_client_note --salon-id ID --client-id ID
        --body TEXT [--author NAME] [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), so the preview applies the
service's own cleaning/validation and prints the
note that WOULD be created (its client, body, and author).

Thin wrapper around :func:`clients.notes.add_client_note`: the
client is resolved by id scoped to the salon, and the body/
author are passed to the service verbatim -- its cleaning and
refusal of empty body text stay the single source of truth and
surface here as ``CommandError``. This command adds no note
logic of its own, so command and service can never disagree.
The note is persistent on the client profile; no appointment
note is created.

Invalid input -- an unknown salon, an unknown client, a client
outside the given salon, or a service ``ValidationError`` --
raises ``CommandError`` and nothing is written. Output names
the client and salon by id only. Backend only -- no views,
templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from clients.notes import add_client_note, validate_add_client_note
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Add a persistent client record note to one client."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon the client must belong to.")
        parser.add_argument(
            "--client-id", required=True, type=int,
            help="Id of the client to add the note to.")
        parser.add_argument(
            "--body", "--text", "--note", dest="body",
            required=True,
            help="Body (text) of the client record note.")
        parser.add_argument(
            "--author", "--author-name", dest="author", default="",
            help="Optional author name stored on the note.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate with the service's "
                 "validate-only helper, print the note that "
                 "would be created, and write nothing.")

    def handle(self, *args, **options):
        salon_id = options.get("salon_id")
        if salon_id is None:
            raise CommandError("Provide --salon-id.")
        client_id = options.get("client_id")
        if client_id is None:
            raise CommandError("Provide --client-id.")
        # ``text``/``note`` are aliases if supplied via
        # call_command kwargs.
        body = (options.get("body") or options.get("text")
                or options.get("note"))
        if body is None:
            raise CommandError("Provide --body.")
        author = (options.get("author")
                  or options.get("author_name") or "")
        try:
            salon = Salon.objects.get(pk=salon_id)
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {salon_id}.") from None
        try:
            client = Client.objects.get(pk=client_id, salon=salon)
        except Client.DoesNotExist:
            raise CommandError(
                f"No client with id {client_id} "
                f"in salon {salon.pk}.") from None
        if options.get("dry_run"):
            try:
                body_clean, author_name = validate_add_client_note(
                    salon, client, body, author=author)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would create client note for "
                f"client {client.pk} in salon {salon.pk}: "
                f"body={body_clean!r} author={author_name!r} "
                f"-- no note written.")
            return
        try:
            note = add_client_note(salon, client, body, author=author)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Added note {note.pk} to client "
            f"{client.pk} in salon {salon.pk}: {note.body!r}")
