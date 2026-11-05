"""Export a salon's unpriced services as CSV or JSON.

Usage:
    python manage.py export_unpriced --salon-id ID
        [--staff-level-id ID] [--format json|csv] [--output PATH]

Thin wrapper around :mod:`saloncore.unpriced_export` -- that
service is the one source of truth for the unpriced export;
this command only resolves the salon (and, when given, the
staff level), delegates to it verbatim, and writes what it
returns (to ``--output`` when given, otherwise to stdout).
For ``--format csv`` (the default) it writes
:func:`saloncore.unpriced_export.export_unpriced_services_csv`'s
CSV string, exactly as before; for ``--format json`` it
serialises the SAME dict rows from
:func:`saloncore.unpriced_export.export_unpriced_services`
as JSON. Without ``--staff-level-id`` the service exports the
fully-unpriced list; with one, every active service missing a
price for that level. Backend only; read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, StaffLevel
from saloncore.unpriced_export import (
    export_unpriced_services,
    export_unpriced_services_csv,
)

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's unpriced services as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose unpriced services to export.",
        )
        parser.add_argument(
            "--staff-level-id", type=int, default=None,
            help="Id of the staff level to scope to (default: "
                 "fully-unpriced services only).",
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
        staff_level = None
        if options["staff_level_id"] is not None:
            try:
                staff_level = StaffLevel.objects.get(
                    pk=options["staff_level_id"])
            except StaffLevel.DoesNotExist:
                raise CommandError(
                    f"No staff level with id "
                    f"{options['staff_level_id']}."
                ) from None
        try:
            if fmt == "json":
                rows = export_unpriced_services(
                    salon, staff_level=staff_level)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_unpriced_services_csv(
                    salon, staff_level=staff_level)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
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
