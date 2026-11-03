"""Export a salon's client opt-in counts summary as JSON or CSV.

Usage:
    python manage.py export_optin_summary --salon-id ID
        [--format json|csv] [--output PATH]

Thin wrapper around ``clients.optin_export`` -- that service is
the one source of truth for the opt-in summary shape; this
command only resolves the salon, delegates verbatim, and routes
the result to the ``--output`` file when given or to stdout
otherwise. For ``--format json`` (the default) it serializes
:func:`~clients.optin_export.export_optin_summary`'s dict as
JSON, exactly as before; for ``--format csv`` it writes
:func:`~clients.optin_export.export_optin_summary_csv`'s CSV
string as-is -- that service builds its single row from the same
summary dict, so the two formats can never disagree. It never
reimplements counting or querying.

The service returns a dict with exactly these keys: ``total``,
``sms_opt_in``, ``email_opt_in``, ``both_opt_in``, ``sms_only``,
``email_only``, and ``neither_opt_in`` (all integers), which are
also the CSV header / field order.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.optin_export import (
    export_optin_summary,
    export_optin_summary_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's client opt-in counts summary as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose opt-in summary to export.",
        )
        parser.add_argument(
            "--format", dest="format", default="json", choices=_FORMATS,
            help="Export format: json (default) or csv.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "json"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        if fmt == "csv":
            text = export_optin_summary_csv(salon)
        else:
            result = export_optin_summary(salon)
            text = json.dumps(result, indent=2) + "\n"

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
