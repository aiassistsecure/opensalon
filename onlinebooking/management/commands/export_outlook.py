"""Export one salon's online booking availability outlook as CSV.

Usage:
    python manage.py export_outlook --salon-id ID
        --duration-minutes MINUTES [--days N]
        [--start-date YYYY-MM-DD] [--step-minutes MINUTES]
        [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.outlook_export.export_outlook_csv` service:
this command delegates verbatim to
``export_outlook_csv(salon, service_duration, days=days,
start_date=start_date, step_minutes=step_minutes)`` and adds no
export logic of its own, so the command output and the service
output can never disagree -- one source of truth.

The service requires ``service_duration`` (the length of the
service to fit, in minutes), exposed here as the required
``--duration-minutes`` integer; the service's other keyword
arguments are mirrored as ``--days`` (default
``DEFAULT_OUTLOOK_DAYS``), ``--start-date`` (default: the
service's own default), and ``--step-minutes`` (default
``SLOT_STEP_MINUTES``). The service's own errors propagate
unchanged (e.g. ``ValueError`` for a non-positive duration).

Output goes to stdout unless ``--output`` names a file.
Backend only -- no views, templates, or UI. Read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.outlook import DEFAULT_OUTLOOK_DAYS
from onlinebooking.outlook_export import export_outlook_csv
from onlinebooking.slots import SLOT_STEP_MINUTES
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's online booking availability outlook as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose outlook to export.")
        parser.add_argument(
            "--duration-minutes", required=True, type=int,
            dest="duration_minutes",
            help="Length of the service to fit, in minutes.")
        parser.add_argument(
            "--days", type=int, default=DEFAULT_OUTLOOK_DAYS,
            help="Window size in days (default: %(default)s).")
        parser.add_argument(
            "--start-date", type=_parse_date, default=None,
            dest="start_date",
            help="First day of the window, YYYY-MM-DD "
                 "(default: the service's own default).")
        parser.add_argument(
            "--step-minutes", type=int, default=SLOT_STEP_MINUTES,
            dest="step_minutes",
            help="Slot grid spacing in minutes (default: %(default)s).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        text = export_outlook_csv(
            salon, options["duration_minutes"], days=options["days"],
            start_date=options["start_date"],
            step_minutes=options["step_minutes"])

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
