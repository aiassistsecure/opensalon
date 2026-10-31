"""Export a salon's client opt-in counts summary as JSON.

Usage:
    python manage.py export_optin_summary --salon-id ID [--output PATH]

Thin wrapper around ``clients.optin_export.export_optin_summary`` --
that service is the one source of truth for the opt-in summary
shape; this command only resolves the salon, delegates verbatim,
serializes the dict it returns as JSON, and routes it to the
``--output`` file when given or to stdout otherwise. It never
reimplements counting or querying.

The service returns a dict with exactly these keys: ``total``,
``sms_opt_in``, ``email_opt_in``, ``both_opt_in``, ``sms_only``,
``email_only``, and ``neither_opt_in`` (all integers).

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from clients.optin_export import export_optin_summary
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's client opt-in counts summary as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose opt-in summary to export.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the JSON file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

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
