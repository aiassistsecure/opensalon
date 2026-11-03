"""Export one salon's attendance records as CSV.

Usage:
    python manage.py export_attendance_records --salon-id ID
        [--output PATH]

Thin wrapper around the existing
:func:`team.attendance_record_export.export_attendance_records_csv`
service: the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. This command adds no
export logic of its own, so command and service output can
never disagree -- one source of truth.

An unknown salon raises ``CommandError``. Backend only -- no
views, templates, or UI. Read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.attendance_record_export import export_attendance_records_csv


class Command(BaseCommand):
    help = "Export one salon's attendance records as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose attendance records to export.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        text = export_attendance_records_csv(salon)

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
