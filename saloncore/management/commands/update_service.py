"""Update one price-book service via the saloncore update_service service.

Usage:
    python manage.py update_service --salon-id ID --service-id ID
        [--name TEXT] [--description TEXT]
        [--category-id ID | --category-name TEXT]
        [--service-minutes N] [--processing-minutes N]
        [--finishing-minutes N] [--active | --inactive] [--dry-run]

Every update flag is optional: an omitted flag leaves that field
unchanged (the service's ``None`` sentinel). The category is
named by id (``--category-id``) or resolved by name inside the
salon (``--category-name``), exactly as ``add_service`` resolves
it. With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_update_service`` helper only and
prints the fields that WOULD change. The writer is never called,
so the preview is safe on every backend (including NEDB, where a
rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper around
:func:`saloncore.update_service.update_service`: it resolves the
salon and service by id, delegates all validation to that service
verbatim, and prints a one-line summary -- no logic of its own,
and no price (``set_price``'s job).

An unknown salon or service, or a service ``ValueError``
(cross-salon service or category, unknown/ambiguous category,
blank or over-long name, bad minute segments, no field given)
is surfaced here as ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, Service
from saloncore.update_service import update_service, validate_update_service


class Command(BaseCommand):
    help = "Update one price-book service in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the service.")
        parser.add_argument(
            "--service-id", required=True, type=int,
            help="ID of the service to update.")
        parser.add_argument(
            "--category-id", type=int, default=None,
            help="ID of the service's new category (in the salon).")
        parser.add_argument(
            "--category-name", default=None,
            help="Name of the service's new category, resolved "
                 "inside the salon; alternative to --category-id.")
        parser.add_argument(
            "--name", default=None, help="New service name.")
        parser.add_argument(
            "--description", default=None,
            help="New service description (may be blank).")
        parser.add_argument(
            "--service-minutes", type=int, default=None,
            help="New hands-on duration in minutes (at least 1).")
        parser.add_argument(
            "--processing-minutes", type=int, default=None,
            help="New processing duration in minutes.")
        parser.add_argument(
            "--finishing-minutes", type=int, default=None,
            help="New finishing duration in minutes.")
        parser.add_argument(
            "--active", dest="active", action="store_true", default=None,
            help="Make the service active.")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Make the service inactive.")
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
            service = Service.objects.get(pk=options["service_id"])
        except Service.DoesNotExist as exc:
            raise CommandError(
                f"No service with id {options['service_id']}.") from exc
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
            description=options.get("description"),
            category=options.get("category_id"),
            category_name=options.get("category_name"),
            service_minutes=options.get("service_minutes"),
            processing_minutes=options.get("processing_minutes"),
            finishing_minutes=options.get("finishing_minutes"),
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_update_service(salon, service, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            parts = []
            for field, value in cleaned.items():
                if field == "category":
                    value = f"{value.pk} ({value.name!r})"
                else:
                    value = repr(value) if isinstance(value, str) else value
                parts.append(f"{field}={value}")
            self.stdout.write(
                f"Dry run: would update service {service.pk} "
                f"in salon {salon.pk}: {' '.join(parts)} "
                f"-- no service written.")
            return
        try:
            service = update_service(salon, service, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Updated service {service.pk}: {service.name!r} "
            f"in salon {salon.pk}: category={service.category_id} "
            f"service_minutes={service.service_minutes} "
            f"processing_minutes={service.processing_minutes} "
            f"finishing_minutes={service.finishing_minutes} "
            f"active={service.active}.")
