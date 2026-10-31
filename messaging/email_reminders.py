"""Batch email delivery for appointment reminders (L8-M2).

The single-appointment path lives in ``messaging.reminders``
(:func:`send_email_reminder`). This module is the delivery run
on top of it: find the appointments due for a reminder in a
window, build one ``django.core.mail.EmailMessage`` per eligible
appointment, and send them all over a single connection from
``get_connection()`` -- i.e. Django's standard email framework,
configured entirely by the salon's own ``EMAIL_*`` SMTP settings
and ``DEFAULT_FROM_EMAIL`` in settings. No vendor email API, no
provider SDK, and no provider name appears here.

Eligibility is exactly the single-send gate, applied again here
so a batch run can never widen it:

- the appointment must still be upcoming business: status booked
  or confirmed (cancelled / completed / no-show / in-service /
  arrived appointments are skipped);
- the client must have ``email_opt_in`` set -- an opted-out
  client gets nothing, on this channel regardless of SMS opt-in;
- the client must have an email address on record.

Skips are counted in the returned summary, never raised, and no
message is built (let alone sent) for a skipped appointment.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from bookings.models import Appointment

from .models import ReminderSend
from .reminders import ReminderResult, reminder_text

REMINDABLE_STATUSES = (Appointment.Status.BOOKED, Appointment.Status.CONFIRMED)
DEFAULT_WINDOW = timedelta(hours=24)


def due_appointments(now=None, within=DEFAULT_WINDOW):
    """Upcoming remindable appointments starting in ``[now, now+within]``."""
    now = now or timezone.now()
    return (
        Appointment.objects.filter(
            start__gte=now,
            start__lte=now + within,
            status__in=REMINDABLE_STATUSES,
        )
        .select_related("client", "staff_member", "service")
        .order_by("start")
    )


def build_email_message(appointment, connection=None):
    """One reminder ``EmailMessage`` for an (already eligible) appointment."""
    return EmailMessage(
        subject="Your appointment reminder",
        body=reminder_text(appointment),
        from_email=None,  # Django uses DEFAULT_FROM_EMAIL (salon's own)
        to=[appointment.client.email],
        connection=connection,
    )


@dataclass
class EmailDeliverySummary:
    """Counts + per-appointment results of one delivery run."""

    sent: int = 0
    skipped_not_opted_in: int = 0
    skipped_missing_email: int = 0
    skipped_status: int = 0
    results: list = field(default_factory=list)

    @property
    def skipped(self):
        return (
            self.skipped_not_opted_in
            + self.skipped_missing_email
            + self.skipped_status
        )


def _skip(summary, reason):
    result = ReminderResult("email", "skipped", reason=reason)
    summary.results.append(result)
    if reason == "not_opted_in":
        summary.skipped_not_opted_in += 1
    elif reason == "missing_email":
        summary.skipped_missing_email += 1
    else:
        summary.skipped_status += 1
    return result


def send_due_email_reminders(now=None, within=DEFAULT_WINDOW, appointments=None):
    """Deliver email reminders for due appointments; return a summary.

    ``appointments`` defaults to :func:`due_appointments` for the
    window; an explicit iterable is still passed through every
    gate above (status, opt-in, address) before anything sends.
    All eligible messages go out over one mail connection, so a
    run against the salon's SMTP server opens it once.
    """
    if appointments is None:
        appointments = due_appointments(now=now, within=within)
    summary = EmailDeliverySummary()
    connection = get_connection()
    messages = []
    pending = []
    for appointment in appointments:
        client = appointment.client
        if appointment.status not in REMINDABLE_STATUSES:
            _skip(summary, "not_remindable_status")
            continue
        if not client.email_opt_in:
            _skip(summary, "not_opted_in")
            continue
        if not client.email:
            _skip(summary, "missing_email")
            continue
        messages.append(build_email_message(appointment, connection=connection))
        pending.append(appointment)
    if messages:
        sent_count = connection.send_messages(messages) or 0
    else:
        sent_count = 0
    for index, appointment in enumerate(pending):
        if index < sent_count:
            summary.results.append(ReminderResult("email", "sent"))
            summary.sent += 1
            ReminderSend.record(appointment, channel="email")
        else:
            summary.results.append(
                ReminderResult("email", "skipped", reason="send_failed")
            )
    return summary
