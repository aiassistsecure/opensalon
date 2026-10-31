"""Export one salon's online booking lookup results as CSV.

Usage:
    python manage.py export_booking_lookup --salon-id ID
        [--client-id ID] [--now ISO-DATETIME]
        [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.lookup_export.export_lookup_csv`
service: this command delegates verbatim to
``export_lookup_csv(salon, client, now=now)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.

Both lookup arguments are optional and default to ``None``
exactly as the service defines them: no ``--client-id`` means
the salon-wide lookup (every client of the salon), and no
``--now`` means the service's own default reference instant.
A client belonging to a different salon exports nothing,
exactly as the lookup service defines it -- never another
salon's bookings, and no error that confirms the client
exists elsewhere.

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, an unknown client, or an
unparseable ``--now`` -- raises ``CommandError``, as do
service errors and unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from onlinebooking.lookup_export import export_lookup_csv
from saloncore.models import Salon


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


class Command(BaseCommand):
    help = "Export one salon's online booking lookup results as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose booking lookup to export.")
        parser.add_argument(
            "--client-id", dest="client_id", default=None, type=int,
            help="Id of the client to look up (default: salon-wide, "
                 "as the service defines it).")
        parser.add_argument(
            "--now", dest="now", default=None,
            help="Reference instant for upcoming, ISO datetime "
                 "(default: the service's own default).")
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

        now = _parse_now(options.get("now"), salon)

        try:
            text = export_lookup_csv(salon, client, now=now)
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
