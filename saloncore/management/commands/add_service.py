"""Create one price-book service via the saloncore add_service service.

Usage:
    python manage.py add_service --salon-id ID --name TEXT
        --service-minutes N [--category-id ID | --category-name TEXT]
        [--description TEXT] [--processing-minutes N]
        [--finishing-minutes N] [--inactive] [--dry-run]

The category is named by id (``--category-id``) or resolved by
name inside the salon (``--category-name``); exactly one form is
required. With ``--dry-run`` nothing is written: the command
calls the service's read-only ``validate_add_service`` helper and
prints the service that WOULD be created. The writer is never
called, so the preview is safe on every backend (including NEDB,
where a rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`saloncore.add_service.add_service`: it resolves
the salon by id, delegates category resolution and all
validation to that service verbatim, and prints a one-line
summary -- no logic of its own, and no price (``set_price``'s
job).

An unknown salon or a service ``ValueError`` (missing / unknown
/ cross-salon / ambiguous category, blank or over-long name,
bad minute segments) is surfaced here as ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.add_service import add_service, validate_add_service
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Create one price-book service in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the service.")
        parser.add_argument(
            "--category-id", type=int, default=None,
            help="ID of the service's category (in the salon).")
        parser.add_argument(
            "--category-name", default="",
            help="Name of the service's category, resolved "
                 "inside the salon; alternative to --category-id.")
        parser.add_argument(
            "--name", required=True,
            help="Service name.")
        parser.add_argument(
            "--description", default="",
            help="Optional service description.")
        parser.add_argument(
            "--service-minutes", required=True, type=int,
            help="Hands-on duration in minutes (at least 1).")
        parser.add_argument(
            "--processing-minutes", type=int, default=0,
            help="Processing duration in minutes (default 0).")
        parser.add_argument(
            "--finishing-minutes", type=int, default=0,
            help="Finishing duration in minutes (default 0).")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the service inactive (default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the service that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        # call_command may pass active= directly; CLI uses --inactive.
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            name=options["name"],
            service_minutes=options["service_minutes"],
            category=options.get("category_id"),
            category_name=options.get("category_name") or None,
            description=options.get("description") or "",
            processing_minutes=options.get("processing_minutes") or 0,
            finishing_minutes=options.get("finishing_minutes") or 0,
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_service(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            category = cleaned["category"]
            self.stdout.write(
                f"Dry run: would create service {cleaned['name']!r} "
                f"in salon {salon.pk}: category={category.pk} "
                f"({category.name!r}) "
                f"service_minutes={cleaned['service_minutes']} "
                f"processing_minutes={cleaned['processing_minutes']} "
                f"finishing_minutes={cleaned['finishing_minutes']} "
                f"active={cleaned['active']} -- no service written.")
            return
        try:
            service = add_service(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created service {service.pk}: {service.name!r} "
            f"in salon {salon.pk}: category={service.category_id} "
            f"service_minutes={service.service_minutes} "
            f"processing_minutes={service.processing_minutes} "
            f"finishing_minutes={service.finishing_minutes} "
            f"active={service.active}.")
