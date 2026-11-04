"""Create one service category via the saloncore add_service_category service.

Usage:
    python manage.py add_service_category --salon-id ID --name TEXT
        [--sort-order N] [--inactive] [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_service_category`` helper
and prints the category that WOULD be created. The writer is
never called, so the preview is safe on every backend
(including NEDB, where a rolled-back transaction does not
undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`saloncore.add_service_category.add_service_category`:
it resolves the salon by id, delegates all validation to that
service verbatim, and prints a one-line summary.

An unknown salon or a service ``ValueError`` is surfaced
here as ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.add_service_category import (
    add_service_category,
    validate_add_service_category,
)
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Create one service category in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the service category.")
        parser.add_argument(
            "--name", required=True,
            help="Service category name.")
        parser.add_argument(
            "--sort-order", type=int, default=0,
            help="Sort order (default 0).")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the category inactive (default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the category that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            name=options["name"],
            sort_order=options.get("sort_order") or 0,
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_service_category(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would create service category "
                f"{cleaned['name']!r} in salon {salon.pk}: "
                f"sort_order={cleaned['sort_order']} "
                f"active={cleaned['active']} "
                f"-- no service category written.")
            return
        try:
            category = add_service_category(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created service category {category.pk}: {category.name!r} "
            f"in salon {salon.pk}: sort_order={category.sort_order} "
            f"active={category.active}.")
