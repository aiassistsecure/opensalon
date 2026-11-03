"""Set one service's price at one staff level.

Usage:
    python manage.py set_price --service-id ID --staff-level-id ID
        --amount 85 [--is-from true|false]
        [--price-active true|false] [--note TEXT] [--dry-run]

Thin wrapper around :func:`saloncore.pricing.set_price`: the
service and staff level are resolved by id (the level must belong
to the same salon as the service's category), and the amount /
is_from / price_active are passed to the service -- its validation
stays the single source of truth and surfaces here as
``CommandError``. ``--price-active`` omitted passes ``None`` to
the service, whose default is active -- exactly the behaviour
before this flag existed; ``false`` creates or sets an inactive
price, matching the ``price_active`` the price-book import/export
round-trips verbatim.
This command adds no price logic of its own, so command, service
and the price-book importer can never disagree. A price change
appends a ``PriceChange`` audit row with
``changed_by="set_price"``.

With ``--dry-run`` nothing is written, audit row included: the
command only reads the stored price, prints the old -> new price
and the ``price_active`` value that WOULD apply, and returns
without calling the service.

Invalid input -- an unknown service, an unknown staff level, a
cross-salon level, or a service ``ValidationError`` -- raises
``CommandError`` and nothing is written. Output names the service
and level by id only. Backend only -- no views, templates, or UI.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Service, ServicePrice, StaffLevel
from saloncore.pricing import set_price


def _parse_bool_flag(value, flag):
    if value is None or isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes", "on"):
        return True
    if lowered in ("false", "0", "no", "off"):
        return False
    raise CommandError(f"Invalid {flag} value {value!r}; use true or false.")


def _parse_is_from(value):
    return _parse_bool_flag(value, "--is-from")


def _parse_price_active(value):
    return _parse_bool_flag(value, "--price-active")


class Command(BaseCommand):
    help = "Set one service's price at one staff level."

    def add_arguments(self, parser):
        parser.add_argument(
            "--service-id", required=True, type=int,
            help="Id of the service whose price to set.")
        parser.add_argument(
            "--staff-level-id", "--level-id", dest="staff_level_id",
            required=True, type=int,
            help="Id of the staff level the price applies at.")
        parser.add_argument(
            "--amount", required=True,
            help="New price amount (e.g. 85 or 85.00).")
        parser.add_argument(
            "--is-from", dest="is_from", default=None,
            choices=("true", "false"),
            help="Starting-at pricing flag (true/false); "
                 "omitted = leave a stored flag unchanged.")
        parser.add_argument(
            "--price-active", dest="price_active", default=None,
            choices=("true", "false"),
            help="Price active flag (true/false); "
                 "omitted = active (the service default).")
        parser.add_argument(
            "--note", default="",
            help="Optional note stored on the PriceChange audit row.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the old -> new price and "
                 "write nothing, audit row included.")

    def handle(self, *args, **options):
        service_id = options.get("service_id")
        if service_id is None:
            raise CommandError("Provide --service-id.")
        staff_level_id = options.get("staff_level_id")
        if staff_level_id is None:
            raise CommandError("Provide --staff-level-id.")
        amount_raw = options.get("amount")
        if amount_raw is None:
            raise CommandError("Provide --amount.")
        try:
            amount = Decimal(str(amount_raw))
        except (InvalidOperation, ValueError):
            raise CommandError(
                f"Amount {amount_raw!r} is not a valid price.") from None
        is_from = _parse_is_from(options.get("is_from"))
        price_active = _parse_price_active(options.get("price_active"))
        try:
            service = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            raise CommandError(
                f"No service with id {service_id}.") from None
        try:
            staff_level = StaffLevel.objects.get(pk=staff_level_id)
        except StaffLevel.DoesNotExist:
            raise CommandError(
                f"No staff level with id {staff_level_id}.") from None
        if service.category.salon_id != staff_level.salon_id:
            raise CommandError(
                f"Staff level {staff_level.pk} belongs to a different "
                f"salon than service {service.pk}.")

        if options.get("dry_run"):
            existing = ServicePrice.objects.filter(
                service=service, staff_level=staff_level).first()
            old = existing.amount if existing else None
            self.stdout.write(
                f"Dry run: would set price for service {service.pk} "
                f"at staff level {staff_level.pk}: {old} -> {amount} "
                f"(price_active={price_active}) "
                f"-- no price or audit row written.")
            return

        try:
            result = set_price(
                service, staff_level, amount, is_from=is_from,
                changed_by="set_price", note=options.get("note") or "",
                price_active=price_active)
        except ValidationError as exc:
            raise CommandError("; ".join(
                str(m) for m in exc.messages)) from exc
        action = "Created" if result.created else "Set"
        self.stdout.write(
            f"{action} price for service {service.pk} at staff "
            f"level {staff_level.pk}: "
            f"{result.old_amount} -> {result.price.amount}")
