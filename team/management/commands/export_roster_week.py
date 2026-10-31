"""Export one salon's roster week as CSV.

Usage:
    python manage.py export_roster_week --salon-id ID
        --week-start YYYY-MM-DD [--output PATH]

Thin wrapper around the existing
:func:`team.roster_week_export.export_roster_week_csv`
service: the salon is resolved by id, the week-start is parsed
to a ``datetime.date`` object, and both are passed to the
service verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. This command
adds no export logic of its own, so command and service output
can never disagree -- one source of truth.

Invalid input -- an unknown salon or an unparseable
week-start -- raises ``CommandError``. The week-start means
the Monday of its week in the salon's timezone, exactly as
the service defines it (a non-Monday date snaps to its
Monday). Backend only -- no views, templates, or UI.
Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.roster_week_export import export_roster_week_csv


def _parse_date(value, label):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's roster week as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose roster week to export.")
        parser.add_argument(
            "--week-start", dest="week_start", required=True,
            help="First day of the week, YYYY-MM-DD (its Monday).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        week_start = _parse_date(options["week_start"], "week-start date")
        try:
            text = export_roster_week_csv(salon, week_start)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

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
