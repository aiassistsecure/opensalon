"""Export one staff member's online booking slots for one day as CSV.

Usage:
    python manage.py export_slots --salon-id ID --staff-id ID
        --date YYYY-MM-DD (--duration-minutes MINUTES |
        --service-id ID) [--step-minutes MINUTES] [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.slots_export.export_slots_csv` service:
this command delegates verbatim to
``export_slots_csv(salon, staff, day, service_duration,
step_minutes=step_minutes)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.

The salon is resolved by ``--salon-id`` and the staff member by
``--staff-id``; an unknown id for either raises
``CommandError``. The service's ``service_duration`` argument is
supplied either as ``--duration-minutes`` (an integer number of
minutes, passed through unchanged) or as ``--service-id`` (the
resolved service object, which the service accepts verbatim as
a duration); exactly one of the two must be given. The
``--date`` day and ``--step-minutes`` grid spacing (default
``SLOT_STEP_MINUTES``) are passed through to the service
unchanged.

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, staff member, or service, a
missing duration source, an unparseable ``--date`` -- raises
``CommandError``, as do service errors and unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.slots import SLOT_STEP_MINUTES
from onlinebooking.slots_export import export_slots_csv
from saloncore.models import Salon, Service
from team.models import StaffMember


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CommandError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one staff member's online booking slots as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose slots to export.")
        parser.add_argument(
            "--staff-id", dest="staff_id", required=True, type=int,
            help="Id of the staff member to export slots for.")
        parser.add_argument(
            "--date", dest="date", type=_parse_date, required=True,
            help="Day to export, YYYY-MM-DD.")
        parser.add_argument(
            "--duration-minutes", dest="duration_minutes",
            default=None, type=int,
            help="Length of the service to fit, in minutes.")
        parser.add_argument(
            "--service-id", dest="service_id", default=None, type=int,
            help="Id of a service whose length to fit "
                 "(alternative to --duration-minutes).")
        parser.add_argument(
            "--step-minutes", dest="step_minutes", type=int,
            default=SLOT_STEP_MINUTES,
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

        try:
            staff = StaffMember.objects.get(pk=options["staff_id"])
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id {options['staff_id']}.") from None

        day = _coerce_date(options.get("date"))
        if day is None:
            raise CommandError("A --date is required.")

        service_id = options.get("service_id")
        duration_minutes = options.get("duration_minutes")
        if service_id is not None:
            try:
                service_duration = Service.objects.get(pk=service_id)
            except Service.DoesNotExist:
                raise CommandError(
                    f"No service with id {service_id}.") from None
        elif duration_minutes is not None:
            service_duration = duration_minutes
        else:
            raise CommandError(
                "Either --duration-minutes or --service-id is required.")

        step_minutes = options.get("step_minutes")
        if step_minutes is None:
            step_minutes = SLOT_STEP_MINUTES

        try:
            text = export_slots_csv(
                salon, staff, day, service_duration,
                step_minutes=step_minutes)
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
