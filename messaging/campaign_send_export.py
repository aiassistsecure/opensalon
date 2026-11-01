"""Read-only campaign send per-day detail CSV export service.

Backend only, read-only, no provider adapter touched. Renders
:mod:`messaging.campaign_send_totals` verbatim as dicts
(:func:`export_campaign_send_totals_detail`) and CSV
(:func:`export_campaign_send_totals_detail_csv`) built from
that same list -- one source of truth, no recomputation from
``CampaignSend`` rows. Distinct from the period summary in
:mod:`messaging.campaign_send_totals_export` (per channel/status).

Columns: ``salon_id``, ``date`` (ISO-8601 local day),
``channel``, ``count`` -- verbatim from
``CampaignSendTotals.by_day_by_channel`` (zero-filled by the
totals service). ``date_from``/``date_to`` are inclusive whole
local days; ``date_to`` may be omitted (single day). Reversed
range, missing salon, or missing start exports as ``[]`` /
header-only CSV. Ordering: date, then totals channel order.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .campaign_send_totals import CHANNELS, campaign_send_totals

__all__ = ["CAMPAIGN_DETAIL_EXPORT_FIELDNAMES", "CAMPAIGN_SEND_EXPORT_FIELDNAMES",
    "DETAIL_EXPORT_FIELDNAMES", "EXPORT_FIELDNAMES", "campaign_send_export_csv",
    "campaign_send_totals_detail_csv", "export_campaign_send_totals",
    "export_campaign_send_totals_csv", "export_campaign_send_totals_detail",
    "export_campaign_send_totals_detail_csv"]

EXPORT_FIELDNAMES = ["salon_id", "date", "channel", "count"]
DETAIL_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES
CAMPAIGN_SEND_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES
CAMPAIGN_DETAIL_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES


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


def export_campaign_send_totals_detail(salon, date_from, date_to=None):
    """Per-day, per-channel rows verbatim from campaign_send_totals."""
    bounds = _range(salon, date_from, date_to)
    if bounds is None:
        return []
    first, last = bounds
    totals = campaign_send_totals(salon, first, last)
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


def export_campaign_send_totals_detail_csv(salon, date_from, date_to=None):
    """CSV of :func:`export_campaign_send_totals_detail` (same rows)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_campaign_send_totals_detail(
            salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_campaign_send_totals = export_campaign_send_totals_detail
export_campaign_send_totals_csv = export_campaign_send_totals_detail_csv
campaign_send_totals_detail_csv = export_campaign_send_totals_detail_csv
campaign_send_export_csv = export_campaign_send_totals_detail_csv
