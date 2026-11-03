"""Set (or clear) one appointment's desk price override.

Usage:
    python manage.py set_appointment_price --appointment-id ID
        --price PRICE [--salon-id ID] [--dry-run]

``--price ""`` (an empty value) CLEARS the override, so the
price book speaks again for that appointment.

With ``--dry-run`` nothing is written: the command runs the
service inside a transaction it rolls back, so the preview
applies the service's own validation and prints the price
that WOULD result (current -> override).

Thin wrapper around
:func:`bookings.price_override.set_appointment_price`: the
appointment is resolved by id (scoped to the salon via both
its client and its staff member when ``--salon-id`` is given,
the bookings salon-scoping convention), and the price is
passed to the service verbatim -- its money validation
(finite, non-negative, cent-quantized, never via float) stays
the single source of truth and surfaces here as
``CommandError``. This command adds no price logic of its
own, so command and service can never disagree. The price
book row itself is never touched. Backend only -- no views,
templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.models import Appointment
from bookings.price_override import set_appointment_price
from saloncore.models import Salon


def _fmt(value):
    return "none" if value is None else str(value)


class Command(BaseCommand):
    help = "Set (or clear, with an empty price) one appointment's price override."

    def add_arguments(self, parser):
        parser.add_argument(
            "--appointment-id", required=True, type=int,
            help="Id of the appointment to set the price for.")
        parser.add_argument(
            "--salon-id", type=int, default=None,
            help="Optional id of the salon the appointment must "
                 "belong to (via both its client and its staff "
                 "member).")
        parser.add_argument(
            "--price", "--price-override", dest="price",
            required=True,
            help="Desk price for this appointment (e.g. 72.50); "
                 "an empty value clears the override.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: run the service inside a "
                 "transaction that is rolled back, print the "
                 "current -> override price, and write nothing.")

    def handle(self, *args, **options):
        appointment_id = options.get("appointment_id")
        if appointment_id is None:
            raise CommandError("Provide --appointment-id.")
        # ``price_override`` is an alias if supplied via
        # call_command kwargs; an explicit empty price is a
        # clear, not a missing value, so never use ``or`` here.
        price = options.get("price")
        if price is None and options.get("price_override") is not None:
            price = options.get("price_override")
        salon_id = options.get("salon_id")
        salon = None
        if salon_id is not None:
            try:
                salon = Salon.objects.get(pk=salon_id)
            except Salon.DoesNotExist:
                raise CommandError(
                    f"No salon with id {salon_id}.") from None
        qs = Appointment.objects.all()
        if salon is not None:
            qs = qs.filter(client__salon=salon,
                           staff_member__salon=salon)
        try:
            appointment = qs.get(pk=appointment_id)
        except Appointment.DoesNotExist:
            if salon is not None:
                raise CommandError(
                    f"No appointment with id {appointment_id} "
                    f"in salon {salon.pk}.") from None
            raise CommandError(
                f"No appointment with id {appointment_id}.") from None
        current = appointment.price_override
        if options.get("dry_run"):
            try:
                with transaction.atomic():
                    set_appointment_price(appointment, price)
                    preview = appointment.price_override
                    transaction.set_rollback(True)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would set price for appointment "
                f"{appointment.pk}: {_fmt(current)} -> "
                f"{_fmt(preview)} -- no price written.")
            return
        try:
            set_appointment_price(appointment, price)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Appointment {appointment.pk} price: "
            f"{_fmt(current)} -> "
            f"{_fmt(appointment.price_override)}")
