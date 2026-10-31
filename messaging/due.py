"""Due-reminder listing service (L8-M5).

Read-only counterpart to the delivery modules: given an explicit
window (``start``/``end`` datetimes), list the appointments due
for a reminder in that window together with, per appointment,
per-channel eligibility. Nothing is sent here -- callers (a
preview, a report, or a delivery run) decide what to do with
the listing.

Eligibility is exactly the gate the existing single-send and
batch code applies (``messaging.reminders``,
``messaging.email_reminders``, ``messaging.sms_reminders``),
so a listing can never widen it:

- the appointment must still be upcoming business: status booked
  or confirmed (``REMINDABLE_STATUSES``);
- email: the client must have ``email_opt_in`` set and an email
  address on record -- SMS opt-in never enables email;
- SMS: the client must have ``sms_opt_in`` set and a phone
  number on record -- email opt-in never enables SMS.

The channels are independent: a client may be eligible on one,
both, or neither. Ineligibility is data (a reason string matching
the reasons the senders return), never an exception.
"""
from dataclasses import dataclass

from bookings.models import Appointment

from .email_reminders import REMINDABLE_STATUSES

__all__ = [
    "ChannelEligibility",
    "DueAppointment",
    "appointments_due_between",
    "channel_eligibility",
    "due_reminders",
]

CHANNELS = ("email", "sms")


@dataclass(frozen=True)
class ChannelEligibility:
    """Eligibility of one appointment on one channel."""

    channel: str
    eligible: bool
    reason: str = ""  # "" when eligible

    @property
    def skipped(self):
        return not self.eligible


@dataclass(frozen=True)
class DueAppointment:
    """One due appointment with its per-channel eligibility."""

    appointment: Appointment
    email: ChannelEligibility
    sms: ChannelEligibility

    @property
    def eligible_channels(self):
        return tuple(
            c.channel for c in (self.email, self.sms) if c.eligible
        )

    @property
    def any_eligible(self):
        return bool(self.eligible_channels)

    def eligibility(self, channel):
        if channel == "email":
            return self.email
        if channel == "sms":
            return self.sms
        raise ValueError(f"unknown reminder channel: {channel!r}")


def channel_eligibility(appointment, channel):
    """Eligibility for ``appointment`` on ``channel``.

    Mirrors the senders' check order: remindable status first,
    then that channel's opt-in, then its contact detail.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown reminder channel: {channel!r}")
    if appointment.status not in REMINDABLE_STATUSES:
        return ChannelEligibility(
            channel, False, reason="not_remindable_status"
        )
    client = appointment.client
    if channel == "email":
        if not client.email_opt_in:
            return ChannelEligibility(channel, False, reason="not_opted_in")
        if not client.email:
            return ChannelEligibility(channel, False, reason="missing_email")
    else:
        if not client.sms_opt_in:
            return ChannelEligibility(channel, False, reason="not_opted_in")
        if not client.phone:
            return ChannelEligibility(channel, False, reason="missing_phone")
    return ChannelEligibility(channel, True)


def appointments_due_between(start, end):
    """Remindable appointments starting in ``[start, end]``.

    Inclusive at both ends, matching ``due_appointments`` in
    ``messaging.email_reminders``, ordered by start.
    """
    if end < start:
        raise ValueError("window end must not be before window start")
    return (
        Appointment.objects.filter(
            start__gte=start,
            start__lte=end,
            status__in=REMINDABLE_STATUSES,
        )
        .select_related("client", "staff_member", "service")
        .order_by("start")
    )


def due_reminders(start, end, appointments=None):
    """List due appointments in ``[start, end]`` with eligibility.

    ``appointments`` defaults to :func:`appointments_due_between`;
    an explicit iterable is still filtered to the window and
    passed through the same eligibility gates, so statuses the
    queryset would exclude surface as ineligible rather than
    silently sending. Returns a list of :class:`DueAppointment`.
    """
    if end < start:
        raise ValueError("window end must not be before window start")
    if appointments is None:
        appointments = appointments_due_between(start, end)
    due = []
    for appointment in appointments:
        if appointment.start is None or not (start <= appointment.start <= end):
            continue
        due.append(
            DueAppointment(
                appointment=appointment,
                email=channel_eligibility(appointment, "email"),
                sms=channel_eligibility(appointment, "sms"),
            )
        )
    return due
