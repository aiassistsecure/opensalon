"""Export one salon's roster patterns as CSV.

Usage:
    python manage.py export_roster --salon-id ID [--output PATH]

Thin wrapper around the existing :mod:`team.roster_export`
service: this command delegates verbatim to
``export_roster_patterns_csv(salon)`` and adds no export logic
of its own, so the command output and the service output can
never disagree -- one source of truth.

The service takes no date arguments (roster patterns are
recurring weekly patterns, not dated records), so this command
takes none either. By default only active patterns are
exported, exactly as the service defaults.

Output goes to stdout unless ``--output`` names a file.
Backend only -- no views, templates, or UI. Read-only.
"""

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.roster_export import export_roster_patterns_csv


class Command(BaseCommand):
    help = "Export one salon's roster patterns as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose roster patterns to export.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        text = export_roster_patterns_csv(salon)

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
