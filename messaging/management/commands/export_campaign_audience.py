"""Export one campaign's audience as CSV.

Usage:
    python manage.py export_campaign_audience --campaign-id ID
        --salon-id ID [--output PATH]

Thin wrapper around
:func:`messaging.campaign_audience_export.export_campaign_audience_csv`:
the salon is resolved by id, the campaign is resolved by id
within that salon (the resolution ``discard_campaign`` uses for
its campaign, salon-scoped as every export command is), and the
service's CSV text is written unchanged, to ``--output`` when
given and to stdout otherwise. This command adds no export
logic of its own, so command and service output can never
disagree -- one source of truth. Rows are the opted-in, active
clients of the salon that the campaign would reach, in the
audience service's own order: the list behind the audience
counts the create / discard / send campaign commands print.

An unknown salon raises ``CommandError``, as does a campaign
id that does not resolve inside that salon and an unwritable
``--output`` path. Backend only -- no views, templates, or UI.
Read-only; nothing is sent or dispatched. Core stays
provider-agnostic -- no provider SDK, field, or name appears
here.
"""
from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_audience_export import (
    export_campaign_audience_csv,
)
from messaging.models import Campaign
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export one campaign's audience (opted-in clients) as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id", required=True, type=int,
            help="Id of the campaign whose audience to export.")
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon that owns the campaign.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        try:
            campaign = Campaign.objects.get(
                pk=options["campaign_id"], salon=salon)
        except Campaign.DoesNotExist:
            raise CommandError(
                f"No campaign with id {options['campaign_id']} "
                f"for salon {salon.pk}.") from None

        text = export_campaign_audience_csv(campaign)

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
