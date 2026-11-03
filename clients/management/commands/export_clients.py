"""Export all clients for a salon via the bulk export service.

Usage:
    python manage.py export_clients --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around ``clients.export_all`` -- that service is the
one source of truth for the bulk client export shape
(single-client serialization via ``clients.export`` plus
``note_count``); this command only resolves the salon, delegates
verbatim, and routes the result to the ``--output`` file when
given or to stdout otherwise. For ``--format json`` (the default)
it serializes :func:`~clients.export_all.export_all_clients`'s
list of dicts as JSON, exactly as before; for ``--format csv`` it
writes :func:`~clients.export_all.export_all_clients_csv`'s CSV
string as-is -- that service builds its rows from the same list,
so the two formats can never disagree. It never reimplements
serialization or querying.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.export_all import export_all_clients, export_all_clients_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export all clients for a salon as JSON or CSV (bulk export service)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose clients to export.",
        )
        parser.add_argument(
            "--format", dest="format", default="json", choices=_FORMATS,
            help="Export format: json (default) or csv.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "json"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        if fmt == "csv":
            text = export_all_clients_csv(salon=salon)
        else:
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
