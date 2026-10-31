"""Export one client's reminder-send history detail as CSV.

Usage:
    python manage.py export_client_history_detail --salon-id ID
        --client-id ID [--limit N] [--output PATH]

Thin wrapper around the existing
:func:`messaging.history_export.export_client_history_csv`
service: the salon and client are resolved by id (mirroring
the bookings ``export_client_history`` command's resolution),
and the client is passed to the service verbatim as
``export_client_history_csv(client, limit=...)`` -- its CSV
text is written unchanged, to ``--output`` when given and to
stdout otherwise. The service is client-scoped (rows come from
the ``ReminderSend`` log for that client), so the salon is
resolved only to validate it exists. A client from another
salon is passed through too: the service exports that client's
sends, exactly as it does directly. This command adds no export
logic of its own -- one source of truth.

This is the per-client detail export (one row per send). It is
distinct from the ``export_client_history`` command owned by
the bookings app, which wraps the appointment-history service
in :mod:`bookings.client_history_export`; the two commands
export different shapes and neither delegates to the other.
Hence the ``_detail`` suffix, following this app's
``export_send_totals_detail`` precedent.

Invalid input -- an unknown salon, an unknown client, or a
service error -- raises ``CommandError``, as does an
unwritable ``--output`` path. Read-only. Core stays
provider-agnostic -- no provider SDK, field, or name appears
here.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from messaging.history_export import export_client_history_csv
from saloncore.models import Salon


def _resolve(model, value, label):
    if value is None or isinstance(value, model):
        return value
    pk = getattr(value, "pk", value)
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected an id."
        ) from exc
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist as exc:
        raise CommandError(f"No {label} with id {pk}.") from exc


def _coerce_limit(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid limit {value!r}; expected an integer."
        ) from exc


def _first(options, *keys):
    for key in keys:
        value = options.get(key)
        if value is not None:
            return value
    return None


class Command(BaseCommand):
    help = "Export one client's reminder-send history detail as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose client history to export.",
        )
        parser.add_argument(
            "--client-id", "--client", dest="client_id",
            type=int, required=True,
            help="Id of the client whose history to export.",
        )
        parser.add_argument(
            "--limit", dest="limit", type=int, default=None,
            help="Maximum rows to export (default: the service's "
                 "own default, the full history).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        salon = _resolve(
            Salon, _first(options, "salon_id", "salon"), "salon")
        if salon is None:
            raise CommandError("A --salon-id is required.")
        client = _resolve(
            Client, _first(options, "client_id", "client"), "client")
        if client is None:
            raise CommandError("A --client-id is required.")
        limit = _coerce_limit(options.get("limit"))
        try:
            text = export_client_history_csv(client, limit=limit)
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
