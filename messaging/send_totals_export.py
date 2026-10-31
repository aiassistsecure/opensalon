"""Read-only reminder-send totals CSV export (L8-M11).

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated here, and no provider adapter is
touched. The figures are aggregates over ``ReminderSend`` rows
already dispatched under the opt-in guards in the reminder
services; this module adds no sending of its own.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing L8-M8 send
totals (:mod:`messaging.send_totals`) for a whole period as a
plain list of dicts (:func:`export_send_totals_summary`) and as
a CSV string (:func:`export_send_totals_summary_csv`) built
from that same list, so the two formats can never disagree --
one source of truth. The totals computation itself is never
reimplemented here: every count comes verbatim from
:func:`messaging.send_totals.send_totals`.

Shape -- distinct from :mod:`messaging.send_export` (L8-M9),
which breaks the same totals down per local day. This export
summarises the period as a whole: one row per channel per
status, taken from ``SendTotals.by_channel_by_status`` (every
known channel and status, zero-filled by the totals service,
so an empty period still reports explicit ``0`` rows).

Columns -- exactly the fields ``SendTotals`` produces, no
invented fields:

* ``salon_id`` -- ``SendTotals.salon_id``;
* ``start_date`` / ``end_date`` -- the range, ISO-8601;
* ``channel`` -- each channel in the totals service's order;
* ``status`` -- each status in the totals service's order;
* ``count`` -- ``by_channel_by_status[channel][status]``,
  verbatim. The counts sum to ``SendTotals.total``.

Range semantics follow the totals service and sibling exports:
``date_from`` / ``date_to`` are inclusive whole local days in
the salon's timezone; ``date_to`` may be omitted for a
single-day export. A reversed range, a missing salon, or a
missing start date exports as ``[]`` / a header-only CSV.
Ordering is deterministic: the totals service's channel order,
then its status order. Lines end ``"\\n"``.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .send_totals import CHANNELS, STATUSES, send_totals

__all__ = [
    "TOTALS_EXPORT_FIELDNAMES",
    "export_send_totals_summary",
    "export_send_totals_summary_csv",
    "send_totals_export_csv",
]

#: Column / key order shared by the summary dict and CSV exports.
TOTALS_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "channel", "status", "count",
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


def export_send_totals_summary(salon, date_from, date_to=None):
    """Return period send totals as one dict per channel/status.

    Rows are rendered verbatim from :func:`send_totals` with the
    same range: channels in the totals service's order, then
    statuses in its order. An empty period yields zero-filled
    rows (one per channel per status); a reversed range, a
    missing salon, or a missing start date yields ``[]``.
    Read-only.
    """
    bounds = _range(salon, date_from, date_to)
    if bounds is None:
        return []
    first, last = bounds
    totals = send_totals(salon, first, last)
    rows = []
    for channel in CHANNELS:
        per_status = totals.by_channel_by_status.get(channel, {})
        for status in STATUSES:
            rows.append({
                "salon_id": totals.salon_id,
                "start_date": totals.start_date.isoformat(),
                "end_date": totals.end_date.isoformat(),
                "channel": channel,
                "status": status,
                "count": per_status.get(status, 0),
            })
    return rows


def export_send_totals_summary_csv(salon, date_from, date_to=None):
    """Return :func:`export_send_totals_summary` as CSV.

    The header row is :data:`TOTALS_EXPORT_FIELDNAMES` and every
    data row comes from :func:`export_send_totals_summary` with
    the same arguments, so CSV and list exports always agree.
    A range with no export is the header row alone.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=TOTALS_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_send_totals_summary(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
send_totals_export_csv = export_send_totals_summary_csv
