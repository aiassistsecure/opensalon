"""Export a salon's client opt-in state as CSV.

Usage:
    python manage.py export_opt_ins --salon-id ID [--output PATH]

Thin wrapper around ``clients.optin_export.export_optins_csv`` --
that service is the one source of truth for the opt-in export
shape; this command only resolves the salon, delegates verbatim,
and routes the CSV it returns to the ``--output`` file when given
or to stdout otherwise. It never reimplements serialization or
querying.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.optin_export import export_optins_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's client opt-in state as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose client opt-ins to export.",
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

        text = export_optins_csv(salon)

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
