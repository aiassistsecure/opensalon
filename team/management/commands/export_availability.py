"""Export one salon's roster availability for one day as CSV or JSON.

Usage:
    python manage.py export_availability --salon-id ID
        --date YYYY-MM-DD [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`team.availability_export` services: the salon is
resolved by id, the date is parsed to a ``datetime.date``
object, and both are passed to the service verbatim -- for
``--format csv`` (the default) it delegates verbatim to
:func:`team.availability_export.export_availability_csv`,
so CSV output is byte-identical to before; for
``--format json`` it serialises the SAME dict rows from
:func:`team.availability_export.export_availability`
with the same arguments via ``DjangoJSONEncoder``, so the
two formats can never disagree -- one source of truth.
The text is written unchanged, to ``--output`` when given
and to stdout otherwise. This command adds no export logic
of its own.

Note: ``export_availability`` is the dict-list service,
defined as ``export_salon_roster`` in
:mod:`team.availability_export` and bound at that module's
tail as ``export_availability = export_salon_roster``;
this command imports it under that existing name -- no
service file is changed and no new alias is added.

Every existing option composes with both formats. An
unknown ``--format`` raises ``CommandError`` (argparse
``choices`` reject it on the CLI; the explicit check
covers ``call_command`` kwargs).

Invalid input -- an unknown salon or an unparseable
date -- raises ``CommandError``. The date means one whole
local day in the salon's timezone, exactly as the service
defines it. Backend only -- no views, templates, or UI.
Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.availability_export import (
    export_availability,
    export_availability_csv,
)

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
    help = "Export one salon's roster availability for one day as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose availability to export.")
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
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        day = _parse_date(options["date"], "date")
        try:
            if fmt == "json":
                rows = export_availability(salon, day)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_availability_csv(salon, day)
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
