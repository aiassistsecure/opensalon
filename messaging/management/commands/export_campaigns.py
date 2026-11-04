"""Export one salon's campaigns verbatim as CSV.

Usage:
    python manage.py export_campaigns --salon-id ID
        [--status STATUS] [--channel CHANNEL]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Thin wrapper around
:func:`messaging.campaign_export.export_campaigns_csv`:
the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. This
command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.
Rows carry every stored campaign field, including ``body``
and ``updated_at``.

With ``--start-date`` / ``--end-date`` (spelled exactly as
the Family XI ledger commands spell them; ``--start`` /
``--date-from`` and ``--end`` / ``--date-to`` accepted as
aliases) the export is narrowed to campaigns whose
``created_at`` falls in that window: the dates are parsed
to ``datetime.date`` objects and passed to the service as
its optional ``start_date`` / ``end_date`` arguments, so a
date start means the start of that day and a date end
includes the whole end day. Each bound is optional; without
either, the command exports every campaign, exactly as
before. The window composes with ``--status`` and
``--channel`` (window AND status AND channel).

An unknown salon, an unparseable date, or an unwritable
``--output`` path raises ``CommandError``. Backend only --
no views, templates, or UI. Read-only; nothing is sent or
dispatched. Core stays provider-agnostic -- no provider
SDK, field, or name appears here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_export import export_campaigns_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
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
    help = "Export one salon's campaigns verbatim as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose campaigns to export.")
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Campaign status value to filter by.")
        parser.add_argument(
            "--channel", dest="channel", default=None,
            help="Campaign channel value to filter by.")
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            type=_parse_date, default=None,
            help="First day of the window on created_at, "
                 "YYYY-MM-DD (inclusive; default: unbounded).")
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            type=_parse_date, default=None,
            help="Last day of the window on created_at, "
                 "YYYY-MM-DD (inclusive; default: unbounded).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        start_date = _coerce_date(options.get("start_date"), "start date")
        end_date = _coerce_date(options.get("end_date"), "end date")
        try:
            text = export_campaigns_csv(
                salon, status=options.get("status"),
                channel=options.get("channel"),
                start_date=start_date, end_date=end_date)
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
