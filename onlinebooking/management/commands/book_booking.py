"""Book one appointment through online booking.

Usage:
    python manage.py book_booking --client-id ID
        --staff-member-id ID --service-id ID --start ISO-8601
        [--end ISO-8601] [--salon-id ID] [--note TEXT]
        [--note-author TEXT] [--dry-run]

Thin wrapper around
:func:`onlinebooking.services.create_online_booking` (which
delegates to ``bookings.lifecycle.create_appointment`` with
``online=True``): the client, staff member, and service are
resolved by id in-command, scoped to the salon when
``--salon-id`` is given (client by its salon, staff member by
its salon, service by its category's salon -- the bookings
salon-scoping convention, following ``rebook_booking``'s
resolver pattern), and passed to the service verbatim -- its
online-booking toggle, rostered-availability, overlap,
cross-salon, active, and performs refusals stay the single
source of truth and surface here as ``CommandError``.
``--end`` omitted defaults, in the service, to ``--start``
plus the service's total minutes. A non-empty ``--note``
becomes one appointment-only note on the new appointment,
never a client record note. The created appointment is
marked ``origin="online"`` by the service.

With ``--dry-run`` nothing is written: the preview runs the
service layer's read-only ``validate_create_online_booking``
helper, which applies the service's own validation without
calling the writer, and prints the booking that WOULD be
created. (No transaction rollback is relied on -- on NEDB a
rolled-back transaction does not undo writes.) Invalid input
-- unknown salon/client/staff/service, a record outside the
given salon, an unparseable datetime, or a service
``ValidationError`` -- raises ``CommandError``, nothing
written. Backend only -- no views, templates, or UI.
"""
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.services import (
    create_online_booking,
    validate_create_online_booking,
)
from saloncore.models import Salon, Service
from team.models import StaffMember


def _parse_datetime(value, label):
    if value is None or isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected ISO-8601 datetime."
        ) from exc


def _resolve(model, pk, label, salon, salon_filter):
    qs = model.objects.all()
    if salon is not None:
        qs = qs.filter(**{salon_filter: salon})
    try:
        return qs.get(pk=pk)
    except model.DoesNotExist:
        suffix = f" in salon {salon.pk}" if salon is not None else ""
        raise CommandError(f"No {label} with id {pk}{suffix}.") from None


def _resolve_all(options):
    salon_id = options.get("salon_id")
    salon = None
    if salon_id is not None:
        try:
            salon = Salon.objects.get(pk=salon_id)
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {salon_id}.") from None
    client_id = options.get("client_id")
    staff_id = options.get("staff_member_id") or options.get("staff_id")
    service_id = options.get("service_id")
    if client_id is None:
        raise CommandError("Provide --client-id.")
    if staff_id is None:
        raise CommandError("Provide --staff-member-id.")
    if service_id is None:
        raise CommandError("Provide --service-id.")
    client = _resolve(Client, client_id, "client", salon, "salon")
    staff = _resolve(StaffMember, staff_id, "staff member", salon, "salon")
    service = _resolve(Service, service_id, "service", salon,
                       "category__salon")
    return client, staff, service


class Command(BaseCommand):
    help = "Book one appointment through online booking."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", required=True, type=int,
                            help="Id of the client to book.")
        parser.add_argument("--staff-member-id", "--staff-id",
                            dest="staff_member_id", required=True, type=int,
                            help="Id of the staff member to book with.")
        parser.add_argument("--service-id", required=True, type=int,
                            help="Id of the service to book.")
        parser.add_argument("--salon-id", type=int, default=None,
                            help="Optional salon all three records must belong to.")
        parser.add_argument("--start", required=True,
                            help="Start, ISO-8601 datetime.")
        parser.add_argument("--end", default=None,
                            help="End, ISO-8601 (default: service duration).")
        parser.add_argument("--note", default="",
                            help="Optional appointment-only note for the booking.")
        parser.add_argument("--note-author", default="",
                            help="Optional author for --note.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only: validate, print the booking, write nothing.")

    def handle(self, *args, **options):
        client, staff, service = _resolve_all(options)
        start = _parse_datetime(options.get("start"), "start")
        if start is None:
            raise CommandError("Provide --start.")
        end = _parse_datetime(options.get("end"), "end")
        note = options.get("note") or ""
        note_author = options.get("note_author") or ""
        if options.get("dry_run"):
            try:
                preview_end = validate_create_online_booking(
                    client=client, staff_member=staff, service=service,
                    start=start, end=end)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would book appointment for client {client.pk} "
                f"with staff {staff.pk}, service {service.pk}: "
                f"{start.isoformat()} -> {preview_end.isoformat()}, "
                f"status {Appointment.Status.BOOKED}, note={note!r} "
                f"-- no appointment created.")
            return
        try:
            created = create_online_booking(
                client=client, staff_member=staff, service=service,
                start=start, end=end, note=note, note_author=note_author)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Booked appointment {created.pk}: client {client.pk} "
            f"with staff {staff.pk}, service {service.pk}: "
            f"{created.start.isoformat()} -> {created.end.isoformat()}, "
            f"status {created.status}.")
