"""Read-only campaign search CSV export service.

Backend only, read-only. Renders :mod:`messaging.campaign_search`
as dicts and CSV built from that same list (one source of truth):
every row comes verbatim from ``search_campaigns`` with the same
arguments; ``send_count`` is its annotation, never recounted here.
Columns: ``id``, ``salon_id``, ``name``, ``channel``, ``status``,
``subject``, ``sent_at``, ``created_at``, ``send_count``
(datetimes ISO-8601, ``sent_at`` None for drafts). Filter semantics
and errors follow the search service verbatim. Missing salon
exports as ``[]`` / header-only CSV. Ordering: newest first.
Lines end ``"\\n"``. No provider SDK, field, or name appears here.
"""
import csv
import io

from .campaign_search import search_campaigns

__all__ = [
    "EXPORT_FIELDNAMES",
    "SEARCH_EXPORT_FIELDNAMES",
    "campaign_search_export_row",
    "export_campaign_search",
    "export_campaign_search_csv",
    "export_search_campaigns",
    "export_search_campaigns_csv",
]

EXPORT_FIELDNAMES = [
    "id", "salon_id", "name", "channel", "status", "subject",
    "sent_at", "created_at", "send_count",
]
SEARCH_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def campaign_search_export_row(campaign):
    """Return one searched ``campaign`` as a row dict."""
    return {
        "id": campaign.pk,
        "salon_id": campaign.salon_id,
        "name": campaign.name,
        "channel": campaign.channel,
        "status": campaign.status,
        "subject": campaign.subject,
        "sent_at": _dt(campaign.sent_at),
        "created_at": _dt(campaign.created_at),
        "send_count": int(getattr(campaign, "send_count", 0) or 0),
    }


def _resolve_term(term, kwargs):
    value = term
    for alias in ("name", "query", "fragment"):
        candidate = kwargs.pop(alias, None)
        if value is None:
            value = candidate
    return value


def export_campaign_search(salon, term=None, *, status=None,
                           channel=None, start=None, end=None,
                           **kwargs):
    """Return ``salon``'s campaigns matching the search, as dicts."""
    fragment = _resolve_term(term, kwargs)
    campaigns = search_campaigns(
        salon, fragment, status=status, channel=channel,
        start=start, end=end, **kwargs,
    )
    return [campaign_search_export_row(c) for c in campaigns]


def export_campaign_search_csv(salon, term=None, *, status=None,
                               channel=None, start=None, end=None,
                               **kwargs):
    """Return :func:`export_campaign_search` with same args as CSV."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_campaign_search(
        salon, term, status=status, channel=channel, start=start,
        end=end, **kwargs,
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_search_campaigns = export_campaign_search
export_search_campaigns_csv = export_campaign_search_csv
