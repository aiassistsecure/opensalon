"""Mark one staff member's unseen notifications seen.

Usage:
    python manage.py mark_notifications_seen
        --staff-member-id ID [--dry-run] [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(staff member id, the number of notifications marked seen,
and ``dry_run``); no prose lines are printed in json mode.
The default ``--format text`` output is unchanged.

Thin wrapper around :func:`team.notifications.mark_seen`:
the staff member is resolved by id and passed to the service
verbatim. This command adds no seen logic of its own, so
command and My Day can never disagree about which rows are
stamped -- exactly that member's unseen pings, nothing else.

With ``--dry-run`` nothing is written: the command counts
the member's unseen notifications with the service's
read-only counter, prints the seen-count that WOULD result,
and returns before the writer runs -- no write happens at
all, so the preview is safe on every backend (NEDB does
not roll back transaction writes).

An unknown staff member raises ``CommandError`` and nothing
is written. Backend only -- no views, templates, or UI.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from team.models import StaffMember
from team.notifications import mark_seen, unseen_notification_count


class Command(BaseCommand):
    help = "Mark one staff member's unseen notifications seen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member whose unseen "
                 "notifications to mark seen.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: count the unseen notifications "
                 "without writing, print the count that would "
                 "be marked seen, write nothing.")
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        try:
            member = StaffMember.objects.get(
                pk=options.get("staff_member_id"))
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id "
                f"{options.get('staff_member_id')}.") from None
        if options.get("dry_run"):
            count = unseen_notification_count(member)
            if fmt == "json":
                self.stdout.write(json.dumps(dict(
                    staff_member_id=member.pk,
                    marked_seen=count,
                    dry_run=True)))
                return
            self.stdout.write(
                f"Dry run: would mark {count} notification(s) "
                f"seen for staff_member_id={member.pk} "
                f"-- no notification marked seen.")
            return
        count = mark_seen(member)
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                staff_member_id=member.pk,
                marked_seen=count,
                dry_run=False)))
            return
        self.stdout.write(
            f"Marked {count} notification(s) seen for "
            f"{member} staff_member_id={member.pk}.")
