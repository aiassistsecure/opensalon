"""Export a salon's receipts as JSON.

Usage:
    python manage.py export_receipt --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Thin wrapper around the existing
:func:`checkout.receipt_export.export_receipts` service:
the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its rows are serialized as JSON (the service
builds them to be JSON-serializable and has no CSV variant;
JSON serialization of its result, as in the
``export_clients`` command, is the only rendering here) and
written unchanged, to ``--output`` when given and to stdout
otherwise. Both dates are optional exactly as the service
defines them, so omitting them exports every receipt for
the salon. This command adds no export logic of its own, so
command and service output can never disagree -- one source
of truth.

Invalid input -- an unparseable date or a reversed range --
raises ``CommandError``, as do service errors. Dates mean
whole local days in the salon's timezone, inclusive at both
ends, exactly as the service defines them. Read-only. Core
stays provider-agnostic -- no payment-provider SDK, field,
or name appears here.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from checkout.receipt_export import export_receipts
from saloncore.models import Salon


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
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's receipts as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose receipts to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the JSON to (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        if start is not None and end is not None and end < start:
            raise CommandError(
                f"End date {end.isoformat()} is before start date "
                f"{start.isoformat()}."
            )
        try:
            rows = export_receipts(start, end, salon=salon)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        text = json.dumps(rows, indent=2) + "\n"
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
