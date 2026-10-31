"""Batch SMS delivery for appointment reminders (L8-M3).

The single-appointment path lives in ``messaging.reminders``
(:func:`send_sms_reminder`). This module is the delivery run on
top of it: find the appointments due for a reminder in a window
and send each one through the configured provider-agnostic SMS
adapter (see ``messaging.adapters``) -- core speaks only that
interface, and no provider SDK, field, or name appears here.

Eligibility is exactly the single-send gate, applied again here
so a batch run can never widen it:

- the appointment must still be upcoming business: status booked
  or confirmed (cancelled / completed / no-show / in-service /
  arrived appointments are skipped);
- the client must have ``sms_opt_in`` set -- an opted-out client
  gets nothing, on this channel regardless of email opt-in;
- the client must have a phone number on record.

Skips are counted in the returned summary, never raised, and no
send is attempted for a skipped appointment.
"""
from dataclasses import dataclass, field

from .email_reminders import DEFAULT_WINDOW, REMINDABLE_STATUSES, due_appointments
from .reminders import ReminderResult, send_sms_reminder

__all__ = [
    "DEFAULT_WINDOW",
    "REMINDABLE_STATUSES",
    "SmsDeliverySummary",
    "due_appointments",
    "send_due_sms_reminders",
]


@dataclass
class SmsDeliverySummary:
    """Counts + per-appointment results of one delivery run."""

    sent: int = 0
    skipped_not_opted_in: int = 0
    skipped_missing_phone: int = 0
    skipped_status: int = 0
    skipped_send_failed: int = 0
    results: list = field(default_factory=list)

    @property
    def skipped(self):
        return (
            self.skipped_not_opted_in
            + self.skipped_missing_phone
            + self.skipped_status
            + self.skipped_send_failed
        )


def send_due_sms_reminders(now=None, within=DEFAULT_WINDOW, appointments=None,
                           adapter=None):
    """Deliver SMS reminders for due appointments; return a summary.

    ``appointments`` defaults to :func:`due_appointments` for the
    window; an explicit iterable is still passed through every
    gate above (status, opt-in, phone) before anything sends.
    ``adapter`` defaults to the configured SMS adapter.
    """
    if appointments is None:
        appointments = due_appointments(now=now, within=within)
    summary = SmsDeliverySummary()
    for appointment in appointments:
        if appointment.status not in REMINDABLE_STATUSES:
            summary.skipped_status += 1
            _record(summary, "not_remindable_status")
            continue
        result = send_sms_reminder(appointment, adapter=adapter)
        summary.results.append(result)
        if result.sent:
            summary.sent += 1
        elif result.reason == "not_opted_in":
            summary.skipped_not_opted_in += 1
        elif result.reason == "missing_phone":
            summary.skipped_missing_phone += 1
        else:
            summary.skipped_send_failed += 1
    return summary


def _record(summary, reason):
    summary.results.append(ReminderResult("sms", "skipped", reason=reason))
