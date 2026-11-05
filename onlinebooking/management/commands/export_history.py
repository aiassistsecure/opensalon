"""Export one salon's online booking history as CSV.

Usage:
    python manage.py export_history --salon-id ID
        [--client-id ID] [--now ISO-DATETIME] [--limit N]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--status STATUS] [--staff-id ID] [--service-id ID]
        [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.export_history.export_history_csv`
service: this command delegates verbatim to
``export_history_csv(salon, client, now=now, limit=limit,
start_date=start_date, end_date=end_date, status=status,
staff_member=staff_member, service=service)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.
``--status`` is the optional exact stored booking status to
filter by; omitted, no status filter applies.
``--staff-id`` is the optional id of the staff member to
filter by (the spelling the bookings ledger's staff filter
uses); it is resolved to its ``StaffMember`` and passed to
the service as its ``staff_member`` filter, and an unknown
id raises ``CommandError``; omitted, no staff filter applies.
``--service-id`` is the optional id of the service to
filter by; it is resolved to its ``Service`` and passed to
the service as its ``service`` filter, and an unknown
id raises ``CommandError``; omitted, no service filter applies.
``--start-date`` / ``--end-date`` are the optional inclusive
local-date window on booking ``start``, spelled as the other
Family XI ledger commands spell them (``--date-from`` /
``--date-to`` accepted as aliases); omitted, the export is
the previous unbounded output verbatim.

Note: the name ``export_upcoming`` was not used for the
sibling upcoming export because a ``bookings`` management
command already owns that global command name; this history
command faces no such collision.

All optional arguments default to ``None`` exactly as the
service defines them: no ``--client-id`` means the salon-wide
history, no ``--now`` means the service's own default
reference instant, and no ``--limit`` means the full history.
A client belonging to a different salon exports nothing,
exactly as the history service defines it.

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, an unknown client, or an
unparseable ``--now`` -- raises ``CommandError``, as do
service errors and unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
import argparse
import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from onlinebooking.export_history import export_history_csv
from saloncore.models import Salon, Service
from team.models import StaffMember


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_now(value, salon):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    tz = _tz_for(salon)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=tz)
    text = str(value).strip()
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            day = datetime.date.fromisoformat(text)
        except ValueError as exc:
            raise CommandError(
                f"Invalid now {value!r}; expected an ISO datetime."
            ) from exc
        return datetime.datetime.combine(
            day, datetime.time.min, tzinfo=tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(value, datetime.date):
        # Dates pass verbatim; datetimes pass too -- the service
        # reduces them to their salon-local date.
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's online booking history as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose booking history to export.")
        parser.add_argument(
            "--client-id", dest="client_id", default=None, type=int,
            help="Id of the client to export (default: salon-wide, "
                 "as the service defines it).")
        parser.add_argument(
            "--now", dest="now", default=None,
            help="Reference instant for past, ISO datetime "
                 "(default: the service's own default).")
        parser.add_argument(
            "--limit", dest="limit", default=None, type=int,
            help="Maximum rows to export (default: full history, "
                 "as the service defines it).")
        parser.add_argument(
            "--start-date", "--date-from", "--from-date",
            dest="start_date", type=_parse_date, default=None,
            help="Inclusive first day of the window on booking "
                 "start, YYYY-MM-DD (default: unbounded).")
        parser.add_argument(
            "--end-date", "--date-to", "--to-date",
            dest="end_date", type=_parse_date, default=None,
            help="Inclusive last day of the window on booking "
                 "start, YYYY-MM-DD (default: unbounded).")
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Booking status value to filter by (default: "
                 "no status filter, as the service defines it).")
        parser.add_argument(
            "--staff-id", dest="staff_id", default=None, type=int,
            help="Id of the staff member to filter by (default: "
                 "no staff filter, as the service defines it).")
        parser.add_argument(
            "--service-id", dest="service_id", default=None, type=int,
            help="Id of the service to filter by (default: "
                 "no service filter, as the service defines it).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        client = None
        if options.get("client_id") is not None:
            try:
                client = Client.objects.get(pk=options["client_id"])
            except Client.DoesNotExist:
                raise CommandError(
                    f"No client with id {options['client_id']}.") from None

        staff_member = None
        staff_value = options.get("staff_id")
        if staff_value is None:
            staff_value = options.get("staff_member")
        if staff_value is not None:
            staff_pk = getattr(staff_value, "pk", staff_value)
            try:
                staff_member = StaffMember.objects.get(pk=staff_pk)
            except (StaffMember.DoesNotExist, TypeError, ValueError):
                raise CommandError(
                    f"No staff member with id {staff_pk}.") from None

        service = None
        service_value = options.get("service_id")
        if service_value is None:
            service_value = options.get("service")
        if service_value is not None:
            service_pk = getattr(service_value, "pk", service_value)
            try:
                service = Service.objects.get(pk=service_pk)
            except (Service.DoesNotExist, TypeError, ValueError):
                raise CommandError(
                    f"No service with id {service_pk}.") from None

        now = _parse_now(options.get("now"), salon)
        start_date = _coerce_date(options.get("start_date"), "start-date")
        end_date = _coerce_date(options.get("end_date"), "end-date")

        try:
            text = export_history_csv(
                salon, client, now=now, limit=options.get("limit"),
                start_date=start_date, end_date=end_date,
                status=options.get("status"), staff_member=staff_member,
                service=service)
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
