"""Export one salon's reminder sends as CSV.

Usage:
    python manage.py export_send --salon-id ID
        --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
        [--appointment-id ID] [--channel CHANNEL]
        [--status STATUS] [--output PATH]

Thin wrapper around the existing
:func:`messaging.send_export.export_sends_csv`
service: the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and they are passed to the service
verbatim as ``(salon, date_from, date_to)`` -- its CSV text is
written unchanged, to ``--output`` when given and to stdout
otherwise. This command adds no export logic of its own, so
command and service output can never disagree -- one source
of truth.

With ``--appointment-id`` the export is narrowed to that one
appointment's sends: the appointment is resolved by id within
the salon (via its client, the ``client__salon`` scoping the
send export service uses; an appointment from another salon,
or an unknown id, is a ``CommandError``), and the resolved
appointment is passed to the service as its optional
``appointment`` argument. Without ``--appointment-id`` the
command exports the whole salon, exactly as before.

With ``--channel`` the export is narrowed to sends on that
one channel: the value is passed to the service as its
optional ``channel`` argument (the spelling the
``export_campaigns`` and ``export_due_reminders`` commands
use), composing with the date window and ``--appointment-id``.
Without ``--channel`` the command exports every channel,
exactly as before. Read-only: it filters the ledger, it
sends nothing.

With ``--status`` the export is narrowed to sends with that
one stored status: the value is validated against
``ReminderSend.Status`` and passed to the service as its
optional ``status`` argument, composing with the date
window, ``--appointment-id``, and ``--channel``. Without
``--status`` the command exports every status, exactly as
before. An unknown / invalid status raises ``CommandError``
(the same invalid-input handling this command applies to
its other validated arguments), rather than exporting.
Read-only: it filters the ledger, it sends nothing.

Invalid input -- an unknown salon or a service error -- raises
``CommandError``, as does an unwritable ``--output`` path.
Read-only. Core stays provider-agnostic -- no provider SDK,
field, or name appears here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment
from messaging.models import ReminderSend
from messaging.send_export import export_sends_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(
            value, (datetime.date, datetime.datetime)):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


def _first(options, *keys):
    for key in keys:
        value = options.get(key)
        if value is not None:
            return value
    return None


class Command(BaseCommand):
    help = "Export one salon's reminder sends as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose sends to export.",
        )
        parser.add_argument(
            "--date-from", dest="date_from", type=_parse_date,
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--start", dest="start", type=_parse_date, default=None,
            help="Alias for --date-from.",
        )
        parser.add_argument(
            "--start-date", dest="start_date", type=_parse_date,
            default=None, help="Alias for --date-from.",
        )
        parser.add_argument(
            "--date-to", dest="date_to", type=_parse_date,
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end", dest="end", type=_parse_date, default=None,
            help="Alias for --date-to.",
        )
        parser.add_argument(
            "--end-date", dest="end_date", type=_parse_date,
            default=None, help="Alias for --date-to.",
        )
        parser.add_argument(
            "--appointment-id", type=int, default=None,
            help="Id of the appointment (in the salon) whose sends "
                 "to export (default: all appointments).",
        )
        parser.add_argument(
            "--channel", dest="channel", default=None,
            help="Reminder send channel value to filter by "
                 "(default: all channels).",
        )
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Reminder send status value to filter by "
                 "(default: all statuses).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        date_from = _coerce_date(
            _first(options, "date_from", "start", "start_date"),
            "date_from")
        date_to = _coerce_date(
            _first(options, "date_to", "end", "end_date"), "date_to")
        appointment = None
        if options.get("appointment_id") is not None:
            try:
                appointment = Appointment.objects.get(
                    pk=options["appointment_id"], client__salon=salon)
            except Appointment.DoesNotExist as exc:
                raise CommandError(
                    f"No appointment with id {options['appointment_id']} "
                    f"for salon {salon.pk}."
                ) from exc
        status = options.get("status")
        if status is not None and status not in ReminderSend.Status.values:
            raise CommandError(
                f"Unknown status {status!r}; expected one of: "
                + ", ".join(ReminderSend.Status.values) + "."
            )
        try:
            text = export_sends_csv(
                salon, date_from, date_to, appointment=appointment,
                channel=options.get("channel"), status=status,
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
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
