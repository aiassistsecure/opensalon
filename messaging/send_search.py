"""Read-only reminder-send search service (L8-M10).

Pure search service -- no views, no templates, no UI. Nothing
is sent, stored, or mutated here, and no provider adapter is
touched: every result is read from the ``ReminderSend`` rows
that are the one source of truth for sends actually dispatched
(see :mod:`messaging.models`).

Public surface:

* :func:`search_sends` -- the sends for ONE salon matching all
  of the optional filters given, newest first.
* :func:`search_reminder_sends` / :func:`reminder_send_search`
  -- aliases for :func:`search_sends`.

Scoping follows the sibling salon-scoped services
(:mod:`messaging.send_totals`, :mod:`messaging.send_export`):
a send belongs to the salon of its denormalised ``client``
(``client__salon``), so sends for other salons are never
returned. ``salon=None`` yields an empty list, never ``None``.

Filters (all optional, combined with AND):

* ``client_name`` -- a case-insensitive fragment matched
  against the client's first OR last name (``name=`` /
  ``query=`` / ``fragment=`` accepted as aliases). Blank means
  no name filter.
* ``channel`` -- an exact ``ReminderSend.Channel`` value.
* ``status`` -- an exact ``ReminderSend.Status`` value.
* a date range -- ``start``/``end`` (``date_from=`` /
  ``date_to=`` / ``start_date=`` / ``end_date=`` accepted as
  aliases). Dates mean inclusive whole local days in the
  salon's timezone, matching ``send_totals``; datetimes are
  reduced to their local date. Either bound may be given on
  its own. A reversed range raises ``ValueError``. A channel
  or status with no matching rows simply matches nothing.

Ordering is deterministic: newest first (``-sent_at``), ties
broken by ``-id`` -- the model's own ordering, made explicit.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q

from .models import ReminderSend

__all__ = [
    "reminder_send_search",
    "search_reminder_sends",
    "search_sends",
]

CHANNELS = tuple(value for value, _label in ReminderSend.Channel.choices)
STATUSES = tuple(value for value, _label in ReminderSend.Status.choices)


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


def search_sends(
    salon, client_name=None, *, channel=None, status=None,
    start=None, end=None, name=None, query=None, fragment=None,
    date_from=None, date_to=None, start_date=None, end_date=None,
):
    """Return ``salon``'s reminder sends matching the filters.

    Returns a list of :class:`~messaging.models.ReminderSend`,
    newest first (``-sent_at``, then ``-id``). Every filter is
    optional; with no filters the salon's whole send log is
    returned in that order. Read-only.
    """
    if salon is None or _salon_id(salon) is None:
        return []
    fragment_value = client_name
    for alias in (name, query, fragment):
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
        ReminderSend.objects.filter(client__salon_id=_salon_id(salon))
        .select_related("client", "appointment")
        .order_by("-sent_at", "-id")
    )
    if fragment_value is not None and str(fragment_value).strip():
        needle = str(fragment_value).strip()
        queryset = queryset.filter(
            Q(client__first_name__icontains=needle)
            | Q(client__last_name__icontains=needle)
        )
    if channel is not None:
        queryset = queryset.filter(channel=str(channel))
    if status is not None:
        queryset = queryset.filter(status=str(status))
    if first is not None:
        window_start = datetime.combine(first, time.min, tzinfo=tz)
        queryset = queryset.filter(sent_at__gte=window_start)
    if last is not None:
        window_end = datetime.combine(
            last + timedelta(days=1), time.min, tzinfo=tz
        )
        queryset = queryset.filter(sent_at__lt=window_end)
    return list(queryset)


def search_reminder_sends(salon, client_name=None, **kwargs):
    """Alias for :func:`search_sends`."""
    return search_sends(salon, client_name, **kwargs)


def reminder_send_search(salon, client_name=None, **kwargs):
    """Alias for :func:`search_sends`."""
    return search_sends(salon, client_name, **kwargs)
