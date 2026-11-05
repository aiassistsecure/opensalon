"""Export a salon's persistent client record notes as CSV or JSON.

Usage:
    python manage.py export_notes --salon-id ID
        [--client-id ID] [--start-date YYYY-MM-DD]
        [--end-date YYYY-MM-DD] [--format json|csv] [--output PATH]

Thin wrapper around ``clients.note_export`` -- that service is
the one source of truth for the record-note export shape; this
command only resolves the salon, delegates verbatim, and routes
what it returns to the ``--output`` file when given or to
stdout otherwise. It never reimplements serialization or
querying. Only persistent client record notes are exported;
appointment-only notes live in the bookings app and never appear.

For ``--format csv`` (the default) it writes
:func:`clients.note_export.export_notes_csv`'s CSV string,
exactly as before (byte-identical); for ``--format json`` it
serialises the SAME dict rows from
:func:`clients.note_export.export_notes` as JSON.

With ``--client-id`` the export is narrowed to that one client's
record notes: the client is resolved by id within the salon (a
client from another salon, or an unknown id, is a
``CommandError``), and the resolved client is passed to the
service as its optional ``client`` argument. Without
``--client-id`` the command exports the whole salon, exactly as
before.

With ``--start-date`` / ``--end-date`` (spelled as the clients
ledger commands spell them, aliases ``--start`` / ``--date-from``
and ``--end`` / ``--date-to``) the export is narrowed to notes
whose ``created_at`` falls in that window: each date is parsed
to a ``datetime.date`` and passed to the service as its optional
``start`` / ``end`` bound, so a date end includes the whole end
day. Either bound may be given alone (the other stays
unbounded); with neither, the command exports the whole salon,
exactly as before. The window composes with ``--client-id``
(window AND record). An unparseable date is a ``CommandError``.
Both filters compose with ``--format`` exactly as they do for CSV.

Backend only: no views, templates, or UI. No provider concepts.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from clients.note_export import export_notes, export_notes_csv
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
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's persistent client record notes as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose record notes to export.",
        )
        parser.add_argument(
            "--client-id", type=int, default=None,
            help="ID of the client (in the salon) whose record "
                 "notes to export (default: all clients).",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the window, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the window, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
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

        client = None
        if options.get("client_id") is not None:
            try:
                client = Client.objects.get(
                    pk=options["client_id"], salon=salon
                )
            except Client.DoesNotExist:
                raise CommandError(
                    f"No client with id {options['client_id']} "
                    f"for salon {options['salon_id']}."
                ) from None

        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")

        try:
            if fmt == "json":
                rows = export_notes(
                    salon, client=client, start=start_date, end=end_date)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_notes_csv(
                    salon, client=client, start=start_date, end=end_date)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Notes export failed: {exc}") from exc

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
