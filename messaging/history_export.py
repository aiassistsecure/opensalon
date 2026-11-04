"""Read-only reminder-history CSV export (L8-M13).

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, dispatched, stored, or mutated here, and no provider
adapter is touched.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
reminder-history service (:mod:`messaging.history`, L8-M7b,
built on the ``ReminderSend`` log) as plain lists of dicts and
as CSV strings built from those same lists, so the two formats
can never disagree -- one source of truth.

History logic -- reused verbatim, never reimplemented: every
count and every row comes exactly from the history service:

* :func:`export_history_summary` /
  :func:`export_history_summary_csv` -- one row per local day
  per channel over an inclusive date range, rendered from
  :func:`messaging.history.reminder_history_summary`'s
  ``by_day_by_channel`` (every day and every known channel
  present, zero-filled by the service, so an empty range
  reports explicit ``0`` rows). A reversed range raises
  ``ValueError``, exactly as the service does. An optional
  ``salon=`` / ``salon_id=`` argument passes through to the
  service and scopes the counts to one salon (via the send's
  ``client__salon``); omitted, the export covers all salons,
  exactly as before.
* :func:`export_client_history` /
  :func:`export_client_history_csv` -- one row per send in
  :func:`messaging.history.client_send_history` for one
  client, most recent first, in the service's order. A
  client with no sends (or a missing client) exports as
  ``[]`` / a header-only CSV. Both accept one optional
  ``start`` / ``end`` window pair on the send's ``sent_at``
  (default ``None`` = unbounded, output byte-identical to
  before); the window applies BEFORE the existing
  ``limit``. Range semantics mirror the sibling ledger
  exports: start-inclusive and end-exclusive after
  normalisation -- a ``date`` start means the start of
  that day and a ``date`` end means the start of the
  *following* day, so two dates include the whole end
  day; a ``datetime`` is used as given (naive datetimes
  are interpreted in the current time zone).

Opt-in semantics are untouched: opt-in state lives only on
``clients.Client`` and is neither read nor duplicated here;
this module only exports history the service already derives
from sends actually dispatched.

Columns -- exactly the service's / log's actual fields, no
invented fields:

Summary: ``start_date`` / ``end_date`` (the range, ISO-8601),
``date`` (each local day, ISO-8601), ``channel``, ``count``
(``by_day_by_channel[date][channel]``, verbatim; the counts
sum to the summary's ``total``).

Client history: ``id``, ``appointment_id``, ``client_id``,
``channel``, ``status``, ``sent_at`` (ISO-8601), ``detail`` --
exactly the ``ReminderSend`` fields the service returns. No
client name, email, or phone is exported.

Ordering is deterministic: summary rows by day then the
service's channel order; client rows in the service's order
(most recent first). Lines end ``"\\n"``.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .history import CHANNELS, client_send_history, reminder_history_summary

__all__ = [
    "CLIENT_HISTORY_FIELDNAMES",
    "HISTORY_EXPORT_FIELDNAMES",
    "export_client_history",
    "export_client_history_csv",
    "export_history_summary",
    "export_history_summary_csv",
    "history_export_csv",
]

#: Column / key order shared by the summary dict and CSV exports.
HISTORY_EXPORT_FIELDNAMES = [
    "start_date", "end_date", "date", "channel", "count",
]

#: Column / key order for the per-client history exports.
CLIENT_HISTORY_FIELDNAMES = [
    "id", "appointment_id", "client_id", "channel", "status",
    "sent_at", "detail",
]


def export_history_summary(start=None, end=None, **kwargs):
    """Return history counts as one dict per day per channel.

    Rows are rendered verbatim from
    :func:`messaging.history.reminder_history_summary` with
    the same range arguments (``date_from=`` / ``date_to=``,
    ``salon=`` / ``salon_id=``, and the other aliases pass
    through): days in range order,
    channels in the service's order. A reversed range raises
    ``ValueError`` as the service does. Read-only.
    """
    summary = reminder_history_summary(start, end, **kwargs)
    rows = []
    for day in sorted(summary.by_day_by_channel):
        per_channel = summary.by_day_by_channel[day]
        for channel in CHANNELS:
            rows.append({
                "start_date": summary.start_date.isoformat(),
                "end_date": summary.end_date.isoformat(),
                "date": day.isoformat(),
                "channel": channel,
                "count": per_channel.get(channel, 0),
            })
    return rows


def export_history_summary_csv(start=None, end=None, **kwargs):
    """Return :func:`export_history_summary` as CSV text.

    The header row is :data:`HISTORY_EXPORT_FIELDNAMES` and
    every data row comes from :func:`export_history_summary`
    with the same arguments, so CSV and list exports always
    agree.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=HISTORY_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_history_summary(start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def export_client_history(client, limit=None, start=None, end=None):
    """Return one client's sends as dict rows.

    Rows are rendered verbatim from
    :func:`messaging.history.client_send_history`, in the
    service's order (most recent first). A missing client or
    a client with no sends returns ``[]``. Read-only.

    ``start`` / ``end`` are one optional window pair on the
    send's ``sent_at`` (see the module docstring for range
    semantics); the default ``None`` / ``None`` is the full
    history, unchanged. The window applies BEFORE ``limit``:
    sends outside the window never consume the limit.
    """
    sends = client_send_history(client)
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None or end_bound is not None:
        sends = [
            send for send in sends
            if send.sent_at is not None
            and (start_bound is None or send.sent_at >= start_bound)
            and (end_bound is None or send.sent_at < end_bound)
        ]
    if limit is not None:
        sends = sends[: int(limit)]
    return [{
        "id": send.pk,
        "appointment_id": send.appointment_id,
        "client_id": send.client_id,
        "channel": send.channel,
        "status": send.status,
        "sent_at": send.sent_at.isoformat() if send.sent_at else "",
        "detail": send.detail,
    } for send in sends]


def export_client_history_csv(client, limit=None, start=None, end=None):
    """Return :func:`export_client_history` as CSV text.

    The header row is :data:`CLIENT_HISTORY_FIELDNAMES` and
    every data row comes from :func:`export_client_history`
    with the same arguments (including the optional
    ``start`` / ``end`` window). A client with no sends in
    the window exports as the header row alone.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLIENT_HISTORY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_client_history(
            client, limit=limit, start=start, end=end):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
history_export_csv = export_history_summary_csv
