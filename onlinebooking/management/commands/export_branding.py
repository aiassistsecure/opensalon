"""Export one salon's derived online-booking branding payload as CSV.

Usage:
    python manage.py export_branding --salon-id ID
        [--output PATH]

Thin wrapper around :mod:`onlinebooking.branding_export` --
that service is the one source of truth for the branding
export; this command only resolves the salon, delegates to
the service verbatim, and writes the CSV it returns (to
``--output`` when given, otherwise to stdout). The row carries
the DERIVED payload a booking page renders from -- fallback
values, ``is_branded`` and ``fallbacks_applied`` -- not the
stored Salon fields (``export_salon_profile`` owns those).
An unknown salon raises ``CommandError``. Backend only;
read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from onlinebooking.branding_export import export_branding_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export one salon's derived online-booking branding payload as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose branding payload to export.",
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
        csv_text = export_branding_csv(salon)
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
