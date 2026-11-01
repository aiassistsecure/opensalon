"""Read-only campaign-send totals CSV export.

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated here, and no provider adapter is
touched. The figures are aggregates over ``CampaignSend`` rows
already dispatched by the campaign send service; this module
adds no sending of its own.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing campaign
send totals (:mod:`messaging.campaign_send_totals`) for a
whole period as a plain list of dicts
(:func:`export_campaign_send_totals_summary`) and as a CSV
string (:func:`export_campaign_send_totals_summary_csv`) built
from that same list, so the two formats can never disagree --
one source of truth. Every count comes verbatim from
:func:`messaging.campaign_send_totals.campaign_send_totals`.

Shape: one row per channel per status, taken from
``CampaignSendTotals.by_channel_by_status`` (zero-filled by
the totals service). Columns -- exactly the fields the totals
service produces: ``salon_id``, ``start_date`` / ``end_date``
(ISO-8601), ``channel``, ``status``, ``count`` (verbatim; the
counts sum to ``CampaignSendTotals.total``).

Range semantics follow the totals service: ``date_from`` /
``date_to`` are inclusive whole local days in the salon's
timezone; ``date_to`` may be omitted for a single-day export.
A reversed range, a missing salon, or a missing start date
exports as ``[]`` / a header-only CSV. Ordering is the totals
service's channel order, then its status order. Lines end
``"\\n"``.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .campaign_send_totals import CHANNELS, STATUSES, campaign_send_totals

__all__ = [
    "CAMPAIGN_TOTALS_EXPORT_FIELDNAMES",
    "TOTALS_EXPORT_FIELDNAMES",
    "campaign_send_totals_export_csv",
    "export_campaign_send_totals_summary",
    "export_campaign_send_totals_summary_csv",
]

#: Column / key order shared by the summary dict and CSV exports.
CAMPAIGN_TOTALS_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "channel", "status", "count",
]
#: Alias mirroring the fieldnames name in the sibling export.
TOTALS_EXPORT_FIELDNAMES = CAMPAIGN_TOTALS_EXPORT_FIELDNAMES


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


def export_campaign_send_totals_summary(salon, date_from, date_to=None):
    """Return period campaign send totals, one dict per channel/status.

    Rows are rendered verbatim from :func:`campaign_send_totals`
    with the same range (channels, then statuses, in the totals
    service's order). An empty period yields zero-filled rows;
    a reversed range, a missing salon, or a missing start date
    yields ``[]``. Read-only.
    """
    bounds = _range(salon, date_from, date_to)
    if bounds is None:
        return []
    first, last = bounds
    totals = campaign_send_totals(salon, first, last)
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


def export_campaign_send_totals_summary_csv(salon, date_from, date_to=None):
    """Return :func:`export_campaign_send_totals_summary` as CSV.

    The header row is :data:`CAMPAIGN_TOTALS_EXPORT_FIELDNAMES`
    and every data row comes from the list export with the same
    arguments, so CSV and list exports always agree. A range
    with no export is the header row alone.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CAMPAIGN_TOTALS_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_campaign_send_totals_summary(
            salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
campaign_send_totals_export_csv = export_campaign_send_totals_summary_csv
