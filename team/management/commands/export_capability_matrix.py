"""Export one salon's staff capability matrix as CSV or JSON.

Usage:
    python manage.py export_capability_matrix --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`team.capability_export` services: for ``--format csv``
(the default) it delegates verbatim to
:func:`team.capability_export.export_capability_matrix_csv`
-- the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. For ``--format json`` it
serialises the SAME dict rows from
:func:`team.capability_export.export_capability_matrix`
with the same argument, so the two formats can never
disagree -- one source of truth. This command adds no
export logic of its own.

Every filter composes with both formats. An unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs).

An unknown salon raises ``CommandError``. Backend only -- no
views, templates, or UI. Read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.capability_export import (
    export_capability_matrix,
    export_capability_matrix_csv,
)

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export one salon's staff capability matrix as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose capability matrix to export.")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        if fmt == "json":
            rows = export_capability_matrix(salon)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_capability_matrix_csv(salon)

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: "
                    f"{exc}") from exc
        else:
            self.stdout.write(text, ending="")
