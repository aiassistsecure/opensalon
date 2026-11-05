"""Export a salon's client search results as CSV or JSON.

Usage:
    python manage.py export_client_search --salon-id ID
        [--query TEXT] [--format json|csv] [--output PATH]

Thin wrapper around ``clients.search_export`` -- that service is
the one source of truth for the client search export shape; this
command only resolves the salon, delegates verbatim, and routes
the result to the ``--output`` file when given or to stdout
otherwise. For ``--format csv`` (the default) it writes
:func:`clients.search_export.export_search_results_csv`'s CSV
string, exactly as before; for ``--format json`` it serialises
the SAME dict rows from
:func:`clients.search_export.export_search_results` as JSON via
``DjangoJSONEncoder``, so the two formats can never disagree. It
never reimplements serialization or querying. The command name
is ``export_client_search``, not ``export_search``, because that
global name is already owned by another app's command.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from clients.search_export import (
    export_search_results,
    export_search_results_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's client search results as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose clients to search.",
        )
        parser.add_argument(
            "--query", dest="query", default=None,
            help="Search text to match (default: all clients).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
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
            if fmt == "json":
                rows = export_search_results(
                    salon, query=options.get("query")
                )
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_search_results_csv(
                    salon, query=options.get("query")
                )
        except Exception as exc:
            raise CommandError(
                f"Client search export failed: {exc}"
            ) from exc

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
