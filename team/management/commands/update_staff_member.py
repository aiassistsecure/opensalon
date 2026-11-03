"""Update one staff member via the team update_staff_member service.

Usage:
    python manage.py update_staff_member --salon-id ID
        --staff-member-id ID [--display-name TEXT]
        [--staff-level-id ID] [--email ADDRESS] [--pin DIGITS]
        [--online-bookable | --no-online-bookable]
        [--active | --inactive] [--dry-run]

Every field flag is optional; an omitted flag leaves that
field unchanged, and at least one must be given. With
``--dry-run`` nothing is written: the command calls only
the service's read-only ``validate_update_staff_member``
helper and prints the member that WOULD result; the writer
is never called, so the preview is safe on every backend
(including NEDB, where a rolled-back transaction does not
undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`team.update_staff_member.update_staff_member`:
it resolves salon, member, and staff level by id, delegates
verbatim, and prints a one-line summary; it adds no
validation of its own. Capabilities/roster stay the
``set_*`` commands' job. The PIN is never printed (a
credential); only whether one is set. Unknown salon/member/
level or a service ``ValueError`` surfaces as
``CommandError``.
"""
import argparse

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.update_staff_member import (
    update_staff_member, validate_update_staff_member)


def _describe(salon, member_id, display_name, staff_level_id,
              online_bookable, email, pin, active):
    return (
        f"staff member {member_id} in salon {salon.pk}: "
        f"display_name={display_name!r} "
        f"staff_level_id={staff_level_id} "
        f"online_bookable={online_bookable} email={email!r} "
        f"pin_set={bool(pin)} active={active}")


class Command(BaseCommand):
    help = "Update one staff member in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the staff member.")
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="ID of the staff member to update.")
        parser.add_argument(
            "--display-name", default=None,
            help="New display name (omitted = unchanged).")
        parser.add_argument(
            "--staff-level-id", type=int, default=None,
            help="ID of the member's new staff level "
                 "(must belong to the salon; omitted = unchanged).")
        parser.add_argument(
            "--online-bookable", action=argparse.BooleanOptionalAction,
            default=None,
            help="Per-staff online-booking toggle "
                 "(omitted = unchanged).")
        parser.add_argument(
            "--active", action="store_true", default=None,
            dest="active", help="Mark the member active.")
        parser.add_argument(
            "--inactive", action="store_false", default=None,
            dest="active", help="Mark the member inactive.")
        parser.add_argument(
            "--email", default=None,
            help="New account email (empty string clears it).")
        parser.add_argument(
            "--pin", default=None,
            help="New time-clock PIN, 4 to 8 digits, unique in "
                 "the salon (empty string clears it).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the update without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            member = StaffMember.objects.get(
                pk=options["staff_member_id"], salon=salon)
        except StaffMember.DoesNotExist as exc:
            raise CommandError(
                f"No staff member with id "
                f"{options['staff_member_id']} in salon "
                f"{salon.pk}.") from exc
        staff_level = None
        level_id = options.get("staff_level_id")
        if level_id is not None:
            try:
                staff_level = StaffLevel.objects.get(pk=level_id)
            except StaffLevel.DoesNotExist as exc:
                raise CommandError(
                    f"No staff level with id {level_id}.") from exc
        kwargs = {}
        if options.get("display_name") is not None:
            kwargs["display_name"] = options["display_name"]
        if level_id is not None:
            kwargs["staff_level"] = staff_level
        if options.get("email") is not None:
            kwargs["email"] = options["email"]
        if options.get("pin") is not None:
            kwargs["pin"] = options["pin"]
        if options.get("online_bookable") is not None:
            kwargs["online_bookable"] = bool(options["online_bookable"])
        if options.get("active") is not None:
            kwargs["active"] = bool(options["active"])
        if options.get("dry_run"):
            try:
                cleaned = validate_update_staff_member(
                    salon, member, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            merged = dict(
                display_name=member.display_name,
                staff_level_id=member.staff_level_id,
                online_bookable=member.online_bookable,
                email=member.email, pin=member.pin,
                active=member.active)
            for field, value in cleaned.items():
                merged["staff_level_id" if field == "staff_level"
                       else field] = (
                    value.pk if field == "staff_level" else value)
            self.stdout.write(
                "Dry run: would update " + _describe(
                    salon, member.pk, merged["display_name"],
                    merged["staff_level_id"],
                    merged["online_bookable"], merged["email"],
                    merged["pin"], merged["active"])
                + " -- no staff member written.")
            return
        try:
            member = update_staff_member(salon, member, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Updated staff member {member.pk}: " + _describe(
                salon, member.pk, member.display_name,
                member.staff_level_id, member.online_bookable,
                member.email, member.pin, member.active) + ".")
