"""Appointment reminder service.

Reminders go ONLY to clients who have opted in to that channel:
``sms_opt_in`` gates SMS and ``email_opt_in`` gates email, and
the two are independent. An opted-out client (or one with no
contact detail for the channel) is skipped: the skip is the
returned :class:`ReminderResult`, never an exception, and no
send is attempted.

SMS goes through the configured provider-agnostic adapter (see
``messaging.adapters``). Email goes through Django's standard
mail settings only (``django.core.mail``): the salon points the
``EMAIL_*`` SMTP settings and ``DEFAULT_FROM_EMAIL`` at its own
mail server. Core uses no vendor messaging API.
"""
from dataclasses import dataclass

from django.core.mail import send_mail

from .adapters import get_sms_adapter


@dataclass(frozen=True)
class ReminderResult:
    """Outcome of one reminder attempt on one channel."""

    channel: str
    status: str  # "sent" or "skipped"
    reason: str = ""
    reference: str = ""

    @property
    def sent(self):
        return self.status == "sent"


def reminder_text(appointment):
    """Plain-text reminder body for ``appointment``."""
    when = appointment.start.strftime("%Y-%m-%d %H:%M") if appointment.start else ""
    return (
        f"Reminder: {appointment.service} with "
        f"{appointment.staff_member} at {when}."
    )


def send_sms_reminder(appointment, adapter=None):
    """Send an SMS reminder if the client opted in to SMS."""
    client = appointment.client
    if not client.sms_opt_in:
        return ReminderResult("sms", "skipped", reason="not_opted_in")
    if not client.phone:
        return ReminderResult("sms", "skipped", reason="missing_phone")
    adapter = adapter or get_sms_adapter()
    result = adapter.send_sms(client.phone, reminder_text(appointment))
    if not result.success:
        return ReminderResult(
            "sms", "skipped", reason=result.message or result.status,
            reference=result.reference,
        )
    return ReminderResult("sms", "sent", reference=result.reference)


def send_email_reminder(appointment):
    """Send an email reminder if the client opted in to email."""
    client = appointment.client
    if not client.email_opt_in:
        return ReminderResult("email", "skipped", reason="not_opted_in")
    if not client.email:
        return ReminderResult("email", "skipped", reason="missing_email")
    sent = send_mail(
        subject="Your appointment reminder",
        message=reminder_text(appointment),
        from_email=None,  # Django uses DEFAULT_FROM_EMAIL
        recipient_list=[client.email],
    )
    if not sent:
        return ReminderResult("email", "skipped", reason="send_failed")
    return ReminderResult("email", "sent")


def send_appointment_reminder(appointment, channel, adapter=None):
    """Send a reminder on one channel (``"sms"`` or ``"email"``)."""
    if channel == "sms":
        return send_sms_reminder(appointment, adapter=adapter)
    if channel == "email":
        return send_email_reminder(appointment)
    raise ValueError(f"unknown reminder channel: {channel!r}")
