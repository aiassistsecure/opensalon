"""Messaging's own persisted record: the reminder send log (L8-M7a).

Opt-in state still lives on ``clients.Client`` (the one source of
truth) and is never duplicated here. What messaging now stores is
only the history of sends it has actually dispatched, so a later
history summary can be built from real rows instead of re-deriving
outcomes from delivery summaries that are discarded after a run.
"""
from django.db import models
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client


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
