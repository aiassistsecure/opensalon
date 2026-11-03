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

With ``--dry-run`` nothing is written: the service runs
inside a transaction that is rolled back (the established
pattern from ``team.set_shift_override``), so the preview
applies the service's own validation and prints the ping
that WOULD be created.

Invalid input -- an unknown staff member, an unknown
appointment, or a service ``ValidationError`` -- raises
``CommandError`` and nothing is written. Backend only --
no views, templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.models import Appointment
from team.models import StaffMember
from team.notifications import notify_staff


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
            help="Preview only: run the service inside a "
                 "transaction that is rolled back, print the "
                 "ping that would be created, write nothing.")

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
                with transaction.atomic():
                    note = notify_staff(member, appointment, kind)
                    preview = _describe(
                        member, appointment, note.kind)
                    transaction.set_rollback(True)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
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
