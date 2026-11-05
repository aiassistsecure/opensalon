"""Export one salon's roster patterns as CSV or JSON.

Usage:
    python manage.py export_roster --salon-id ID [--output PATH]
        [--include-inactive] [--format json|csv]

Thin wrapper around the existing :mod:`team.roster_export`
service: this command delegates verbatim to
``export_roster_patterns_csv(salon, include_inactive=...)``
for ``--format csv`` (the default) and serialises the SAME
dict rows from ``export_roster_patterns`` for
``--format json``, so the two formats can never disagree --
one source of truth.

The service takes no date arguments (roster patterns are
recurring weekly patterns, not dated records), so this command
takes none either. By default only active patterns are
exported, exactly as the service defaults. Pass
``--include-inactive`` for a complete exit export including
inactive patterns; it is passed through to the service
verbatim and composes with both formats.

Output goes to stdout unless ``--output`` names a file.
Backend only -- no views, templates, or UI. Read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.roster_export import (
    export_roster_patterns,
    export_roster_patterns_csv,
)

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export one salon's roster patterns as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose roster patterns to export.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")
        parser.add_argument(
            "--include-inactive", action="store_true",
            help="Include inactive roster patterns (default: "
                 "active patterns only).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")

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

        include_inactive = bool(options.get("include_inactive", False))
        if fmt == "json":
            rows = export_roster_patterns(
                salon, include_inactive=include_inactive)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_roster_patterns_csv(
                salon, include_inactive=include_inactive)

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
