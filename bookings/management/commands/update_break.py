"""Update one break's start, end, or paid flag.

Usage:
    python manage.py update_break --break-id ID
        [--starts-at ISO-8601-DATETIME] [--ends-at ISO-8601-DATETIME]
        [--paid | --unpaid] [--salon-id ID] [--dry-run]

At least one of --starts-at / --ends-at / --paid / --unpaid must
be given; omitted = unchanged. The staff member is NOT
changeable here -- a different member is a different break.

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), and prints the merged break that
WOULD be stored.

Thin wrapper around :func:`bookings.breaks.update_break`: the
break is resolved by id (scoped to the salon via its staff
member when ``--salon-id`` is given, the bookings salon-scoping
convention), the times are parsed to datetimes, and both are
passed to the service verbatim -- its merged-pair end-after-
start and aware-datetime rules stay the single source of truth
and surface here as ``CommandError``. Backend only.
"""
import argparse
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.breaks import update_break, validate_update_break
from bookings.models import Break
from saloncore.models import Salon


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
    help = "Update one break's start, end, or paid flag."

    def add_arguments(self, parser):
        parser.add_argument(
            "--break-id", required=True, type=int,
            help="Id of the break to update.")
        parser.add_argument(
            "--salon-id", type=int, default=None,
            help="Optional id of the salon the break's staff "
                 "member must belong to.")
        parser.add_argument(
            "--starts-at", "--start", dest="starts_at",
            type=_parse_datetime, default=None,
            help="New break start, ISO-8601; omitted = unchanged.")
        parser.add_argument(
            "--ends-at", "--end", dest="ends_at",
            type=_parse_datetime, default=None,
            help="New break end, ISO-8601; omitted = unchanged.")
        parser.add_argument(
            "--paid", dest="paid", action="store_true", default=None,
            help="Mark the break as paid; omitted = unchanged.")
        parser.add_argument(
            "--unpaid", dest="paid", action="store_false",
            default=None,
            help="Mark the break as unpaid; omitted = unchanged.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate with the service's "
                 "validate-only helper, print the merged break "
                 "that would be stored, and write nothing.")

    def handle(self, *args, **options):
        break_id = options.get("break_id")
        if break_id is None:
            raise CommandError("Provide --break-id.")
        starts_at = _coerce_datetime(
            options.get("starts_at") or options.get("start"), "starts-at")
        ends_at = _coerce_datetime(
            options.get("ends_at") or options.get("end"), "ends-at")
        paid = options.get("paid")
        if starts_at is None and ends_at is None and paid is None:
            raise CommandError(
                "At least one field must be given: --starts-at, "
                "--ends-at, --paid, or --unpaid.")
        salon_id = options.get("salon_id")
        salon = None
        if salon_id is not None:
            try:
                salon = Salon.objects.get(pk=salon_id)
            except Salon.DoesNotExist:
                raise CommandError(
                    f"No salon with id {salon_id}.") from None
        qs = Break.objects.all()
        if salon is not None:
            qs = qs.filter(staff_member__salon=salon)
        try:
            break_obj = qs.get(pk=break_id)
        except Break.DoesNotExist:
            if salon is not None:
                raise CommandError(
                    f"No break with id {break_id} "
                    f"in salon {salon.pk}.") from None
            raise CommandError(
                f"No break with id {break_id}.") from None
        if options.get("dry_run"):
            try:
                start, end, is_paid = validate_update_break(
                    break_obj, start=starts_at, end=ends_at, paid=paid)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would update break {break_obj.pk} for "
                f"staff member {break_obj.staff_member_id}: "
                f"start={start.isoformat()} end={end.isoformat()} "
                f"paid={is_paid} -- no break written.")
            return
        try:
            updated = update_break(
                break_obj, start=starts_at, end=ends_at, paid=paid)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Updated break {updated.pk} for staff member "
            f"{updated.staff_member_id}: "
            f"start={updated.start.isoformat()} "
            f"end={updated.end.isoformat()} paid={updated.paid}")
