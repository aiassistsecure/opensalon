"""Export one salon's prior-week roster week comparison as CSV or JSON.

Usage: python manage.py export_prior_roster_week --salon-id ID
    --week-start YYYY-MM-DD [--format json|csv] [--output PATH]
Thin wrapper around :mod:`team.prior_roster_week_export`; for
``--format csv`` (the default) it delegates verbatim to the
CSV service, so CSV output is byte-identical to before; for
``--format json`` it serialises the SAME dict rows from the
dict service beside its CSV twin via ``DjangoJSONEncoder``.
Unknown salon, bad / missing dates, or an unknown format
raises ``CommandError`` (argparse ``choices`` reject an
unknown format on the CLI; the explicit check covers
``call_command`` kwargs).
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.prior_roster_week_export import (
    export_prior_roster_week,
    export_prior_roster_week_csv,
)

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
    help = "Export one salon's prior-week roster week comparison as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument(
            "--week-start", "--start-date", "--date", "--start",
            dest="week_start", default=None,
            help="First day of the current week, YYYY-MM-DD (its Monday).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Path to write the export to (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        week_start = _parse_date(options.get("week_start"), "week-start date")
        if week_start is None:
            raise CommandError("--week-start is required.")
        try:
            if fmt == "json":
                rows = export_prior_roster_week(salon, week_start)
                text = json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_roster_week_csv(salon, week_start)
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
