"""Messaging's own persisted records.

Opt-in state still lives on ``clients.Client`` (the one source of
truth) and is never duplicated here. Messaging stores the history
of reminder sends it has actually dispatched (``ReminderSend``),
and marketing campaign drafts (``Campaign``) -- M1 is model and
audience only: a campaign has no send path yet.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon


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
    """A marketing campaign draft for one salon on one channel.

    Marketing is the last Slice-3 capability and M1 is deliberately
    draft-only: the only status is ``draft``, there is no send
    method and no state transition beyond draft, and audience
    selection (see ``messaging.campaigns``) only reads the
    per-channel opt-ins on ``clients.Client``. Sending -- through
    the existing provider-agnostic SMS adapter interface or
    Django's SMTP email settings, never a provider SDK in core --
    is a later microtask. ``subject`` is used by email campaigns
    and may be blank for SMS.
    """

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.channel}, {self.status})"

    def clean(self):
        super().clean()
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {"status": "Campaigns are draft-only in this version."}
            )

    def save(self, *args, **kwargs):
        # Draft-only lifecycle: refuse any non-draft status rather
        # than implying a send/sent state that does not exist yet.
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {"status": "Campaigns are draft-only in this version."}
            )
        return super().save(*args, **kwargs)
