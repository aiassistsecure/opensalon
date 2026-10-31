"""Export all clients for a salon via the bulk export service.

Usage:
    python manage.py export_clients --salon-id ID [--output PATH]

Thin wrapper around ``clients.export_all.export_all_clients`` --
that service is the one source of truth for the bulk client export
shape (single-client serialization via ``clients.export`` plus
``note_count``); this command only resolves the salon, delegates
verbatim, serializes the result as JSON, and routes it to the
``--output`` file when given or to stdout otherwise. It never
reimplements serialization or querying.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.export_all import export_all_clients
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export all clients for a salon as JSON (bulk export service)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose clients to export.",
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

        records = export_all_clients(salon=salon)
        text = json.dumps(records, indent=2) + "\n"

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
