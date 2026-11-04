"""Export one salon's campaigns verbatim as CSV.

Usage:
    python manage.py export_campaigns --salon-id ID
        [--status STATUS] [--output PATH]

Thin wrapper around
:func:`messaging.campaign_export.export_campaigns_csv`:
the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. This
command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.
Rows carry every stored campaign field, including ``body``
and ``updated_at``.

An unknown salon raises ``CommandError``, as does an
unwritable ``--output`` path. Backend only -- no views,
templates, or UI. Read-only; nothing is sent or dispatched.
Core stays provider-agnostic -- no provider SDK, field, or
name appears here.
"""
from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_export import export_campaigns_csv
from saloncore.models import Salon


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
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        text = export_campaigns_csv(
            salon, status=options.get("status"))

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
