"""Export one client in full as JSON.

Usage:
    python manage.py export_client --salon-id ID --client-id ID
        [--output PATH]

Thin wrapper around ``clients.export.export_client`` -- that
service is the one source of truth for the single-client export
shape; this command only resolves the salon, resolves the client
by id within that salon, delegates verbatim, serializes the dict
the service returns as JSON, and routes it to the ``--output``
file when given or to stdout otherwise. It never reimplements
serialization or querying.

The name ``export_client`` is used because no other app defines
a management command with that name (checked across all apps);
it matches the service it wraps exactly.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.export import export_client
from clients.models import Client
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export one client in full as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon the client belongs to.",
        )
        parser.add_argument(
            "--client-id", type=int, required=True,
            help="ID of the client to export.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the JSON file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        try:
            client = Client.objects.get(
                pk=options["client_id"], salon=salon
            )
        except Client.DoesNotExist:
            raise CommandError(
                f"No client with id {options['client_id']} "
                f"for salon {options['salon_id']}."
            ) from None

        try:
            result = export_client(client)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        text = json.dumps(result, indent=2) + "\n"

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
