"""Messaging's own persisted records.

Opt-in state still lives on ``clients.Client`` (the one source of
truth) and is never duplicated here. Messaging stores the history
of reminder sends it has actually dispatched (``ReminderSend``),
marketing campaigns (``Campaign``), and one send-log row per
campaign recipient actually dispatched (``CampaignSend``).
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, StrictConstraints


class ReminderSend(models.Model):
    """One successfully dispatched appointment reminder.

    A row is written only on a successful dispatch (see
    ``messaging.email_reminders`` / ``messaging.sms_reminders``,
    which the combined dispatch and send-due paths both run
    through): skipped or failed attempts create no row, exactly
    as they send nothing. ``client`` is denormalised from the
    appointment at send time so history queries need not join
    through appointments that may later change.
    """

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"

    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="reminder_sends"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="reminder_sends"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SENT
    )
    sent_at = models.DateTimeField(default=timezone.now)
    # Free-form send detail: the adapter reference for SMS, blank
    # for email. Never a provider name or provider-specific field.
    detail = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-sent_at", "-id"]

    def __str__(self):
        return (
            f"{self.channel} reminder for appointment "
            f"{self.appointment_id} ({self.status} at {self.sent_at})"
        )

    @classmethod
    def record(cls, appointment, channel, detail=""):
        """Log one successful dispatch for ``appointment``."""
        return cls.objects.create(
            appointment=appointment,
            client=appointment.client,
            channel=channel,
            status=cls.Status.SENT,
            sent_at=timezone.now(),
            detail=detail or "",
        )


class Campaign(models.Model):
    """A marketing campaign for one salon on one channel.

    M1 was draft-only; M2 adds the send path
    (``messaging.campaign_send.send_campaign``): a draft campaign
    may transition exactly once, to ``sent`` (with ``sent_at``
    stamped), through the existing provider-agnostic SMS adapter
    interface or Django's SMTP email settings -- never a provider
    SDK in core. Audience selection (see ``messaging.campaigns``)
    only reads the per-channel opt-ins on ``clients.Client`` and
    is re-resolved at send time. ``subject`` is used by email
    campaigns and may be blank for SMS.
    """

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="campaigns"
    )
    name = models.CharField(max_length=200)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.channel}, {self.status})"

    def clean(self):
        super().clean()
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Unknown campaign status."})
        if self.status == self.Status.SENT and self.sent_at is None:
            raise ValidationError(
                {"sent_at": "A sent campaign must carry a sent_at timestamp."}
            )

    def save(self, *args, **kwargs):
        # Lifecycle guard: only draft/sent are valid, and ``sent``
        # must carry its timestamp. The one-way draft -> sent
        # transition itself (and the re-send refusal) is enforced
        # by the send service, the only intended writer of ``sent``.
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Unknown campaign status."})
        if self.status == self.Status.SENT and self.sent_at is None:
            raise ValidationError(
                {"sent_at": "A sent campaign must carry a sent_at timestamp."}
            )
        return super().save(*args, **kwargs)


class CampaignSend(StrictConstraints):
    """One successfully dispatched campaign message to one client.

    The campaign send-log (``ReminderSend`` cannot serve here: it
    is keyed to an appointment). As with ``ReminderSend``, a row
    is written only on a successful dispatch -- skipped or failed
    attempts create no row, exactly as they send nothing.
    ``channel`` is denormalised from the campaign at send time.
    """

    class Status(models.TextChoices):
        SENT = "sent", "Sent"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="sends"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="campaign_sends"
    )
    channel = models.CharField(max_length=20, choices=Campaign.Channel.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SENT
    )
    sent_at = models.DateTimeField(default=timezone.now)
    # Free-form send detail: the adapter reference for SMS, blank
    # for email. Never a provider name or provider-specific field.
    detail = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-sent_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "client"], name="uniq_campaign_send_per_client"
            )
        ]

    def __str__(self):
        return f"{self.channel} campaign {self.campaign_id} to client {self.client_id}"

    @classmethod
    def record(cls, campaign, client, detail=""):
        return cls.objects.create(
            campaign=campaign, client=client, channel=campaign.channel,
            status=cls.Status.SENT, sent_at=timezone.now(), detail=detail or "",
        )
