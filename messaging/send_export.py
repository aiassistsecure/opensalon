"""Read-only reminder send CSV export service (L8-M9).

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated here, and no provider adapter is
touched.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing L8-M8 send
totals (:mod:`messaging.send_totals`) as a plain list of dicts
(:func:`export_send_totals`) and as a CSV string
(:func:`export_send_totals_csv`) built from that same list, so
the two formats can never disagree -- one source of truth. It
also exports the underlying ``ReminderSend`` records
(:func:`export_sends` / :func:`export_sends_csv`) using only
real model fields.

Totals columns -- exactly the fields ``SendTotals`` produces,
no invented fields:

* ``salon_id`` -- ``SendTotals.salon_id``;
* ``date`` -- each local day in ``SendTotals.by_day``, ISO-8601;
* ``channel`` -- each channel in ``SendTotals.by_day_by_channel``
  for that day (every known channel, zero-filled by the totals
  service, so empty days/channels appear with ``count`` 0);
* ``count`` -- ``by_day_by_channel[date][channel]``, verbatim.

Record columns -- exactly ``ReminderSend`` fields: ``id``,
``salon_id`` (the send's client's salon, the scoping
``send_totals`` uses), ``appointment_id``, ``client_id``,
``channel``, ``status``, ``sent_at`` (ISO-8601), ``detail``.
No client name, email, or phone is exported.

Range semantics follow the totals service and sibling exports:
``date_from`` / ``date_to`` are inclusive whole local days in
the salon's timezone; ``date_to`` may be omitted for a
single-day export. A reversed range, a missing salon, or a
missing start date exports as ``[]`` / a header-only CSV.
Ordering is deterministic: totals by date then the totals
service's channel order; records oldest first (``sent_at``,
then ``id``). An empty range exports as ``[]`` / the header
row alone, never ``None``.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import ReminderSend
from .send_totals import CHANNELS, send_totals

__all__ = [
    "EXPORT_FIELDNAMES",
    "RECORD_FIELDNAMES",
    "export_send_totals",
    "export_send_totals_csv",
    "export_sends",
    "export_sends_csv",
    "reminder_send_export_row",
    "send_export_row",
    "send_totals_csv",
]

#: Column / key order shared by the totals dict and CSV exports.
EXPORT_FIELDNAMES = ["salon_id", "date", "channel", "count"]

#: Column / key order for the record-level export.
RECORD_FIELDNAMES = [
    "id", "salon_id", "appointment_id", "client_id",
    "channel", "status", "sent_at", "detail",
]


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def _range(salon, date_from, date_to):
    """Return (first, last) local dates, or None for no export."""
    if salon is None or date_from is None:
        return None
    tz = _tz_for(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return None
    return first, last


def export_send_totals(salon, date_from, date_to=None):
    """Return per-day, per-channel send totals as dicts.

    Rows are rendered verbatim from :func:`send_totals` with
    the same range: one row per local day per channel, in date
    order, channels in the totals service's order. Read-only.
    """
    bounds = _range(salon, date_from, date_to)
    if bounds is None:
        return []
    first, last = bounds
    totals = send_totals(salon, first, last)
    rows = []
    for day in sorted(totals.by_day_by_channel):
        per_channel = totals.by_day_by_channel[day]
        for channel in CHANNELS:
            rows.append({
                "salon_id": totals.salon_id,
                "date": day.isoformat(),
                "channel": channel,
                "count": per_channel.get(channel, 0),
            })
    return rows


def export_send_totals_csv(salon, date_from, date_to=None):
    """Return :func:`export_send_totals` for the range as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_send_totals` with the same
    arguments, so CSV and list exports always agree. An empty
    range exports as the header row alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_send_totals(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


def send_export_row(send):
    """Return one stored ``ReminderSend`` as an export row dict."""
    return {
        "id": send.pk,
        "salon_id": send.client.salon_id,
        "appointment_id": send.appointment_id,
        "client_id": send.client_id,
        "channel": send.channel,
        "status": send.status,
        "sent_at": send.sent_at.isoformat() if send.sent_at else None,
        "detail": send.detail,
    }


def export_sends(salon, date_from, date_to=None):
    """Return ``salon``'s ``ReminderSend`` rows in a date range.

    Scoped by ``client__salon`` (the totals service's scoping),
    ordered oldest first (``sent_at``, then ``id``). An empty
    or reversed range, a missing salon, or a missing start
    date exports as ``[]``. Read-only.
    """
    bounds = _range(salon, date_from, date_to)
    if bounds is None:
        return []
    first, last = bounds
    tz = _tz_for(salon)
    window_start = datetime.datetime.combine(
        first, datetime.time.min, tzinfo=tz)
    window_end = datetime.datetime.combine(
        last + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
    sends = (
        ReminderSend.objects.filter(
            client__salon=salon,
            sent_at__gte=window_start, sent_at__lt=window_end,
        )
        .select_related("client")
        .order_by("sent_at", "id")
    )
    return [send_export_row(send) for send in sends]


def export_sends_csv(salon, date_from, date_to=None):
    """Return :func:`export_sends` for the range as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=RECORD_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_sends(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
reminder_send_export_row = send_export_row
send_totals_csv = export_send_totals_csv
