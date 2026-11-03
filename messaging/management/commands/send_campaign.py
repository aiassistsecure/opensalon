"""Send one saved draft marketing campaign.

Usage:
    python manage.py send_campaign --campaign-id ID [--dry-run]

Thin wrapper around
:func:`messaging.campaign_send.send_campaign`: the campaign
is resolved by id and passed to the service verbatim -- the
real run adds no sending logic of its own, so command and
service can never disagree -- one source of truth. The
service re-resolves the audience at send time, re-checks
each recipient's per-channel opt-in, records one
``CampaignSend`` row per successful dispatch, and refuses
any non-draft campaign (re-send raises, surfaced here as
``CommandError``).

With ``--dry-run`` nothing is sent, no ``CampaignSend``
rows are written, and the campaign stays a draft: the
audience is re-resolved exactly as the real send resolves
it (``messaging.campaigns.audience_queryset`` -- the same
function the service uses), and counts are printed by
channel: would-send (in the audience with contact details
on the campaign's channel), skipped by opt-in (active
clients of the salon not opted in on that channel, hence
excluded from the audience), and skipped missing contact
(in the audience but with no phone/email for the channel).

Output is counts only: no client names or contact details
are printed. An unknown campaign id raises ``CommandError``,
as does a non-draft campaign on either path. Core stays
provider-agnostic -- no provider SDK, field, or name
appears here.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from messaging.campaign_send import send_campaign
from messaging.campaigns import audience_queryset
from messaging.models import Campaign

_OPT_IN_FIELD = {
    Campaign.Channel.SMS: "sms_opt_in",
    Campaign.Channel.EMAIL: "email_opt_in",
}
_CONTACT_FIELD = {
    Campaign.Channel.SMS: "phone",
    Campaign.Channel.EMAIL: "email",
}


def _preview_counts(campaign):
    """Dry-run counts for ``campaign``, resolved like a real send."""
    opt_in_field = _OPT_IN_FIELD[campaign.channel]
    contact_field = _CONTACT_FIELD[campaign.channel]
    skipped_opt_in = Client.objects.filter(
        salon_id=campaign.salon_id, active=True,
        **{opt_in_field: False},
    ).count()
    audience = list(audience_queryset(campaign))
    would_send = sum(
        1 for client in audience if getattr(client, contact_field)
    )
    return would_send, skipped_opt_in, len(audience) - would_send


class Command(BaseCommand):
    help = "Send a draft marketing campaign (or preview with --dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id", required=True, type=int,
            help="Id of the draft campaign to send.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print counts, send nothing.")

    def handle(self, *args, **options):
        try:
            campaign = Campaign.objects.get(pk=options["campaign_id"])
        except Campaign.DoesNotExist:
            raise CommandError(
                f"No campaign with id {options['campaign_id']}.") from None
        if campaign.status != Campaign.Status.DRAFT:
            raise CommandError(
                "Only a draft campaign can be sent; "
                f"campaign {campaign.pk} is {campaign.status}.")
        if options["dry_run"]:
            would_send, skipped_opt_in, skipped_missing = (
                _preview_counts(campaign))
            self.stdout.write(
                f"Dry run: Campaign {campaign.pk} ({campaign.channel}): "
                f"{would_send} would send, "
                f"{skipped_opt_in} skipped by opt-in, "
                f"{skipped_missing} skipped missing contact.")
            return
        try:
            summary = send_campaign(campaign)
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Campaign {summary.campaign_id} ({summary.channel}): "
            f"{summary.sent} sent, {summary.skipped} skipped "
            f"({summary.skipped_missing_contact} skipped missing contact, "
            f"{summary.skipped_send_failed} skipped send failed).")
