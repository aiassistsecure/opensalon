"""Export a salon's price-book structure records as CSV.

Usage:
    python manage.py export_structure --salon-id ID
        [--section categories|levels|all] [--output PATH]

Thin wrapper around :mod:`saloncore.structure_export` -- that
service is the one source of truth for the structure export;
this command only resolves the salon, picks the requested
section, delegates to the service verbatim, and writes the CSV
it returns (to ``--output`` when given, otherwise to stdout).
``--section all`` (the default) writes the categories block,
one blank line, then the levels block, exactly as the service's
:func:`~saloncore.structure_export.export_structure_csv`
renders them. An unknown salon raises ``CommandError``.
Backend only; read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from saloncore.structure_export import (
    export_service_categories_csv,
    export_staff_levels_csv,
    export_structure_csv,
)

_RENDERERS = {
    "categories": export_service_categories_csv,
    "levels": export_staff_levels_csv,
    "all": export_structure_csv,
}


class Command(BaseCommand):
    help = "Export a salon's service categories and staff levels as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose structure records to export.",
        )
        parser.add_argument(
            "--section", choices=sorted(_RENDERERS), default="all",
            help="Which records to export: categories, levels, or "
                 "all (default).",
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
        csv_text = _RENDERERS[options["section"]](salon)
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
