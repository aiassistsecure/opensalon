"""Combined reminder dispatch (L8-M4).

Runs both reminder channels for the appointments due in a
window -- email (``messaging.email_reminders``) and SMS
(``messaging.sms_reminders``) -- in a single call and returns
one combined summary.

The channels stay fully independent, exactly as their own
modules define them:

- each channel applies its own eligibility gate unchanged --
  this module reuses the existing ``send_due_*`` functions and
  duplicates none of their logic, so a dispatch run can never
  widen a gate;
- ``email_opt_in`` gates email only and ``sms_opt_in`` gates
  SMS only: a client opted into only one channel is attempted
  only on that channel, and a client opted into neither is
  attempted on neither.

No provider SDK, field, or name appears here: email goes
through Django's standard mail framework and SMS through the
configured provider-agnostic adapter, as in the channel
modules.
"""
from dataclasses import dataclass

from .email_reminders import (
    DEFAULT_WINDOW,
    EmailDeliverySummary,
    due_appointments,
    send_due_email_reminders,
)
from .sms_reminders import SmsDeliverySummary, send_due_sms_reminders

__all__ = [
    "DEFAULT_WINDOW",
    "ReminderDispatchSummary",
    "send_due_reminders",
]


@dataclass
class ReminderDispatchSummary:
    """Combined per-channel summaries of one dispatch run."""

    email: EmailDeliverySummary
    sms: SmsDeliverySummary

    @property
    def sent(self):
        return self.email.sent + self.sms.sent

    @property
    def skipped(self):
        return self.email.skipped + self.sms.skipped

    @property
    def results(self):
        return self.email.results + self.sms.results


def send_due_reminders(now=None, within=DEFAULT_WINDOW, appointments=None,
                       adapter=None):
    """Dispatch email + SMS reminders for due appointments.

    ``appointments`` defaults to :func:`due_appointments` for
    the window ``[now, now+within]``. The due set is
    materialised once and passed to both channels, so email
    and SMS see exactly the same appointments; each channel
    still applies its own opt-in / contact / status gates to
    that set. ``adapter`` is forwarded to the SMS channel only
    (it defaults to the configured SMS adapter).

    Returns a :class:`ReminderDispatchSummary` with the full
    per-channel summary for each channel.
    """
    if appointments is None:
        appointments = due_appointments(now=now, within=within)
    # Materialise so both channels iterate the same set even
    # when given a one-pass iterable or a lazy queryset.
    appointments = list(appointments)
    email_summary = send_due_email_reminders(
        now=now, within=within, appointments=appointments
    )
    sms_summary = send_due_sms_reminders(
        now=now, within=within, appointments=appointments,
        adapter=adapter,
    )
    return ReminderDispatchSummary(email=email_summary, sms=sms_summary)
