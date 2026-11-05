"""Export one salon's upcoming online bookings as CSV or JSON.

Usage:
    python manage.py export_online_upcoming --salon-id ID
        [--now ISO-DATETIME] [--start ISO-DATETIME]
        [--days N] [--horizon-days N]
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`onlinebooking.export_upcoming` services: for
``--format csv`` (the default) this command delegates verbatim
to ``export_upcoming_csv(salon, now=now, days=days, start=start,
horizon_days=horizon_days)``; for ``--format json`` the same
arguments are passed to the dict service ``export_upcoming``
(beside its CSV twin) and its rows are serialised as JSON via
``DjangoJSONEncoder``. The command adds no export logic of its
own, so the command output and the service output can never
disagree -- one source of truth, and the CSV output is exactly
as before, byte-identical.

The distinct name ``export_online_upcoming`` is deliberate:
the global name ``export_upcoming`` is already owned by a
``bookings`` management command.

All optional arguments default to ``None`` exactly as the
service defines them: no ``--now`` means the service's own
default reference instant, ``--start`` is the service's alias
for ``now`` (used only when ``now`` is not given), no
``--days`` means no upper bound, and ``--horizon-days`` is
the service's alias for ``days`` (and wins when given).

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, an unparseable
``--now`` / ``--start``, a non-integer ``--days`` /
``--horizon-days``, or an unknown format -- raises
``CommandError``, as do service errors and unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from onlinebooking.export_upcoming import export_upcoming, export_upcoming_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_now(value, salon, label):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    tz = _tz_for(salon)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=tz)
    text = str(value).strip()
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            day = datetime.date.fromisoformat(text)
        except ValueError as exc:
            raise CommandError(
                f"Invalid {label} {value!r}; expected an ISO datetime."
            ) from exc
        return datetime.datetime.combine(
            day, datetime.time.min, tzinfo=tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _coerce_days(value, label):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected an integer."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's upcoming online bookings as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose upcoming online bookings "
                 "to export.")
        parser.add_argument(
            "--now", dest="now", default=None,
            help="Reference instant for upcoming, ISO datetime "
                 "(default: the service's own default).")
        parser.add_argument(
            "--start", dest="start", default=None,
            help="Alias for --now, ISO datetime, exactly as the "
                 "service defines it (used only when --now is "
                 "not given).")
        parser.add_argument(
            "--days", dest="days", default=None, type=int,
            help="Optional horizon in days (default: no upper "
                 "bound, as the service defines it).")
        parser.add_argument(
            "--horizon-days", dest="horizon_days", default=None,
            type=int,
            help="Alias for --days, exactly as the service "
                 "defines it (wins when given).")
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
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        now = _parse_now(options.get("now"), salon, "now")
        start = _parse_now(options.get("start"), salon, "start")
        days = _coerce_days(options.get("days"), "days")
        horizon_days = _coerce_days(
            options.get("horizon_days"), "horizon-days")

        try:
            if fmt == "json":
                rows = export_upcoming(
                    salon, now=now, days=days, start=start,
                    horizon_days=horizon_days)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_upcoming_csv(
                    salon, now=now, days=days, start=start,
                    horizon_days=horizon_days)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options["output"]:
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
