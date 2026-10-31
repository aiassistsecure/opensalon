"""Export a salon's persistent client record notes as CSV.

Usage:
    python manage.py export_notes --salon-id ID [--output PATH]

Thin wrapper around ``clients.note_export.export_notes_csv`` --
that service is the one source of truth for the record-note export
shape; this command only resolves the salon, delegates verbatim,
and routes the CSV it returns to the ``--output`` file when given
or to stdout otherwise. It never reimplements serialization or
querying. Only persistent client record notes are exported;
appointment-only notes live in the bookings app and never appear.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.note_export import export_notes_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's persistent client record notes as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose record notes to export.",
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

        try:
            text = export_notes_csv(salon)
        except Exception as exc:
            raise CommandError(f"Notes export failed: {exc}") from exc

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
