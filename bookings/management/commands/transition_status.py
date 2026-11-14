"""Move one appointment to a new lifecycle status.

Usage:
    python manage.py transition_status --appointment-id ID
        --status STATUS [--dry-run] [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text line
(appointment id, old status, new status, and ``dry_run``);
no prose lines are printed in json mode. The default
``--format text`` output is unchanged.

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), so the preview applies the
service's own transition table and prints the current ->
target status that WOULD result.

Thin wrapper around
:func:`bookings.lifecycle.transition_status`: the appointment
is resolved by id and the target status is passed to the
service verbatim -- the service's own transition table decides
whether the move is allowed. This command adds no status logic
of its own, so command and service state can never disagree --
one source of truth.

Invalid input -- an unknown appointment or an unknown status --
raises ``CommandError``; a service ``ValidationError`` (an
invalid transition, including any move out of a terminal
status) is also surfaced as ``CommandError`` and the
appointment is left unchanged. Backend only -- no views,
templates, or UI.
"""
import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from bookings.lifecycle import transition_status, validate_transition_status
from bookings.models import Appointment


class Command(BaseCommand):
    help = "Move one appointment to a new lifecycle status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--appointment-id", required=True, type=int,
            help="Id of the appointment to transition.")
        parser.add_argument(
            "--status", "--to-status", "--new-status", dest="status",
            required=True,
            help="Target status (one of: "
                 + ", ".join(Appointment.Status.values) + ").")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate with the service's "
                 "validate-only helper, print the current -> "
                 "target status that would result, and write "
                 "nothing.")
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        appointment_id = options.get("appointment_id")
        # ``to_status``/``new_status`` are aliases if supplied
        # via call_command kwargs.
        new_status = (
            options.get("status") or options.get("to_status")
            or options.get("new_status"))
        if appointment_id is None:
            raise CommandError("Provide --appointment-id.")
        if new_status is None:
            raise CommandError("Provide --status.")
        new_status = str(new_status).strip().lower()
        if new_status not in Appointment.Status.values:
            raise CommandError(
                f"Unknown status {new_status!r}; expected one of: "
                + ", ".join(Appointment.Status.values) + ".")
        try:
            appointment = Appointment.objects.get(pk=appointment_id)
        except Appointment.DoesNotExist:
            raise CommandError(
                f"No appointment with id {appointment_id}.") from None
        old_status = appointment.status
        if options.get("dry_run"):
            try:
                validate_transition_status(appointment, new_status)
                preview_status = new_status
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            if fmt == "json":
                self.stdout.write(json.dumps(dict(
                    appointment_id=appointment.pk,
                    old_status=old_status,
                    new_status=preview_status,
                    dry_run=True)))
                return
            self.stdout.write(
                f"Dry run: would transition appointment "
                f"{appointment.pk}: {old_status} -> "
                f"{preview_status} -- no change written.")
            return
        try:
            transition_status(appointment, new_status)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                appointment_id=appointment.pk,
                old_status=old_status,
                new_status=appointment.status,
                dry_run=False)))
            return
        self.stdout.write(
            f"Appointment {appointment.pk}: "
            f"{old_status} -> {appointment.status}.")
