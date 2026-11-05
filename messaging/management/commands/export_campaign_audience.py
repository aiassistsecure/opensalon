"""Export one campaign's audience as CSV or JSON.

Usage:
    python manage.py export_campaign_audience --campaign-id ID
        --salon-id ID [--format json|csv] [--output PATH]

Thin wrapper around
:func:`messaging.campaign_audience_export.export_campaign_audience_csv`:
the salon is resolved by id, the campaign is resolved by id
within that salon (the resolution ``discard_campaign`` uses for
its campaign, salon-scoped as every export command is), and the
service's CSV text is written unchanged, to ``--output`` when
given and to stdout otherwise. For ``--format csv`` (the
default) that CSV output is exactly as before, byte-identical;
for ``--format json`` the same campaign is passed to the dict
service
:func:`messaging.campaign_audience_export.export_campaign_audience`
(beside its CSV twin) and its rows are serialised as JSON, so
the two formats can never disagree. This command adds no export
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
import json

from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_audience_export import (
    export_campaign_audience,
    export_campaign_audience_csv,
)
from messaging.models import Campaign
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = (
        "Export one campaign's audience (opted-in clients) "
        "as CSV (default) or JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id", required=True, type=int,
            help="Id of the campaign whose audience to export.")
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon that owns the campaign.")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).")

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
        try:
            campaign = Campaign.objects.get(
                pk=options["campaign_id"], salon=salon)
        except Campaign.DoesNotExist:
            raise CommandError(
                f"No campaign with id {options['campaign_id']} "
                f"for salon {salon.pk}.") from None

        if fmt == "json":
            rows = export_campaign_audience(campaign)
            text = json.dumps(rows, indent=2) + "\n"
        else:
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
