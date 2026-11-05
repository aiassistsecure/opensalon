"""Export one staff member's roster availability for one day as CSV or JSON.

Usage:
    python manage.py export_roster_availability --salon-id ID
        --staff-member-id ID --date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`team.availability_export` services: the salon is
resolved by id, the staff member is resolved by id scoped to
that salon, the date is parsed to a ``datetime.date`` object,
and the staff member and date are passed to the service
verbatim -- for ``--format csv`` (the default) it delegates
verbatim to
:func:`team.availability_export.export_roster_availability_csv`,
so CSV output is byte-identical to before; for
``--format json`` it serialises the SAME dict rows from
:func:`team.availability_export.export_roster_availability`
with the same arguments via ``DjangoJSONEncoder``, so the two
formats can never disagree -- one source of truth. The text
is written unchanged, to ``--output`` when given and to
stdout otherwise. This command adds no export logic of its
own.

This is NOT the salon-roster export: it delegates to
``export_roster_availability_csv(staff_member, day)`` /
``export_roster_availability(staff_member, day)`` (one
member), never to ``export_availability_csv`` /
``export_salon_roster_csv`` (the whole salon roster).

Every filter composes with both formats. An unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs).

Invalid input -- an unknown salon, an unknown staff member
(or one from another salon), or an unparseable date -- raises
``CommandError``. The date means one whole local day in the
salon's timezone, exactly as the service defines it. Backend
only -- no views, templates, or UI. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.availability_export import (
    export_roster_availability,
    export_roster_availability_csv,
)
from team.models import StaffMember

_FORMATS = ("json", "csv")


def _parse_date(value, label):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


def _pk(value):
    return getattr(value, "pk", value)


class Command(BaseCommand):
    help = "Export one staff member's roster availability for one day as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose staff member to export.")
        parser.add_argument(
            "--staff-member-id", "--staff-member", "--staff-id",
            "--staff", dest="staff_member_id", required=True, type=int,
            help="Id of the staff member whose availability to export.")
        parser.add_argument(
            "--date", "--day", dest="date", required=True,
            help="Day to export, YYYY-MM-DD.")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        salon_id = _pk(options.get("salon_id"))
        # Fallbacks for alternate kwarg dests used by callers.
        staff_raw = options.get("staff_member_id")
        if staff_raw is None:
            for key in ("staff_id", "staff_member", "staff"):
                if options.get(key) is not None:
                    staff_raw = options[key]
                    break
        staff_id = _pk(staff_raw)
        try:
            salon = Salon.objects.get(pk=salon_id)
        except (Salon.DoesNotExist, TypeError, ValueError):
            raise CommandError(
                f"No salon with id {salon_id}.") from None

        if staff_id is None:
            raise CommandError("A --staff-member-id is required.")
        try:
            staff_member = StaffMember.objects.get(
                pk=staff_id, salon=salon)
        except (StaffMember.DoesNotExist, TypeError, ValueError):
            raise CommandError(
                f"No staff member with id {staff_id}.") from None

        day = _parse_date(options.get("date"), "date")
        try:
            if fmt == "json":
                rows = export_roster_availability(staff_member, day)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_roster_availability_csv(staff_member, day)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: "
                    f"{exc}") from exc
        else:
            self.stdout.write(text, ending="")
