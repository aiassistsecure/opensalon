"""CSV export of online booking history (backend only).

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports past online bookings as a
list of dicts (:func:`export_history`) and as a CSV string
(:func:`export_history_csv`) built from that same list, so the
two formats can never disagree -- one source of truth.

History -- reused, never reimplemented
---------------------------------------
Membership, scoping, and ordering come verbatim from
:mod:`onlinebooking.history`: this module calls
:func:`onlinebooking.history.past_bookings` and never queries
``Appointment`` itself for membership or order. That service
defines history as:

* ``start < now`` (``now`` defaults to ``timezone.now()``; an
  appointment starting exactly at ``now`` is upcoming, not past).
* Cancelled bookings INCLUDED, flagged per row via
  ``is_cancelled``.
* Salon-scoped on client and staff member (and, when a service
  is linked, on the service's category); a snapshot-only
  appointment (``service=None``) still exports, its name from
  the ``service_name`` snapshot as resolved by the service.
* Ordered newest first: ``-start``, then ``-pk``.

Online origin -- the one filter this export adds on top: only
rows whose stored appointment origin is
``Appointment.Origin.ONLINE`` export (the online-booking creation
path sets this; phone / walk-in / unknown origins are excluded --
same origin rule as :mod:`onlinebooking.export_upcoming`). The
history service itself returns the client's appointments
regardless of origin, so filtering its rows here keeps the
history definition in exactly one place.

Scope: with a ``client``, the export is that client's history in
``salon`` (the service's own scope). With ``client=None``, it is
the salon-wide history: the service is called once per client of
the salon, its rows merged and re-ordered by the service's own
ordering (``-start``, then ``-pk``).

Columns -- only fields that exist on the models / service rows,
exactly :data:`EXPORT_FIELDNAMES`: appointment ``id``,
``salon_id``, ``client_id``, ``staff_member_id``, ``staff_name``
(the service row's ``staff_display_name``), ``service_id``
(or ``None``), ``service_name`` (as resolved by the service),
``start`` / ``end`` ISO-8601 strings, ``status``, ``origin``,
and ``is_cancelled`` (the service row's flag).

Date window: ``start_date`` / ``end_date`` are optional
inclusive local dates filtered on the booking's ``start``
in the salon's timezone (the
:mod:`bookings.client_history_export` convention) -- the
window is [start of ``start_date``, start of the day after
``end_date``). Either bound may be given alone (an open-ended
window); datetimes are reduced to their salon-local date.
Both default ``None``, which is exactly the previous unbounded
output, byte-identical. A reversed window exports as ``[]`` /
a header-only CSV. The window composes with the ``client``,
``now``, and ``limit`` parameters (it applies before
``limit``): membership and ordering still come from
:mod:`onlinebooking.history` alone, and the window only drops
rows whose ``start`` falls outside it.
"""
import csv
import datetime
import io

from bookings.availability import _tz
from bookings.models import Appointment
from clients.models import Client
from onlinebooking.history import past_bookings

__all__ = [
    "EXPORT_FIELDNAMES",
    "HISTORY_FIELDNAMES",
    "export_history",
    "export_history_csv",
    "export_history_online_bookings",
    "export_history_online_bookings_csv",
    "export_booking_history",
    "export_booking_history_csv",
    "history_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "client_id",
    "staff_member_id",
    "staff_name",
    "service_id",
    "service_name",
    "start",
    "end",
    "status",
    "origin",
    "is_cancelled",
]
HISTORY_FIELDNAMES = EXPORT_FIELDNAMES


def _record(salon, row):
    appt = row.appointment
    return {
        "id": appt.pk,
        "salon_id": salon.pk if salon is not None else appt.client.salon_id,
        "client_id": appt.client_id,
        "staff_member_id": appt.staff_member_id,
        "staff_name": row.staff_display_name,
        "service_id": appt.service_id,
        "service_name": row.service_name,
        "start": row.start.isoformat() if row.start else None,
        "end": row.end.isoformat() if row.end else None,
        "status": appt.status,
        "origin": appt.origin,
        "is_cancelled": row.is_cancelled,
    }


