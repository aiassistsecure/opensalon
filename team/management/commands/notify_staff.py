"""Notify one staff member about one appointment.

Usage:
    python manage.py notify_staff --staff-member-id ID
        --appointment-id ID [--kind KIND] [--dry-run]

Thin wrapper around :func:`team.notifications.notify_staff`:
the staff member and appointment are resolved by id and the
kind is passed to the service verbatim -- its validation
stays the single source of truth and surfaces here as
``CommandError``. This command adds no notification logic
of its own, so command and webui check-in can never disagree
about the ping's shape.

With ``--dry-run`` nothing is written: the command calls
the service's validate-only helper, prints the ping that
WOULD be created, and returns before the writer runs --
no write happens at all, so the preview is safe on every
backend (NEDB does not roll back transaction writes).

Invalid input -- an unknown staff member, an unknown
appointment, or a service ``ValidationError`` -- raises
``CommandError`` and nothing is written. Backend only --
no views, templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment
from team.models import StaffMember
from team.notifications import notify_staff, validate_notify_staff


def _describe(member, appointment, kind):
    return (f"StaffNotification staff_member={member} "
            f"staff_member_id={member.pk} "
            f"appointment_id={appointment.pk} kind={kind}")


class Command(BaseCommand):
    help = "Create one staff notification ping for an appointment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member to notify.")
        parser.add_argument(
            "--appointment-id", required=True, type=int,
            help="Id of the appointment the ping is about.")
        parser.add_argument(
            "--kind", default="arrived",
            help="Notification kind (default: arrived).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate with the service's "
                 "validate-only helper, print the ping that "
                 "would be created, write nothing.")

    def handle(self, *args, **options):
        try:
            member = StaffMember.objects.get(
                pk=options.get("staff_member_id"))
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options.get('staff_member_id')}.") from None
        try:
            appointment = Appointment.objects.get(
                pk=options.get("appointment_id"))
        except Appointment.DoesNotExist:
            raise CommandError(
                f"No appointment with id "
                f"{options.get('appointment_id')}.") from None
        kind = options.get("kind") or "arrived"
        if options.get("dry_run"):
            try:
                kind = validate_notify_staff(member, appointment, kind)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            preview = _describe(member, appointment, kind)
            self.stdout.write(
                f"Dry run: would create {preview} "
                f"-- no notification written.")
            return
        try:
            note = notify_staff(member, appointment, kind)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Created {_describe(member, appointment, note.kind)} "
            f"id={note.pk}.")
