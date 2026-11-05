"""Export one salon's derived online-booking branding payload as CSV or JSON.

Usage:
    python manage.py export_branding --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`onlinebooking.branding_export` --
that service is the one source of truth for the branding
export; this command only resolves the salon, delegates to
the service verbatim, and writes the text it produces (to
``--output`` when given, otherwise to stdout). For
``--format csv`` (the default) the CSV from
``export_branding_csv`` is exactly as before, byte-identical;
for ``--format json`` the same salon is passed to the dict
service ``export_branding`` (beside its CSV twin) and its
dict is serialised as JSON via ``DjangoJSONEncoder``, so the
two formats can never disagree. The row carries the DERIVED
payload a booking page renders from -- fallback values,
``is_branded`` and ``fallbacks_applied`` -- not the stored
Salon fields (``export_salon_profile`` owns those).
An unknown salon or an unknown format raises
``CommandError``. Backend only; read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from onlinebooking.branding_export import export_branding, export_branding_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export one salon's derived online-booking branding payload as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose branding payload to export.",
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
            row = export_branding(salon)
            text = json.dumps(
                row, indent=2, cls=DjangoJSONEncoder) + "\n"
        else:
            text = export_branding_csv(salon)
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
