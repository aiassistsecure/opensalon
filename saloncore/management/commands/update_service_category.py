"""Update one service category via the update_service_category service.

Usage:
    python manage.py update_service_category --salon-id ID
        --service-category-id ID [--name TEXT] [--sort-order N]
        [--active | --inactive] [--dry-run]

Every update flag is optional: an omitted flag leaves that field
unchanged (the service's ``None`` sentinel). With ``--dry-run``
nothing is written: the command calls the service's read-only
``validate_update_service_category`` helper only and prints the
fields that WOULD change. The writer is never called, so the
preview is safe on every backend (including NEDB, where a
rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper around
:func:`saloncore.update_service_category.update_service_category`:
it resolves the salon and service category by id, delegates all
validation to that service verbatim, and prints a one-line
summary -- no logic of its own.

An unknown salon or service category, or a service ``ValueError``
(cross-salon service category, blank or over-long name, bad
``sort_order``, no field given) is surfaced here as
``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, ServiceCategory
from saloncore.update_service_category import (
    update_service_category,
    validate_update_service_category,
)


class Command(BaseCommand):
    help = "Update one service category in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the service category.")
        parser.add_argument(
            "--service-category-id", required=True, type=int,
            help="ID of the service category to update.")
        parser.add_argument(
            "--name", default=None, help="New service category name.")
        parser.add_argument(
            "--sort-order", type=int, default=None,
            help="New sort order.")
        parser.add_argument(
            "--active", dest="active", action="store_true", default=None,
            help="Make the service category active.")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Make the service category inactive.")
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
            service_category = ServiceCategory.objects.get(
                pk=options["service_category_id"])
        except ServiceCategory.DoesNotExist as exc:
            raise CommandError(
                f"No service category with id "
                f"{options['service_category_id']}.") from exc
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
                cleaned = validate_update_service_category(
                    salon, service_category, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            parts = []
            for field, value in cleaned.items():
                value = repr(value) if isinstance(value, str) else value
                parts.append(f"{field}={value}")
            self.stdout.write(
                f"Dry run: would update service category "
                f"{service_category.pk} in salon {salon.pk}: "
                f"{' '.join(parts)} -- no service category written.")
            return
        try:
            service_category = update_service_category(
                salon, service_category, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Updated service category {service_category.pk}: "
            f"{service_category.name!r} in salon {salon.pk}: "
            f"sort_order={service_category.sort_order} "
            f"active={service_category.active}.")
