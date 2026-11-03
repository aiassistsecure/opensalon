"""Export one client in full as JSON or CSV.

Usage:
    python manage.py export_client --salon-id ID --client-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around ``clients.export`` -- that service is the
one source of truth for the single-client export shape; this
command only resolves the salon, resolves the client by id
within that salon, delegates verbatim, and routes the result to
the ``--output`` file when given or to stdout otherwise. For
``--format json`` (the default) it serializes
:func:`~clients.export.export_client`'s dict as JSON, exactly as
before; for ``--format csv`` it writes
:func:`~clients.export.export_client_csv`'s CSV string as-is --
that service builds its single row from the same dict, so the
two formats can never disagree. It never reimplements
serialization or querying.

The name ``export_client`` is used because no other app defines
a management command with that name (checked across all apps);
it matches the service it wraps exactly.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.export import export_client, export_client_csv
from clients.models import Client
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export one client in full as JSON or CSV."

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
            if fmt == "csv":
                text = export_client_csv(client)
            else:
                result = export_client(client)
                text = json.dumps(result, indent=2) + "\n"
        except Exception as exc:
            raise CommandError(str(exc)) from exc

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
