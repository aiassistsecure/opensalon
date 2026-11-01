"""Export a salon's core data to a single JSON file.

Usage:
    python manage.py export_salon_data OUTPUT.json [--salon NAME]

Exit Principle (founding rule): anything a salon can enter, it can
fully export. This is part 1 of that test — the core records only:

- saloncore: Salon, ServiceCategory, Service, StaffLevel, ServicePrice
  (StaffLevel is included because ServicePrice rows reference it;
  without levels an exported price cannot be interpreted.)
- clients: Client (including the ``sms_opt_in`` / ``email_opt_in``
  flags) and ClientNote (persistent client record notes).
- team: StaffMember (including the ``online_bookable`` toggle).
- bookings: Appointment and AppointmentNote (appointment-only
  notes; a separate model from ClientNote — the two kinds never
  blur). Appointment rows carry their own ``external_id`` plus the
  ``client`` / ``staff_member`` / ``service`` references as both the
  internal ``*_id`` (following the other sections) and the related
  record's ``*_external_id`` where that model carries one.

No new models and no provider concepts: plain querysets turned into
plain dicts, Decimals as strings and datetimes as ISO-8601 so the file
round-trips losslessly through ``json.load``. Without ``--salon`` every
salon in the database is exported; with it, only that salon's records
(clients/staff scoped by salon, categories/services/prices/levels
scoped through their salon/category/service chain).
"""

import json

from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember


def _dt(value):
    return value.isoformat() if value is not None else None


class Command(BaseCommand):
    help = "Export salon core data (price book, clients, staff, appointments) to one JSON file."

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path of the JSON file to write.")
        parser.add_argument(
            "--salon", default=None,
            help="Only export the salon with this exact name.",
        )

    def handle(self, *args, **options):
        salons = Salon.objects.all()
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
            if not salons.exists():
                raise CommandError(f"No salon named {options['salon']!r}.")
        salon_ids = list(salons.values_list("id", flat=True))

        categories = ServiceCategory.objects.filter(salon_id__in=salon_ids)
        category_ids = list(categories.values_list("id", flat=True))
        services = Service.objects.filter(category_id__in=category_ids)
        service_ids = list(services.values_list("id", flat=True))
        levels = StaffLevel.objects.filter(salon_id__in=salon_ids)
        prices = ServicePrice.objects.filter(service_id__in=service_ids)
        clients = Client.objects.filter(salon_id__in=salon_ids)
        client_ids = list(clients.values_list("id", flat=True))
        notes = ClientNote.objects.filter(client_id__in=client_ids)
        staff = StaffMember.objects.filter(salon_id__in=salon_ids)
        appointments = Appointment.objects.filter(
            client_id__in=client_ids
        ).select_related("client", "staff_member", "service")
        appointment_ids = list(appointments.values_list("id", flat=True))
        appointment_notes = AppointmentNote.objects.filter(
            appointment_id__in=appointment_ids
        )

        data = {
            "salons": [
                {
                    "id": s.id, "name": s.name, "timezone": s.timezone,
                    "currency": s.currency,
                    "created_at": _dt(s.created_at),
                    "updated_at": _dt(s.updated_at),
                }
                for s in salons
            ],
            "service_categories": [
                {
                    "id": c.id, "salon_id": c.salon_id, "name": c.name,
                    "sort_order": c.sort_order, "active": c.active,
                }
                for c in categories
            ],
            "services": [
                {
                    "id": s.id, "category_id": s.category_id,
                    "external_id": s.external_id, "name": s.name,
                    "description": s.description,
                    "service_minutes": s.service_minutes,
                    "processing_minutes": s.processing_minutes,
                    "finishing_minutes": s.finishing_minutes,
                    "active": s.active,
                }
                for s in services
            ],
            "staff_levels": [
                {
                    "id": lvl.id, "salon_id": lvl.salon_id, "name": lvl.name,
                    "sort_order": lvl.sort_order, "active": lvl.active,
                }
                for lvl in levels
            ],
            "service_prices": [
                {
                    "id": p.id, "service_id": p.service_id,
                    "staff_level_id": p.staff_level_id,
                    "amount": str(p.amount), "is_from": p.is_from,
                    "active": p.active,
                }
                for p in prices
            ],
            "clients": [
                {
                    "id": c.id, "salon_id": c.salon_id,
                    "external_id": c.external_id,
                    "first_name": c.first_name, "last_name": c.last_name,
                    "email": c.email, "phone": c.phone,
                    "sms_opt_in": c.sms_opt_in,
                    "email_opt_in": c.email_opt_in,
                    "active": c.active, "created_at": _dt(c.created_at),
                }
                for c in clients
            ],
            "client_notes": [
                {
                    "id": n.id, "client_id": n.client_id, "body": n.body,
                    "author_name": n.author_name,
                    "created_at": _dt(n.created_at),
                }
                for n in notes
            ],
            "staff_members": [
                {
                    "id": m.id, "salon_id": m.salon_id,
                    "external_id": m.external_id,
                    "display_name": m.display_name,
                    "staff_level_id": m.staff_level_id,
                    "online_bookable": m.online_bookable,
                    "active": m.active,
                }
                for m in staff
            ],
            "appointments": [
                {
                    "id": a.id,
                    "external_id": a.external_id,
                    "client_id": a.client_id,
                    "client_external_id": a.client.external_id,
                    "staff_member_id": a.staff_member_id,
                    "staff_member_external_id": a.staff_member.external_id,
                    "service_id": a.service_id,
                    "service_external_id": (
                        a.service.external_id if a.service else None
                    ),
                    "service_name": a.service_name,
                    "start": _dt(a.start), "end": _dt(a.end),
                    "status": a.status, "origin": a.origin,
                    "price_override": (
                        str(a.price_override)
                        if a.price_override is not None else None
                    ),
                    "created_at": _dt(a.created_at),
                    "updated_at": _dt(a.updated_at),
                }
                for a in appointments
            ],
            "appointment_notes": [
                {
                    "id": n.id, "appointment_id": n.appointment_id,
                    "body": n.body, "author_name": n.author_name,
                    "created_at": _dt(n.created_at),
                }
                for n in appointment_notes
            ],
        }
        data["counts"] = {
            key: len(value) for key, value in data.items()
        }

        try:
            with open(options["output"], "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=False)
                fh.write("\n")
        except OSError as exc:
            raise CommandError(
                f"Cannot write export file {options['output']}: {exc}"
            ) from exc

        summary = ", ".join(
            f"{key}={count}" for key, count in data["counts"].items()
        )
        self.stdout.write(f"EXPORT_SUMMARY {summary}")
        self.stdout.write(f"Wrote {options['output']}")
