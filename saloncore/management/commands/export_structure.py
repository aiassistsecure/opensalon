"""Export a salon's price-book structure records as CSV or JSON.

Usage:
    python manage.py export_structure --salon-id ID
        [--section categories|levels|all] [--format json|csv]
        [--output PATH]

Thin wrapper around :mod:`saloncore.structure_export` -- that
service is the one source of truth for the structure export;
this command only resolves the salon, picks the requested
section, delegates to the service verbatim, and writes the
export it returns (to ``--output`` when given, otherwise to
stdout). For ``--format csv`` (the default) it writes the
service's CSV strings exactly as before: ``--section all``
writes the categories block, one blank line, then the levels
block, exactly as the service's
:func:`~saloncore.structure_export.export_structure_csv`
renders them. For ``--format json`` it serialises the SAME
dict rows from the service's dict-row exports as JSON via
``DjangoJSONEncoder``: a section export is the dict list
mirroring that section's CSV rows, and ``--section all`` is
an object ``{"categories": [...], "levels": [...]}`` built
from those same dict rows, so the two formats can never
disagree. An unknown salon raises ``CommandError``.
Backend only; read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from saloncore.structure_export import (
    export_service_categories,
    export_service_categories_csv,
    export_staff_levels,
    export_staff_levels_csv,
    export_structure_csv,
)

_RENDERERS = {
    "categories": export_service_categories_csv,
    "levels": export_staff_levels_csv,
    "all": export_structure_csv,
}

_FORMATS = ("json", "csv")


def _json_payload(salon, section):
    if section == "categories":
        return export_service_categories(salon)
    if section == "levels":
        return export_staff_levels(salon)
    return {
        "categories": export_service_categories(salon),
        "levels": export_staff_levels(salon),
    }


class Command(BaseCommand):
    help = "Export a salon's service categories and staff levels as CSV (default) or JSON."

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
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the file to write (default: stdout).",
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
        section = options["section"]
        if fmt == "json":
            text = json.dumps(
                _json_payload(salon, section),
                indent=2, cls=DjangoJSONEncoder) + "\n"
        else:
            text = _RENDERERS[section](salon)
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
