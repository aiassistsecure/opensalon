"""Read-only campaign send row-per-send detail CSV export.

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated here, and no adapter is touched.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This is the record-level companion to the
aggregate exports in :mod:`messaging.campaign_send_export`
(per-day totals) and :mod:`messaging.campaign_send_totals_export`
(period summary): where those count ``CampaignSend`` rows, this
module lists them -- one row per ``CampaignSend`` actually
dispatched, mirroring the ``ReminderSend`` record export in
:mod:`messaging.send_export` (``export_sends``).

Columns -- exactly ``CampaignSend`` fields, no invented fields:
``id``, ``salon_id`` (via the campaign, the scoping the totals
service uses: ``campaign__salon``), ``campaign_id``,
``client_id``, ``channel``, ``status``, ``sent_at`` (ISO-8601),
``detail``. No client name, email, or phone is exported.

Opt-in / audience semantics: a ``CampaignSend`` row exists only
for a recipient who passed the campaign send service's send-time
per-channel opt-in re-check, so exporting the stored rows exactly
as recorded respects those semantics -- this module adds no
sending, no audience resolution, and no re-interpretation.

Range semantics follow sibling exports: ``date_from`` /
``date_to`` are inclusive whole local days in the salon's
timezone; ``date_to`` may be omitted for a single-day export.
A reversed range, a missing salon, or a missing start date
exports as ``[]`` / a header-only CSV. Ordering is oldest
first (``sent_at``, then ``id``). Lines end ``"\\n"``.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import CampaignSend

__all__ = [
    "CAMPAIGN_SEND_DETAIL_FIELDNAMES",
    "DETAIL_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "campaign_send_detail",
    "campaign_send_detail_csv",
    "campaign_send_detail_row",
    "export_campaign_send_detail",
    "export_campaign_send_detail_csv",
]

#: Column / key order shared by the detail dict and CSV exports.
CAMPAIGN_SEND_DETAIL_FIELDNAMES = [
    "id", "salon_id", "campaign_id", "client_id",
    "channel", "status", "sent_at", "detail",
]
DETAIL_FIELDNAMES = CAMPAIGN_SEND_DETAIL_FIELDNAMES
EXPORT_FIELDNAMES = CAMPAIGN_SEND_DETAIL_FIELDNAMES


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


def campaign_send_detail_row(send):
    """Return one stored ``CampaignSend`` as an export row dict."""
    return {
        "id": send.pk,
        "salon_id": send.campaign.salon_id,
        "campaign_id": send.campaign_id,
        "client_id": send.client_id,
        "channel": send.channel,
        "status": send.status,
        "sent_at": send.sent_at.isoformat() if send.sent_at else None,
        "detail": send.detail,
    }


def export_campaign_send_detail(salon, date_from, date_to=None):
    """Return ``salon``'s ``CampaignSend`` rows in a date range.

    One dict per send, scoped by ``campaign__salon``, ordered
    oldest first (``sent_at``, then ``id``). An empty or
    reversed range, a missing salon, or a missing start date
    exports as ``[]``. Read-only.
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
        CampaignSend.objects.filter(
            campaign__salon=salon,
            sent_at__gte=window_start, sent_at__lt=window_end,
        )
        .select_related("campaign")
        .order_by("sent_at", "id")
    )
    return [campaign_send_detail_row(send) for send in sends]


def export_campaign_send_detail_csv(salon, date_from, date_to=None):
    """Return :func:`export_campaign_send_detail` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CAMPAIGN_SEND_DETAIL_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_campaign_send_detail(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
campaign_send_detail = export_campaign_send_detail
campaign_send_detail_csv = export_campaign_send_detail_csv
