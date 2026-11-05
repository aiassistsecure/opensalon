"""Export reminder message history as CSV or JSON.

Usage:
    python manage.py export_message_history
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--salon-id ID] [--format json|csv] [--output PATH]

Thin wrapper around the existing
:func:`messaging.history_export.export_history_summary_csv`
and :func:`messaging.history_export.export_history_summary`
services: the dates are parsed to ``datetime.date`` objects and
passed to the service verbatim as ``(start, end)``. For
``--format csv`` (the default) its CSV text is written unchanged,
to ``--output`` when given and to stdout otherwise; for
``--format json`` the same dict rows are serialised as JSON via
``DjangoJSONEncoder``, so the two formats can never disagree --
one source of truth. The service derives counts from the
``ReminderSend`` log over an inclusive date range; an optional
``--salon-id`` scopes those counts to one salon (resolved by
id and passed to the service, which matches sends through
``client__salon``). Omitting ``--salon-id`` keeps the previous
all-salons behaviour, byte-identical.

Invalid input -- an unparseable date, a reversed range, an
unknown format, or an unknown salon -- raises ``CommandError``.
Dates mean whole local days, inclusive at both ends, exactly as
the service defines them. Read-only. Core stays
provider-agnostic -- no provider SDK, field, or name appears here.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from messaging.history_export import (
    export_history_summary,
    export_history_summary_csv,
)
from saloncore.models import Salon

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


class Command(BaseCommand):
    help = "Export reminder message history as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date", dest="start_date", required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", dest="end_date", required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--salon-id", dest="salon_id", type=int, default=None,
            help="Id of the salon to scope the export to "
                 "(default: all salons).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv",
            choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        salon = None
        if options.get("salon_id") is not None:
            try:
                salon = Salon.objects.get(pk=options["salon_id"])
            except Salon.DoesNotExist as exc:
                raise CommandError(
                    f"No salon with id {options['salon_id']}."
                ) from exc
        kwargs = {} if salon is None else {"salon": salon}
        try:
            if fmt == "json":
                rows = export_history_summary(start, end, **kwargs)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_history_summary_csv(start, end, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
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
