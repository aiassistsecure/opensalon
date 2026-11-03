"""Update one client's profile fields.

Usage:
    python manage.py update_client --salon-id ID --client-id ID
        [--first-name TEXT] [--last-name TEXT] [--email ADDRESS]
        [--phone NUMBER] [--active | --inactive] [--dry-run]

Thin wrapper around ``clients.update_client.update_client`` (the
one source of truth): resolves salon/client, delegates verbatim,
reports by id and field name only (no names/contact details;
only the boolean ``active`` value is shown). At least one field
must be given; omitted = unchanged. Opt-ins are NOT set here --
``set_client_opt_ins`` owns them. ``--dry-run`` calls only the
read-only ``validate_update_client`` twin (no writer, no
rollback relied on -- NEDB-safe). Invalid input raises
``CommandError``, nothing written. Backend only.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from clients.update_client import update_client, validate_update_client
from saloncore.models import Salon

_FIELDS = ("first_name", "last_name", "email", "phone", "active")


class Command(BaseCommand):
    help = "Update one client's profile fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon the client belongs to.")
        parser.add_argument(
            "--client-id", type=int, required=True,
            help="ID of the client to update.")
        parser.add_argument(
            "--first-name", dest="first_name", default=None,
            help="New first name; omitted = unchanged.")
        parser.add_argument(
            "--last-name", dest="last_name", default=None,
            help="New last name; omitted = unchanged.")
        parser.add_argument(
            "--email", dest="email", default=None,
            help="New email (empty string clears); omitted = unchanged.")
        parser.add_argument(
            "--phone", dest="phone", default=None,
            help="New phone (empty string clears); omitted = unchanged.")
        parser.add_argument(
            "--active", dest="active", action="store_true", default=None,
            help="Mark the client active; omitted = unchanged.")
        parser.add_argument(
            "--inactive", dest="active", action="store_false",
            default=None,
            help="Mark the client inactive; omitted = unchanged.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate, print fields that would "
                 "change, and write nothing.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        try:
            client = Client.objects.get(
                pk=options["client_id"], salon=salon)
        except Client.DoesNotExist:
            raise CommandError(
                f"No client with id {options['client_id']} "
                f"for salon {options['salon_id']}.") from None

        requested = {field: options.get(field) for field in _FIELDS}
        if all(value is None for value in requested.values()):
            raise CommandError(
                "At least one field must be given: --first-name, "
                "--last-name, --email, --phone, --active, or "
                "--inactive.")

        if options.get("dry_run"):
            try:
                cleaned = validate_update_client(
                    salon, client, **requested)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            changes = [
                field for field in _FIELDS
                if field in cleaned
                and cleaned[field] != getattr(client, field)
            ]
            if not changes:
                self.stdout.write(
                    f"update_client dry-run: client_id={client.pk} "
                    f"salon_id={salon.pk} no changes")
                return
            for field in changes:
                suffix = (f": -> {cleaned[field]}"
                          if field == "active" else "")
                self.stdout.write(
                    f"update_client dry-run: client_id={client.pk} "
                    f"salon_id={salon.pk} would set {field}{suffix}")
            return

        try:
            result = update_client(salon, client, **requested)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not result.changed:
            self.stdout.write(
                f"update_client: client_id={client.pk} "
                f"salon_id={salon.pk} no changes "
                f"active={result.active}")
            return
        for change in result.changes:
            suffix = (f": {change.old_value} -> {change.new_value}"
                      if change.field == "active" else "")
            self.stdout.write(
                f"update_client: client_id={client.pk} "
                f"salon_id={salon.pk} set {change.field}{suffix}")
