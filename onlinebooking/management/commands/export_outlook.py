"""Export one salon's online booking availability outlook as CSV or JSON.

Usage:
    python manage.py export_outlook --salon-id ID
        --duration-minutes MINUTES [--days N]
        [--start-date YYYY-MM-DD] [--step-minutes MINUTES]
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`onlinebooking.outlook_export` services: for
``--format csv`` (the default) this command delegates verbatim
to ``export_outlook_csv(salon, service_duration, days=days,
start_date=start_date, step_minutes=step_minutes)``; for
``--format json`` the same arguments are passed to the dict
service ``export_outlook`` (beside its CSV twin) and its rows
are serialised as JSON. The command adds no export logic of
its own, so the command output and the service output can
never disagree -- one source of truth, and the CSV output is
exactly as before, byte-identical.

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
import json

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.outlook import DEFAULT_OUTLOOK_DAYS
from onlinebooking.outlook_export import export_outlook, export_outlook_csv
from onlinebooking.slots import SLOT_STEP_MINUTES
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's online booking availability outlook as CSV or JSON."

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
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

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

        service_kwargs = dict(
            days=options["days"], start_date=options["start_date"],
            step_minutes=options["step_minutes"])
        if fmt == "json":
            rows = export_outlook(
                salon, options["duration_minutes"], **service_kwargs)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_outlook_csv(
                salon, options["duration_minutes"], **service_kwargs)

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
