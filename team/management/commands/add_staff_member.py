"""Create one staff member via the team add_staff_member service.

Usage:
    python manage.py add_staff_member --salon-id ID
        --display-name TEXT [--staff-level-id ID]
        [--online-bookable | --no-online-bookable]
        [--email ADDRESS] [--pin DIGITS] [--inactive] [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_staff_member`` helper and
prints the member that WOULD be created; the writer is never
called, so the preview is safe on every backend (including
NEDB, where a rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`team.add_staff_member.add_staff_member`: it
resolves salon and staff level by id, delegates verbatim, and
prints a one-line summary; it adds no validation of its own,
so printed result and created member can never disagree.
Capabilities/roster stay the ``set_*`` commands' job. The PIN
is never printed (a credential); only whether one was set.
Unknown salon/level or a service ``ValueError`` surfaces as
``CommandError``.
"""
import argparse

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, StaffLevel
from team.add_staff_member import (
    add_staff_member, validate_add_staff_member)


def _describe(salon, display_name, staff_level, online_bookable,
              email, pin, active=True):
    level = staff_level.pk if staff_level is not None else None
    return (
        f"staff member {display_name!r} in salon {salon.pk}: "
        f"staff_level_id={level} online_bookable={online_bookable} "
        f"email={email!r} pin_set={bool(pin)} active={active}")


class Command(BaseCommand):
    help = "Create one staff member in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the staff member.")
        parser.add_argument(
            "--display-name", required=True,
            help="Staff member's display name.")
        parser.add_argument(
            "--staff-level-id", type=int, default=None,
            help="Optional ID of the member's staff level "
                 "(must belong to the salon).")
        parser.add_argument(
            "--online-bookable", action=argparse.BooleanOptionalAction,
            default=None,
            help="Per-staff online-booking toggle "
                 "(default: bookable; use --no-online-bookable "
                 "to create the member not bookable online).")
        parser.add_argument(
            "--email", default="",
            help="Optional account email.")
        parser.add_argument(
            "--pin", default="",
            help="Optional time-clock PIN (4 to 8 digits, "
                 "unique in the salon).")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the staff member inactive "
                 "(default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the member that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        staff_level = None
        level_id = options.get("staff_level_id")
        if level_id is not None:
            try:
                staff_level = StaffLevel.objects.get(pk=level_id)
            except StaffLevel.DoesNotExist as exc:
                raise CommandError(
                    f"No staff level with id {level_id}.") from exc
        online = options.get("online_bookable")
        # call_command may pass active= directly; CLI uses --inactive.
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            display_name=options["display_name"],
            staff_level=staff_level,
            online_bookable=True if online is None else bool(online),
            email=options.get("email") or "",
            pin=options.get("pin") or "",
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_staff_member(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                "Dry run: would create " + _describe(
                    cleaned["salon"], cleaned["display_name"],
                    cleaned["staff_level"],
                    cleaned["online_bookable"], cleaned["email"],
                    cleaned["pin"], cleaned["active"])
                + " -- no staff member written.")
            return
        try:
            member = add_staff_member(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created staff member {member.pk}: " + _describe(
                salon, member.display_name, member.staff_level,
                member.online_bookable, member.email, member.pin,
                member.active)
            + ".")
