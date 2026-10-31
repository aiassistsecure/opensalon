"""Export a salon's client search results as CSV.

Usage:
    python manage.py export_client_search --salon-id ID
        [--query TEXT] [--output PATH]

Thin wrapper around ``clients.search_export.export_search_results_csv``
-- that service is the one source of truth for the client search
export shape; this command only resolves the salon, delegates
verbatim, and routes the CSV it returns to the ``--output`` file
when given or to stdout otherwise. It never reimplements
serialization or querying. The command name is
``export_client_search``, not ``export_search``, because that
global name is already owned by another app's command.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.search_export import export_search_results_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's client search results as CSV."

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
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        try:
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
