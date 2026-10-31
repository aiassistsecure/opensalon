"""Export a salon's inactive clients as CSV.

Usage:
    python manage.py export_inactive --salon-id ID [--output PATH]

Thin wrapper around ``clients.inactive_export.export_inactive_csv`` --
that service is the one source of truth for the inactive export
shape; this command only resolves the salon, delegates verbatim,
and routes the CSV it returns to the ``--output`` file when given
or to stdout otherwise. It never reimplements serialization or
querying.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.inactive_export import export_inactive_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's inactive clients as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose inactive clients to export.",
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

        text = export_inactive_csv(salon)

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
