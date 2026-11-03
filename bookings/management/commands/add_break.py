"""Add a break for one staff member.

Usage:
    python manage.py add_break --staff-member-id ID
        --starts-at ISO-8601-DATETIME --ends-at ISO-8601-DATETIME
        [--paid] [--salon-id ID] [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), so the preview applies the
service's own validation and prints the break that WOULD be
created (its staff member, start, end, and paid flag).

Thin wrapper around :func:`bookings.breaks.add_break`: the
staff member is resolved by id (scoped to the salon when
``--salon-id`` is given, the bookings salon-scoping
convention), the times are parsed to datetimes, and both are
passed to the service verbatim -- its refusal of an end at or
before the start, or of a missing staff member, stays the
single source of truth and surfaces here as ``CommandError``.
This command adds no break logic of its own, so command and
service can never disagree. ``--paid`` marks the break as on
the clock (payroll-relevant); it defaults to unpaid.
Backend only -- no views, templates, or UI.
"""
import argparse
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from bookings.breaks import add_break, validate_add_break
from saloncore.models import Salon
from team.models import StaffMember


def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


def _coerce_datetime(value, label):
    if value is None or isinstance(value, datetime.datetime):
        return value
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected ISO-8601."
        ) from exc


class Command(BaseCommand):
    help = "Add a break for one staff member."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", required=True, type=int,
            help="Id of the staff member taking the break.")
        parser.add_argument(
            "--salon-id", type=int, default=None,
            help="Optional id of the salon the staff member "
                 "must belong to.")
        parser.add_argument(
            "--starts-at", "--start", dest="starts_at",
            type=_parse_datetime, required=True,
            help="When the break starts, ISO-8601.")
        parser.add_argument(
            "--ends-at", "--end", dest="ends_at",
            type=_parse_datetime, required=True,
            help="When the break ends, ISO-8601.")
        parser.add_argument(
            "--paid", dest="paid", action="store_true",
            default=False,
            help="Mark the break as paid (on the clock).")
        parser.add_argument(
            "--unpaid", dest="paid", action="store_false",
            help="Mark the break as unpaid (the default).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate with the service's "
                 "validate-only helper, print the break that "
                 "would be created, and write nothing.")

    def handle(self, *args, **options):
        staff_member_id = options.get("staff_member_id")
        if staff_member_id is None:
            raise CommandError("Provide --staff-member-id.")
        starts_at = _coerce_datetime(
            options.get("starts_at") or options.get("start"),
            "starts-at")
        ends_at = _coerce_datetime(
            options.get("ends_at") or options.get("end"), "ends-at")
        if starts_at is None:
            raise CommandError("Provide --starts-at.")
        if ends_at is None:
            raise CommandError("Provide --ends-at.")
        paid = bool(options.get("paid"))
        salon_id = options.get("salon_id")
        salon = None
        if salon_id is not None:
            try:
                salon = Salon.objects.get(pk=salon_id)
            except Salon.DoesNotExist:
                raise CommandError(
                    f"No salon with id {salon_id}.") from None
        qs = StaffMember.objects.all()
        if salon is not None:
            qs = qs.filter(salon=salon)
        try:
            staff_member = qs.get(pk=staff_member_id)
        except StaffMember.DoesNotExist:
            if salon is not None:
                raise CommandError(
                    f"No staff member with id {staff_member_id} "
                    f"in salon {salon.pk}.") from None
            raise CommandError(
                f"No staff member with id {staff_member_id}.") from None
        if options.get("dry_run"):
            try:
                start, end, is_paid = validate_add_break(
                    staff_member, start=starts_at, end=ends_at,
                    paid=paid)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would create break for staff member "
                f"{staff_member.pk} ({staff_member}): "
                f"start={start.isoformat()} end={end.isoformat()} "
                f"paid={is_paid} -- no break written.")
            return
        try:
            created = add_break(
                staff_member, start=starts_at, end=ends_at, paid=paid)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Added break {created.pk} for staff member "
            f"{staff_member.pk} ({staff_member}): "
            f"start={created.start.isoformat()} "
            f"end={created.end.isoformat()} paid={created.paid}")
