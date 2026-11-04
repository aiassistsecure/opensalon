"""Export one salon's staff notifications as CSV.

Usage:
    python manage.py export_staff_notifications --salon-id ID
        [--staff-member-id ID] [--output PATH]

Thin wrapper around the existing
:func:`team.notification_export.export_staff_notifications_csv`
service: the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. This command adds no
export logic of its own, so command and service output can
never disagree -- one source of truth.

With ``--staff-member-id`` the export is narrowed to that one
staff member's notifications: the staff member is resolved
by id within the salon (a staff member from another salon, or
an unknown id, is a ``CommandError``), and the resolved staff
member is passed to the service as its optional
``staff_member`` argument. Without ``--staff-member-id`` the
command exports the whole salon, exactly as before.

An unknown salon raises ``CommandError``. Backend only -- no
views, templates, or UI. Read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.models import StaffMember
from team.notification_export import export_staff_notifications_csv


class Command(BaseCommand):
    help = "Export one salon's staff notifications as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose staff notifications to export.")
        parser.add_argument(
            "--staff-member-id", type=int, default=None,
            help="ID of the staff member (in the salon) whose "
                 "notifications to export "
                 "(default: all staff members).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        staff_member = None
        if options.get("staff_member_id") is not None:
            try:
                staff_member = StaffMember.objects.get(
                    pk=options["staff_member_id"], salon=salon
                )
            except StaffMember.DoesNotExist:
                raise CommandError(
                    f"No staff member with id "
                    f"{options['staff_member_id']} "
                    f"for salon {options['salon_id']}.") from None

        text = export_staff_notifications_csv(
            salon, staff_member=staff_member)

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
