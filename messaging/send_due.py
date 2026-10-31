"""Send the due reminders listed by ``messaging.due`` (L8-M6).

Bridge between the read-only due listing (``messaging.due``,
PR #71) and the combined delivery run (``messaging.dispatch``,
PR #61): take the appointments due in an explicit
``[start, end]`` window, with the per-channel eligibility the
listing reports for each of them, and dispatch them.

The listing is the eligibility truth here, exactly as
``messaging.due`` reports it:

- an appointment eligible on no channel is never handed to the
  dispatch at all -- it is counted here as skipped on both
  channels, with the listing's own reason strings;
- an appointment eligible on at least one channel is handed to
  the combined dispatch, which applies its own per-channel
  gates unchanged -- so a channel the listing marked ineligible
  (opt-in off, or contact detail missing for that channel) is
  skipped by the dispatch and never sent, while the eligible
  channel sends. Email opt-in never enables SMS and SMS opt-in
  never enables email, on either side of this bridge.

No provider SDK, field, or name appears here: delivery goes
through the combined dispatch, i.e. email via Django's standard
mail framework and SMS via the configured provider-agnostic
adapter, forwarded as ``adapter``.
"""
from dataclasses import dataclass, field

from .dispatch import ReminderDispatchSummary, send_due_reminders as _dispatch
from .due import due_reminders
from .reminders import ReminderResult

__all__ = [
    "SendDueSummary",
    "send_due",
    "send_due_reminders_between",
]


@dataclass
class SendDueSummary:
    """Outcome of one send-due run over a due listing.

    ``due`` is the listing this run acted on and ``dispatch``
    is the combined summary for the appointments handed to the
    dispatch. ``results`` additionally carries one skipped
    :class:`ReminderResult` per channel for each appointment
    that was eligible on no channel and so never dispatched.
    """

    due: list = field(default_factory=list)
    dispatch: ReminderDispatchSummary = None
    results: list = field(default_factory=list)

    @property
    def considered(self):
        return len(self.due)

    @property
    def dispatched(self):
        return sum(1 for d in self.due if d.any_eligible)

    @property
    def sent(self):
        return self.dispatch.sent if self.dispatch else 0

    @property
    def skipped(self):
        # Dispatch skips cover every channel outcome for the
        # appointments it saw (including the ineligible channel
        # of a partly eligible appointment); appointments it
        # never saw contribute two skipped results each, held
        # in ``results`` beyond the dispatch's own results.
        if not self.dispatch:
            return len(self.results)
        return self.dispatch.skipped + (
            len(self.results) - len(self.dispatch.results)
        )


def send_due_reminders_between(start, end, appointments=None,
                               adapter=None, due=None):
    """Dispatch reminders for the appointments due in ``[start, end]``.

    ``due`` is an optional precomputed listing from
    :func:`messaging.due.due_reminders`; by default the listing
    is built here from the window (and ``appointments``, when
    given, is passed through to that listing, which filters it
    to the window and applies the same eligibility gates).

    Returns a :class:`SendDueSummary`. Ineligibility is data in
    the summary, never an exception; a reversed window raises
    ``ValueError``, exactly as the listing does.
    """
    if due is None:
        due = due_reminders(start, end, appointments=appointments)
    else:
        due = list(due)
    summary = SendDueSummary(due=due)
    eligible = [d.appointment for d in due if d.any_eligible]
    summary.dispatch = _dispatch(appointments=eligible, adapter=adapter)
    summary.results = list(summary.dispatch.results)
    for entry in due:
        if entry.any_eligible:
            continue
        for eligibility in (entry.email, entry.sms):
            summary.results.append(
                ReminderResult(
                    eligibility.channel, "skipped",
                    reason=eligibility.reason,
                )
            )
    return summary


# Short alias matching the module name.
send_due = send_due_reminders_between
