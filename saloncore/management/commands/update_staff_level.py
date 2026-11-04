"""Update one staff level via the saloncore update_staff_level service.

Usage:
    python manage.py update_staff_level --salon-id ID
        --staff-level-id ID [--name TEXT] [--sort-order N]
        [--active | --inactive] [--dry-run]

Every update flag is optional: an omitted flag leaves that field
unchanged (the service's ``None`` sentinel). With ``--dry-run``
nothing is written: the command calls the service's read-only
``validate_update_staff_level`` helper only and prints the fields
that WOULD change. The writer is never called, so the preview is
safe on every backend (including NEDB, where a rolled-back
transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper around
:func:`saloncore.update_staff_level.update_staff_level`: it
resolves the salon and staff level by id, delegates all
validation to that service verbatim, and prints a one-line
summary -- no logic of its own.

An unknown salon or staff level, or a service ``ValueError``
(cross-salon staff level, blank or over-long name, bad
``sort_order``, no field given) is surfaced here as
``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, StaffLevel
from saloncore.update_staff_level import (
    update_staff_level,
    validate_update_staff_level,
)


class Command(BaseCommand):
    help = "Update one staff level in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the staff level.")
        parser.add_argument(
            "--staff-level-id", required=True, type=int,
            help="ID of the staff level to update.")
        parser.add_argument(
            "--name", default=None, help="New staff level name.")
        parser.add_argument(
            "--sort-order", type=int, default=None,
            help="New sort order.")
        parser.add_argument(
            "--active", dest="active", action="store_true", default=None,
            help="Make the staff level active.")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Make the staff level inactive.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the fields that would change "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            staff_level = StaffLevel.objects.get(pk=options["staff_level_id"])
        except StaffLevel.DoesNotExist as exc:
            raise CommandError(
                f"No staff level with id {options['staff_level_id']}.") from exc
        if options.get("inactive"):
            if options.get("active"):
                raise CommandError("Pass --active or --inactive, not both.")
            active = False
        elif options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = None
        kwargs = dict(
            name=options.get("name"),
            sort_order=options.get("sort_order"),
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_update_staff_level(
                    salon, staff_level, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            parts = []
            for field, value in cleaned.items():
                value = repr(value) if isinstance(value, str) else value
                parts.append(f"{field}={value}")
            self.stdout.write(
                f"Dry run: would update staff level {staff_level.pk} "
                f"in salon {salon.pk}: {' '.join(parts)} "
                f"-- no staff level written.")
            return
        try:
            staff_level = update_staff_level(salon, staff_level, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Updated staff level {staff_level.pk}: {staff_level.name!r} "
            f"in salon {salon.pk}: sort_order={staff_level.sort_order} "
            f"active={staff_level.active}.")