def _as_local_date(value, tz):
    """Reduce a date / datetime / ISO string to a local date."""
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        parsed = datetime.datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        return parsed.astimezone(tz).date() if parsed.tzinfo else parsed.date()


def _in_window(start, salon, start_date, end_date):
    """True when ``start`` is inside the optional date window."""
    if start is None:
        return start_date is None and end_date is None
    tz = _tz(salon)
    if start_date is not None:
        first = _as_local_date(start_date, tz)
        window_start = datetime.datetime.combine(
            first, datetime.time.min, tzinfo=tz)
        if start < window_start:
            return False
    if end_date is not None:
        last = _as_local_date(end_date, tz)
        window_end = datetime.datetime.combine(
            last + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
        if start >= window_end:
            return False
    return True


def _online_rows(salon, client, now, limit, start_date=None, end_date=None):
    rows = past_bookings(salon, client, now=now, limit=limit)
    rows = [r for r in rows if r.appointment.origin == Appointment.Origin.ONLINE]
    if start_date is not None or end_date is not None:
        rows = [
            r for r in rows
            if _in_window(r.start, salon, start_date, end_date)
        ]
    return rows


def export_history(salon, client=None, now=None, limit=None,
                   start_date=None, end_date=None):
    """Return past online bookings as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        client: optional ``clients.Client`` instance; when given,
            only that client's history in ``salon`` exports. When
            omitted, the export is salon-wide (see module docstring).
        now: reference instant for "past"; defaults inside the
            history service to ``timezone.now()``.
        limit: maximum rows; defaults to ``None`` (full history --
            an export is complete). Forwarded to the history
            service per client; in the salon-wide scope it caps
            the merged result after ordering. A non-positive
            limit exports ``[]``.
        start_date / end_date: optional inclusive local dates
            bounding the booking ``start`` (see the module
            docstring); both default ``None`` = unbounded, the
            previous output verbatim. The window applies before
            ``limit``.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, ordered as the history service orders: newest
        first (``-start``, then ``-pk``).
    """
    if salon is None:
        return []
    if limit is not None and limit <= 0:
        return []
    windowed = start_date is not None or end_date is not None
    if client is not None:
        rows = _online_rows(
            salon, client, now, None if windowed else limit,
            start_date=start_date, end_date=end_date)
        if windowed and limit is not None:
            rows = rows[:limit]
    else:
        rows = []
        for salon_client in Client.objects.filter(salon=salon).order_by("id"):
            rows.extend(_online_rows(
                salon, salon_client, now, None,
                start_date=start_date, end_date=end_date))
        rows.sort(key=lambda r: (r.start, r.appointment.pk), reverse=True)
        if limit is not None:
            rows = rows[:limit]
    return [_record(salon, row) for row in rows]


def export_history_csv(salon, client=None, now=None, limit=None,
                       start_date=None, end_date=None, **kwargs):
    """Return the history export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_history` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``. ``client``,
    ``now``, ``limit``, ``start_date``, and ``end_date`` may
    also be passed as keywords.
    """
    if "client" in kwargs:
        client = kwargs.pop("client")
    if "now" in kwargs:
        now = kwargs.pop("now")
    if "limit" in kwargs:
        limit = kwargs.pop("limit")
    if "start_date" in kwargs:
        start_date = kwargs.pop("start_date")
    if "end_date" in kwargs:
        end_date = kwargs.pop("end_date")
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_history(
            salon, client, now=now, limit=limit,
            start_date=start_date, end_date=end_date):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_history_online_bookings = export_history
export_history_online_bookings_csv = export_history_csv
export_booking_history = export_history
export_booking_history_csv = export_history_csv
history_csv = export_history_csv
