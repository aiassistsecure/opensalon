"""Marketing campaign creation, discard, and audience selection.

Pure service module -- no views, no UI, and no sending.
:func:`create_campaign` is the one validated path for creating
a campaign: it always creates a DRAFT and never sends anything.
:func:`discard_campaign` is its inverse: it deletes a DRAFT
campaign only and refuses a sent one, whose history is never
touched.
This module also answers "who would this campaign reach?" from
the one source of truth for consent, ``clients.Client``:

- SMS audience: clients of the campaign's salon with
  ``sms_opt_in=True``.
- Email audience: clients of the campaign's salon with
  ``email_opt_in=True``.

The two opt-ins are independent -- one never implies the other --
matching the single-flag rule documented in ``clients.optins``
(the same flag gates marketing and reminders on that channel).
Inactive clients (``active=False``; Client has no separate
archived/banned flag) are excluded on both channels. Clients of
any other salon are never included.
"""
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from clients.models import Client
from saloncore.models import Salon

from .models import Campaign

__all__ = [
    "CampaignAudience",
    "DiscardSummary",
    "audience_count",
    "audience_for",
    "audience_queryset",
    "audience_summary",
    "campaign_audience",
    "count_audience",
    "create_campaign",
    "discard_campaign",
]

_CHANNEL_FIELD = {
    Campaign.Channel.SMS: "sms_opt_in",
    Campaign.Channel.EMAIL: "email_opt_in",
}


def _channel_field(channel):
    try:
        return _CHANNEL_FIELD[channel]
    except (KeyError, TypeError):
        raise ValidationError(
            {"channel": f"Unknown campaign channel: {channel!r}."}
        ) from None


def create_campaign(salon, name, channel, subject="", body=""):
    """Create one DRAFT campaign for ``salon``; never sends.

    The one validated creation path: ``salon`` must be a saved
    Salon, ``name`` and ``body`` must be non-blank, ``channel``
    must be a known campaign channel, and an email campaign
    must carry a non-blank ``subject`` (SMS subjects are stored
    as given and may be blank). Any violation raises
    ``ValidationError`` and nothing is created.
    """
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValidationError("salon must be a saved Salon instance.")
    _channel_field(channel)
    name = (name or "").strip()
    if not name:
        raise ValidationError({"name": "Campaign name must not be empty."})
    body = body or ""
    if not body.strip():
        raise ValidationError({"body": "Campaign body must not be empty."})
    subject = subject or ""
    if channel == Campaign.Channel.EMAIL and not subject.strip():
        raise ValidationError(
            {"subject": "An email campaign must carry a subject."})
    campaign = Campaign(
        salon=salon, name=name, channel=channel,
        subject=subject, body=body, status=Campaign.Status.DRAFT,
    )
    campaign.full_clean()
    campaign.save()
    return campaign


def audience_queryset(campaign):
    """Clients ``campaign`` would reach, in Client's default order.

    Raises ValidationError if ``campaign`` is not a saved Campaign.
    """
    if not isinstance(campaign, Campaign) or campaign.pk is None:
        raise ValidationError("campaign must be a saved Campaign instance.")
    field = _channel_field(campaign.channel)
    return Client.objects.filter(
        salon_id=campaign.salon_id, active=True, **{field: True}
    )


def audience_for(salon, channel):
    """Clients of ``salon`` opted in on ``channel`` (``sms``/``email``)."""
    field = _channel_field(channel)
    return Client.objects.filter(salon=salon, active=True, **{field: True})


def audience_count(campaign):
    """How many clients ``campaign`` would reach on its channel."""
    return audience_queryset(campaign).count()


def count_audience(campaign):
    """Alias for :func:`audience_count`."""
    return audience_count(campaign)


def campaign_audience(campaign):
    """Alias for :func:`audience_queryset`."""
    return audience_queryset(campaign)


@dataclass(frozen=True)
class DiscardSummary:
    """Snapshot of one discarded draft campaign."""

    campaign_id: int = None
    name: str = ""
    channel: str = ""
    audience_count: int = 0


def discard_campaign(campaign):
    """Delete one DRAFT campaign; refuse anything else.

    The inverse of :func:`create_campaign`: the one validated
    path for discarding a campaign that was never sent. Only a
    draft may be discarded -- the persisted status is re-read
    so a stale in-memory copy cannot discard a campaign that
    has since been sent. A sent campaign raises
    ``ValidationError`` and is never touched: sent history,
    including its ``CampaignSend`` rows, is preserved exactly.
    The audience count is resolved before the delete so the
    caller can report what the draft would have reached.
    Returns a :class:`DiscardSummary`.
    """
    if not isinstance(campaign, Campaign) or campaign.pk is None:
        raise ValidationError("campaign must be a saved Campaign instance.")
    status = (
        Campaign.objects.filter(pk=campaign.pk)
        .values_list("status", flat=True)
        .first()
    )
    if status is None:
        raise ValidationError("campaign must be a saved Campaign instance.")
    if status != Campaign.Status.DRAFT:
        raise ValidationError(
            {"status": "Only a draft campaign can be discarded; "
                       "a sent campaign is never deleted."}
        )
    summary = DiscardSummary(
        campaign_id=campaign.pk, name=campaign.name,
        channel=campaign.channel,
        audience_count=audience_count(campaign),
    )
    campaign.delete()
    return summary


@dataclass(frozen=True)
class CampaignAudience:
    """Audience snapshot for one campaign."""

    campaign: Campaign
    channel: str
    count: int
    client_ids: tuple = ()


def audience_summary(campaign):
    """Count + ids of the clients ``campaign`` would reach."""
    qs = audience_queryset(campaign)
    ids = tuple(qs.values_list("id", flat=True))
    return CampaignAudience(
        campaign=campaign, channel=campaign.channel,
        count=len(ids), client_ids=ids,
    )
