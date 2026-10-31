"""Export one salon's rebookable appointments as CSV.

Usage:
    python manage.py export_rebook --salon-id ID
        [--client-id ID] [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.rebook_export.export_rebook_csv`
service: this command delegates verbatim to
``export_rebook_csv(salon, client)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.

The client argument is optional and defaults to ``None``
exactly as the service defines it: no ``--client-id`` means
the salon-wide export (every client of the salon). A client
belonging to a different salon exports nothing, exactly as
the service defines it -- never another salon's bookings,
and no error that confirms the client exists elsewhere.

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon or an unknown client --
raises ``CommandError``, as do service errors and
unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from onlinebooking.rebook_export import export_rebook_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export one salon's rebookable appointments as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose rebookable appointments "
                 "to export.")
        parser.add_argument(
            "--client-id", dest="client_id", default=None, type=int,
            help="Id of the client to export for (default: "
                 "salon-wide, as the service defines it).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        client = None
        if options.get("client_id") is not None:
            try:
                client = Client.objects.get(pk=options["client_id"])
            except Client.DoesNotExist:
                raise CommandError(
                    f"No client with id {options['client_id']}.") from None

        try:
            text = export_rebook_csv(salon, client)
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
