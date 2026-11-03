"""Read-only campaign search service.

Backend only -- no views, templates, or UI. Nothing is sent,
stored, or mutated here, and no provider adapter is touched.

Salon-scoped search over :class:`messaging.models.Campaign`,
mirroring :mod:`messaging.send_search` (which searches sends;
this searches the campaigns that produced them). Each result
is a ``Campaign`` annotated with ``send_count`` -- the count
of its ``CampaignSend`` rows via the ``sends`` relation, so
counts come from the one source of truth with no new
counting path.

Filters (all optional, combined with AND):

* ``name`` -- case-insensitive fragment matched against the
  campaign ``name`` (``term`` / ``query`` / ``fragment``
  accepted as aliases). Blank means no name filter.
* ``status`` -- exact ``Campaign.Status`` value.
* ``channel`` -- exact ``Campaign.Channel`` value.
* a date range -- ``start``/``end`` (``date_from=`` /
  ``date_to=`` / ``start_date=`` / ``end_date=`` aliases)
  over ``created_at`` as inclusive whole local days in the
  salon's timezone. Either bound may be given alone. A
  reversed range raises ``ValueError``.

``salon=None`` yields ``[]``, never ``None``. Ordering is
deterministic: newest first (``-created_at``, then ``-id``).
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count

from .models import Campaign

__all__ = [
    "campaign_search",
    "search_campaigns",
]

STATUSES = tuple(value for value, _label in Campaign.Status.choices)
CHANNELS = tuple(value for value, _label in Campaign.Channel.choices)


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _salon_id(salon):
    return getattr(salon, "pk", salon)


def _as_local_date(value, tz):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected a date or datetime, got {type(value).__name__}")


def search_campaigns(
    salon, name=None, *, status=None, channel=None,
    start=None, end=None, term=None, query=None, fragment=None,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return ``salon``'s campaigns matching the filters.

    Returns a list of :class:`~messaging.models.Campaign`,
    each annotated with ``send_count``, newest first.
    Read-only.
    """
    if salon is None or _salon_id(salon) is None:
        return []
    fragment_value = name
    for alias in (term, query, fragment):
        if fragment_value is None:
            fragment_value = alias
    tz = _tz(salon)
    first_raw = start if start is not None else date_from
    if first_raw is None:
        first_raw = start_date
    last_raw = end if end is not None else date_to
    if last_raw is None:
        last_raw = end_date
    first = _as_local_date(first_raw, tz)
    last = _as_local_date(last_raw, tz)
    if first is not None and last is not None and last < first:
        raise ValueError("range end must not be before range start")

    queryset = (
        Campaign.objects.filter(salon_id=_salon_id(salon))
        .annotate(send_count=Count("sends", distinct=True))
        .order_by("-created_at", "-id")
    )
    if fragment_value is not None and str(fragment_value).strip():
        queryset = queryset.filter(name__icontains=str(fragment_value).strip())
    if status is not None:
        queryset = queryset.filter(status=str(status))
    if channel is not None:
        queryset = queryset.filter(channel=str(channel))
    if first is not None:
        window_start = datetime.combine(first, time.min, tzinfo=tz)
        queryset = queryset.filter(created_at__gte=window_start)
    if last is not None:
        window_end = datetime.combine(
            last + timedelta(days=1), time.min, tzinfo=tz
        )
        queryset = queryset.filter(created_at__lt=window_end)
    return list(queryset)


def campaign_search(salon, name=None, **kwargs):
    """Alias for :func:`search_campaigns`."""
    return search_campaigns(salon, name, **kwargs)
