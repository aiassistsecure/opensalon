"""Mark one staff member's unseen notifications seen.

Usage:
    python manage.py mark_notifications_seen
        --staff-member-id ID [--dry-run]

Thin wrapper around :func:`team.notifications.mark_seen`:
the staff member is resolved by id and passed to the service
verbatim. This command adds no seen logic of its own, so
command and My Day can never disagree about which rows are
stamped -- exactly that member's unseen pings, nothing else.

With ``--dry-run`` nothing is written: the service runs
inside a transaction that is rolled back (the established
pattern from ``team.set_shift_override``), so the preview
prints the seen-count that WOULD result and stamps nothing.

An unknown staff member raises ``CommandError`` and nothing
is written. Backend only -- no views, templates, or UI.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from team.models import StaffMember
from team.notifications import mark_seen


class Command(BaseCommand):
    help = "Mark one staff member's unseen notifications seen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member whose unseen "
                 "notifications to mark seen.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: run the service inside a "
                 "transaction that is rolled back, print the "
                 "count that would be marked seen, write "
                 "nothing.")

    def handle(self, *args, **options):
        try:
            member = StaffMember.objects.get(
                pk=options.get("staff_member_id"))
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options.get('staff_member_id')}.") from None
        if options.get("dry_run"):
            with transaction.atomic():
                count = mark_seen(member)
                transaction.set_rollback(True)
            self.stdout.write(
                f"Dry run: would mark {count} notification(s) "
                f"seen for staff_member_id={member.pk} "
                f"-- no notification marked seen.")
            return
        count = mark_seen(member)
        self.stdout.write(
            f"Marked {count} notification(s) seen for "
            f"{member} staff_member_id={member.pk}.")
