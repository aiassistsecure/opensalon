"""Marketing campaign audience selection (Marketing M1).

Pure service module -- no views, no UI, and no sending. A campaign
is draft-only (see ``messaging.models.Campaign``); this module only
answers "who would this campaign reach?" from the one source of
truth for consent, ``clients.Client``:

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

from .models import Campaign

__all__ = [
    "CampaignAudience",
    "audience_count",
    "audience_for",
    "audience_queryset",
    "audience_summary",
    "campaign_audience",
    "count_audience",
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
