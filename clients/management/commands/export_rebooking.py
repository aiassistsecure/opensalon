"""Export a salon's rebooking candidates as CSV or JSON.

Usage:
    python manage.py export_rebooking --salon-id ID
        [--reference-date YYYY-MM-DD] [--lookback-days N]
        [--window-days N] [--format json|csv] [--output PATH]

Thin wrapper around ``clients.rebooking_export.export_rebooking_csv``
and its dict source ``clients.rebooking_export.export_rebooking_candidates``
-- those services are the one source of truth for the rebooking
export shape; this command only resolves the salon, delegates
verbatim, and routes the text it returns to the ``--output``
file when given or to stdout otherwise. For ``--format csv``
(the default) the CSV text is written unchanged, exactly as
before; for ``--format json`` the same arguments are passed to
the dict service and its rows are serialised as JSON, so the
two formats can never disagree. It never reimplements querying.
``--reference-date``, ``--lookback-days`` and ``--window-days``
are passed through to the service unchanged, with the service's
own defaults when omitted.

Invalid input -- an unknown salon, an unknown ``--format``, or
a service error -- raises ``CommandError``, as does an
unwritable ``--output`` path.

Backend only: no views, templates, or UI. No provider concepts.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from clients.rebooking import DEFAULT_LOOKBACK_DAYS
from clients.rebooking_export import (
    export_rebooking_candidates,
    export_rebooking_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
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
            f"Invalid reference date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's rebooking candidates as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose rebooking candidates to export.",
        )
        parser.add_argument(
            "--reference-date", dest="reference_date", default=None,
            help="Reference date, YYYY-MM-DD "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--lookback-days", dest="lookback_days", type=int,
            default=DEFAULT_LOOKBACK_DAYS,
            help="Lookback window in days "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--window-days", dest="window_days", type=int, default=None,
            help="Window in days; when given, takes precedence over "
                 "--lookback-days, exactly as in the service.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        reference_date = _parse_date(options.get("reference_date"))
        lookback_days = options.get("lookback_days")
        if lookback_days is None:
            lookback_days = DEFAULT_LOOKBACK_DAYS

        try:
            if fmt == "json":
                rows = export_rebooking_candidates(
                    salon, reference_date=reference_date,
                    lookback_days=lookback_days,
                    window_days=options.get("window_days"),
                )
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_rebooking_csv(
                    salon, reference_date=reference_date,
                    lookback_days=lookback_days,
                    window_days=options.get("window_days"),
                )
        except Exception as exc:
            raise CommandError(
                f"Rebooking export failed: {exc}"
            ) from exc

        if options["output"]:
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
