"""Discard one draft marketing campaign.

Usage:
    python manage.py discard_campaign --campaign-id ID [--dry-run]
        [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(campaign id, name, channel, status -- ``discarded`` after a
real run, the campaign's draft status on ``--dry-run`` --
audience count, and ``dry_run``); no prose lines are printed
in json mode. The default ``--format text`` output is
unchanged.

Thin wrapper around
:func:`messaging.campaigns.discard_campaign`: the campaign
is resolved by id and passed to the service verbatim -- the
real run adds no deletion logic of its own, so command and
service can never disagree -- one source of truth. The
service deletes a DRAFT campaign row only and refuses any
non-draft campaign (surfaced here as ``CommandError``): a
sent campaign and its ``CampaignSend`` history are never
touched.

With ``--dry-run`` nothing is deleted: the draft is
resolved, its audience is counted exactly as the service
layer resolves it (``messaging.campaigns.audience_count``),
and that count is printed. Output is counts only: no client
names or contact details are printed. An unknown campaign
id raises ``CommandError``, as does a non-draft campaign
on either path. Core stays provider-agnostic -- no provider
SDK, field, or name appears here.
"""
import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from messaging.campaigns import audience_count, discard_campaign
from messaging.models import Campaign


def _as_command_error(exc):
    try:
        messages = exc.messages
    except AttributeError:
        messages = [str(exc)]
    return CommandError("; ".join(messages))


class Command(BaseCommand):
    help = "Discard a draft marketing campaign (or preview with --dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id", required=True, type=int,
            help="Id of the draft campaign to discard.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print audience count, delete nothing.")
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        try:
            campaign = Campaign.objects.get(pk=options["campaign_id"])
        except Campaign.DoesNotExist:
            raise CommandError(
                f"No campaign with id {options['campaign_id']}.") from None
        if campaign.status != Campaign.Status.DRAFT:
            raise CommandError(
                "Only a draft campaign can be discarded; "
                f"campaign {campaign.pk} is {campaign.status}.")
        if options["dry_run"]:
            count = audience_count(campaign)
            if fmt == "json":
                self.stdout.write(json.dumps(dict(
                    id=campaign.pk,
                    name=campaign.name,
                    channel=campaign.channel,
                    status=campaign.status,
                    audience=count,
                    dry_run=True)))
                return
            self.stdout.write(
                f"Dry run: Campaign {campaign.pk} ({campaign.channel}): "
                f"audience {count} -- no campaign deleted.")
            return
        try:
            summary = discard_campaign(campaign)
        except ValidationError as exc:
            raise _as_command_error(exc) from exc
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                id=summary.campaign_id,
                name=summary.name,
                channel=summary.channel,
                status="discarded",
                audience=summary.audience_count,
                dry_run=False)))
            return
        self.stdout.write(
            f"Discarded draft campaign {summary.campaign_id} "
            f"({summary.channel}): {summary.name!r} "
            f"audience {summary.audience_count}.")
