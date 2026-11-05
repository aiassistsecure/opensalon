"""Export a salon's client opt-in state as CSV or JSON.

Usage:
    python manage.py export_opt_ins --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around ``clients.optin_export`` -- that service
is the one source of truth for the opt-in export shape; this
command only resolves the salon, delegates verbatim, and routes
what it returns to the ``--output`` file when given or to stdout
otherwise. It never reimplements serialization or querying.

For ``--format csv`` (the default) it writes
:func:`clients.optin_export.export_optins_csv`'s CSV string,
exactly as before (byte-identical); for ``--format json`` it
serialises the SAME dict rows from
:func:`clients.optin_export.export_optins` as JSON.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.optin_export import export_optins, export_optins_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's client opt-in state as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose client opt-ins to export.",
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
                rows = export_optins(salon)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_optins_csv(salon)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Client opt-in export failed: {exc}"
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
