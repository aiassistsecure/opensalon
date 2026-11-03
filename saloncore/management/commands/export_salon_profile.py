"""Export one salon's profile verbatim as CSV.

Usage:
    python manage.py export_salon_profile --salon-id ID
        [--output PATH]

Thin wrapper around :mod:`saloncore.salon_profile_export` --
that service is the one source of truth for the salon profile
export; this command only resolves the salon, delegates to
the service verbatim, and writes the CSV it returns (to
``--output`` when given, otherwise to stdout). The row carries
every stored Salon field. An unknown salon raises
``CommandError``. Backend only; read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from saloncore.salon_profile_export import export_salon_profile_csv


class Command(BaseCommand):
    help = "Export one salon's profile verbatim as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose profile to export.",
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
        csv_text = export_salon_profile_csv(salon)
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(csv_text, ending="")
