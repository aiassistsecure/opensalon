"""Export one salon's prior (same-weekday) day load as CSV or JSON.

Usage: python manage.py export_prior_day_load --salon-id ID
    --date YYYY-MM-DD [--format json|csv] [--output PATH]
Thin wrapper around :mod:`bookings.prior_day_load_export`;
unknown salon, bad/missing date, or service error -> CommandError.
For ``--format csv`` (the default) the CSV output is exactly as
before, byte-identical; for ``--format json`` the same arguments
are passed to
:func:`bookings.prior_day_load_export.export_prior_day_load_dict`
and its wrapper dict is serialised verbatim as JSON via
``DjangoJSONEncoder`` (not the bare rows list).
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.prior_day_load_export import (
    export_prior_day_load_csv,
    export_prior_day_load_dict,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value, label):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's prior (same-weekday) day load comparison as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--date", "--day", dest="date", default=None,
                            help="Day to report, YYYY-MM-DD.")
        parser.add_argument("--start-date", dest="start_date", default=None,
                            help="Alias for --date, YYYY-MM-DD.")
        parser.add_argument("--end-date", dest="end_date", default=None,
                            help="Alias for --date, YYYY-MM-DD.")
        parser.add_argument("--format", dest="format", default="csv",
                            choices=_FORMATS,
                            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Path to write the export to (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        raw = (options.get("date") or options.get("start_date")
               or options.get("end_date"))
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        day = _parse_date(raw, "date")
        if day is None:
            raise CommandError("--date is required.")
        try:
            if fmt == "json":
                payload = export_prior_day_load_dict(salon, day)
                text = json.dumps(
                    payload, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_day_load_csv(salon, day)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
