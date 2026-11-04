"""Verbatim campaign CSV export service for the messaging app.

Backend only -- no views, templates, or UI. Read-only and
export only: this service never sends, dispatches, creates,
edits, or deletes a campaign, and touches no provider adapter.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every row is a stored
:class:`messaging.models.Campaign` row, verbatim -- including
the stored ``body`` and ``updated_at``, which until now
rendered only inside the salon_data bundle. This module does
not search, count sends, or aggregate anything: the campaign
search rows stay in :mod:`messaging.campaign_search_export`
(the discovery surface) and send totals stay in their own
services, unchanged.

Scoping: a salon's campaigns are the rows whose ``salon``
is that salon, in the model's own ordering (newest first:
``-created_at``, then ``-id``). A missing salon exports as
``[]`` / the header row alone.

Filters: ``status`` and ``channel`` (each optional,
default ``None`` = no filter for that field, output
identical to the unfiltered export) are exact stored-value
matches, mirroring :mod:`messaging.campaign_search` --
``status=str(status)`` / ``channel=str(channel)``, no case
folding -- and compose (AND) with each other and the salon
scope.

Date window: both export functions also accept an optional
``start_date`` / ``end_date`` window pair (aliases ``start``
/ ``end`` and ``date_from`` / ``date_to``), filtering on
``created_at`` as inclusive whole local days in the salon's
timezone, mirroring :mod:`messaging.campaign_search` on the
same records and the Family XI ledger windows: the window
is [start of ``start_date``, start of the day after
``end_date``). Each bound may be a ``date``, a ``datetime``,
an ISO string, or ``None`` (the default, unbounded -- with
both ``None`` the output is unchanged, byte-identical).
Either bound may be given alone (an open-ended window); a
``datetime`` / ISO string is reduced to its salon-local
date. A reversed window exports as ``[]`` / the header row
alone. The window composes with ``status`` and ``channel``
(window AND status AND channel AND salon scope).

Columns are exactly the fields the stored row carries, in
the salon_data bundle's order: ``id``, ``salon_id``,
``name``, ``channel``, ``subject``, ``body``, ``status``,
``sent_at``, ``created_at``, ``updated_at`` (datetimes
ISO-8601, ``sent_at`` None for drafts). Lines end ``"\\n"``.
No provider SDK, field, or name appears here.
"""
import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Campaign

__all__ = [
    "CAMPAIGN_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "campaign_export_row",
    "campaigns_csv",
    "export_campaign",
    "export_campaign_csv",
    "export_campaigns",
    "export_campaigns_csv",
]

#: Column / key order shared by the dict export and the CSV export.
CAMPAIGN_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "name",
    "channel",
    "subject",
    "body",
    "status",
    "sent_at",
    "created_at",
    "updated_at",
]
EXPORT_FIELDNAMES = CAMPAIGN_EXPORT_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    """Reduce a date / datetime / ISO string to a local date."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        if parsed.tzinfo is not None:
            return parsed.astimezone(tz).date()
        return parsed.date()


def _resolve_window(start_date, end_date, kwargs):
    """Fold the ``start`` / ``end`` / ``date_from`` / ``date_to``
    aliases into the start_date/end_date pair."""
    if "start" in kwargs:
        if start_date is not None:
            raise TypeError("multiple values for start_date")
        start_date = kwargs.pop("start")
    if "end" in kwargs:
        if end_date is not None:
            raise TypeError("multiple values for end_date")
        end_date = kwargs.pop("end")
    if "date_from" in kwargs:
        if start_date is not None:
            raise TypeError("multiple values for start_date")
        start_date = kwargs.pop("date_from")
    if "date_to" in kwargs:
        if end_date is not None:
            raise TypeError("multiple values for end_date")
        end_date = kwargs.pop("date_to")
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    return start_date, end_date


def campaign_export_row(campaign):
    """Return one stored ``campaign`` as a verbatim row dict."""
    return {
        "id": campaign.pk,
        "salon_id": campaign.salon_id,
        "name": campaign.name,
        "channel": campaign.channel,
        "subject": campaign.subject,
        "body": campaign.body,
        "status": campaign.status,
        "sent_at": _dt(campaign.sent_at),
        "created_at": _dt(campaign.created_at),
        "updated_at": _dt(campaign.updated_at),
    }


def export_campaigns(salon, *, status=None, channel=None,
                     start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s campaigns as a list of dicts.

    Each entry is one stored :class:`messaging.models.Campaign`
    row of the salon, as a dict with exactly
    :data:`CAMPAIGN_EXPORT_FIELDNAMES` keys, in the model's
    ordering (newest first). ``salon=None`` yields ``[]``.
    ``status`` and ``channel`` optionally filter by exact
    stored value (AND with each other and the salon scope);
    ``None`` (the default) applies no filter for that field.
    ``start_date`` / ``end_date`` (aliases ``start`` / ``end``,
    ``date_from`` / ``date_to``) are an optional window on
    ``created_at``: the defaults ``None`` are unbounded, so
    the default output is unchanged (see the module docstring
    for the range semantics). The window composes with
    ``status`` and ``channel``. Read-only.
    """
    start_date, end_date = _resolve_window(start_date, end_date, kwargs)
    if salon is None:
        return []
    salon_id = getattr(salon, "pk", salon)
    if salon_id is None:
        return []
    rows = Campaign.objects.filter(salon_id=salon_id)
    if status is not None:
        rows = rows.filter(status=str(status))
    if channel is not None:
        rows = rows.filter(channel=str(channel))
    if start_date is not None or end_date is not None:
        tz = _tz(salon)
        if start_date is not None:
            first = _as_local_date(start_date, tz)
            rows = rows.filter(
                created_at__gte=datetime.combine(first, time.min,
                                                 tzinfo=tz))
        if end_date is not None:
            last = _as_local_date(end_date, tz)
            rows = rows.filter(
                created_at__lt=datetime.combine(
                    last + timedelta(days=1), time.min, tzinfo=tz))
    return [campaign_export_row(row) for row in rows]


def export_campaigns_csv(salon, *, status=None, channel=None,
                         start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s campaigns as a CSV string.

    The header row is :data:`CAMPAIGN_EXPORT_FIELDNAMES` and
    every data row is rendered from :func:`export_campaigns`
    with the same arguments, so the CSV and the dict export can
    never disagree. Lines end with ``"\\n"``. ``start_date`` /
    ``end_date`` are likewise passed through: the defaults
    ``None`` are unbounded and unchanged; a given window
    exports only campaigns whose ``created_at`` falls inside
    it. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CAMPAIGN_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_campaigns(salon, status=status,
                                   channel=channel,
                                   start_date=start_date,
                                   end_date=end_date, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_campaign = export_campaigns
export_campaign_csv = export_campaigns_csv
campaigns_csv = export_campaigns_csv
