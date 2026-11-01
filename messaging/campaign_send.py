"""Marketing campaign send execution (Marketing M2).

Sends a saved draft :class:`~messaging.models.Campaign` to exactly
its audience, reusing the existing dispatch layer -- nothing here
reinvents transport:

- SMS goes through the configured provider-agnostic adapter
  (``messaging.adapters.get_sms_adapter``), exactly as SMS
  reminders do; no provider SDK, field, or name appears here.
- Email goes through Django's standard mail framework over one
  connection from ``get_connection()`` -- the salon's own
  ``EMAIL_*`` SMTP settings and ``DEFAULT_FROM_EMAIL`` -- exactly
  as email reminders do.

Consent discipline: the audience is RE-RESOLVED at send time via
``messaging.campaigns.audience_queryset`` (never a snapshot taken
at preview/draft time), so a client who opted out after a preview
is excluded, and each recipient's per-channel opt-in flag is
checked again immediately before their send. One
``CampaignSend`` row is recorded per recipient actually sent to.

Lifecycle: only a draft campaign may send. Sending transitions
the campaign to ``sent`` with a ``sent_at`` timestamp; a non-draft
campaign refuses (re-send raises ``ValidationError``).
"""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from .adapters import get_sms_adapter
from .campaigns import audience_queryset
from .models import Campaign, CampaignSend

__all__ = ["CampaignSendSummary", "send_campaign"]

_OPT_IN_FIELD = {
    Campaign.Channel.SMS: "sms_opt_in",
    Campaign.Channel.EMAIL: "email_opt_in",
}


@dataclass
class CampaignSendSummary:
    """Counts + recipient ids of one campaign send run."""

    campaign_id: int = None
    channel: str = ""
    sent: int = 0
    skipped_missing_contact: int = 0
    skipped_send_failed: int = 0
    sent_client_ids: list = field(default_factory=list)

    @property
    def skipped(self):
        return self.skipped_missing_contact + self.skipped_send_failed


def _send_sms(campaign, recipients, summary, adapter):
    adapter = adapter or get_sms_adapter()
    for client in recipients:
        if not client.sms_opt_in:  # re-checked at send time
            continue
        if not client.phone:
            summary.skipped_missing_contact += 1
            continue
        result = adapter.send_sms(client.phone, campaign.body)
        if not result.success:
            summary.skipped_send_failed += 1
            continue
        CampaignSend.record(campaign, client, detail=result.reference)
        summary.sent += 1
        summary.sent_client_ids.append(client.id)


def _send_email(campaign, recipients, summary):
    connection = get_connection()
    messages, pending = [], []
    for client in recipients:
        if not client.email_opt_in:  # re-checked at send time
            continue
        if not client.email:
            summary.skipped_missing_contact += 1
            continue
        messages.append(EmailMessage(
            subject=campaign.subject, body=campaign.body,
            from_email=None,  # Django uses DEFAULT_FROM_EMAIL
            to=[client.email], connection=connection,
        ))
        pending.append(client)
    sent_count = (connection.send_messages(messages) or 0) if messages else 0
    for index, client in enumerate(pending):
        if index < sent_count:
            CampaignSend.record(campaign, client)
            summary.sent += 1
            summary.sent_client_ids.append(client.id)
        else:
            summary.skipped_send_failed += 1


def send_campaign(campaign, adapter=None, now=None):
    """Send draft ``campaign`` to its freshly resolved audience.

    Returns a :class:`CampaignSendSummary`. Raises
    ``ValidationError`` for an unsaved campaign or any non-draft
    campaign (re-send is refused). ``adapter`` overrides the
    configured SMS adapter (SMS channel only); ``now`` overrides
    the ``sent_at`` timestamp (defaults to ``timezone.now()``).
    """
    if not isinstance(campaign, Campaign) or campaign.pk is None:
        raise ValidationError("campaign must be a saved Campaign instance.")
    # Re-read the persisted status so a stale in-memory copy that
    # was already sent cannot send twice.
    status = (
        Campaign.objects.filter(pk=campaign.pk)
        .values_list("status", flat=True)
        .first()
    )
    if status is None:
        raise ValidationError("campaign must be a saved Campaign instance.")
    if status != Campaign.Status.DRAFT:
        raise ValidationError(
            {"status": "Only a draft campaign can be sent; re-send is refused."}
        )
    campaign.status = status
    # Re-resolve at send time -- never a preview snapshot -- so an
    # opt-out recorded after drafting/preview excludes the client.
    recipients = list(audience_queryset(campaign))
    summary = CampaignSendSummary(
        campaign_id=campaign.pk, channel=campaign.channel
    )
    if campaign.channel == Campaign.Channel.SMS:
        _send_sms(campaign, recipients, summary, adapter)
    elif campaign.channel == Campaign.Channel.EMAIL:
        _send_email(campaign, recipients, summary)
    else:
        raise ValidationError(
            {"channel": f"Unknown campaign channel: {campaign.channel!r}."}
        )
    campaign.status = Campaign.Status.SENT
    campaign.sent_at = now or timezone.now()
    campaign.save(update_fields=["status", "sent_at", "updated_at"])
    return summary
