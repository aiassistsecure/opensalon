"""Export one salon's profile verbatim as CSV or JSON.

Usage:
    python manage.py export_salon_profile --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`saloncore.salon_profile_export` --
that service is the one source of truth for the salon profile
export; this command only resolves the salon, delegates to
the service verbatim, and writes its output (to ``--output``
when given, otherwise to stdout). For ``--format csv`` (the
default) it writes
:func:`saloncore.salon_profile_export.export_salon_profile_csv`'s
CSV string as-is, so the historical CSV output is
byte-identical; for ``--format json`` it serialises the same
single dict from
:func:`saloncore.salon_profile_export.export_salon_profile`
-- the same dict the CSV is built from -- verbatim as JSON
via ``DjangoJSONEncoder`` (indent=2 + trailing newline), so
the two formats can never disagree. The row carries every
stored Salon field. An unknown salon or unknown format
raises ``CommandError``. Backend only; read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from saloncore.salon_profile_export import (
    export_salon_profile,
    export_salon_profile_csv,
)

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export one salon's profile verbatim as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose profile to export.",
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
                f"Invalid format {fmt!r}; expected 'json' or 'csv'."
            )
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        if fmt == "json":
            text = json.dumps(
                export_salon_profile(salon),
                indent=2, cls=DjangoJSONEncoder) + "\n"
        else:
            text = export_salon_profile_csv(salon)
        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
