"""Client appointment-history CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one client's appointment
history as a plain, JSON-serializable list of dicts
(:func:`export_client_history`) and as a CSV string
(:func:`export_client_history_csv`) built from that same list,
so the two formats can never disagree — one source of truth.

Delegation: history membership and ordering are
:mod:`bookings.client_history`'s alone and are reused verbatim
via :func:`bookings.client_history.client_appointments`; this
module never re-queries appointments for membership or
re-orders rows. Ordering is exactly the service's: full history
newest first (``-start``, ``-pk``); with ``upcoming_only=True``,
only ``start >= now``, soonest first (``start``, ``pk``).

Salon scoping: the export is scoped to one salon and one client
of that salon. A client whose salon does not match the given
salon exports as ``[]`` / a header-only CSV, so one salon's
export can never carry another salon's client history.

Columns are only real ``Appointment`` fields, plus ``price``
exactly as defined in :mod:`bookings.export`:

- ``id``: the appointment's pk.
- ``salon_id``: the salon the export was scoped to.
- ``client_id`` / ``client_name``: the client pk and display
  name (``str(client)``).
- ``staff_member_id`` / ``staff_name``: staff pk / display name.
- ``service_id`` / ``service_name``: the linked service pk
  (``None`` for snapshot-only appointments) and the name resolved
  as the service / day book resolve it — live ``Service.name``,
  otherwise the stored ``service_name`` snapshot.
- ``start`` / ``end``: ISO-8601 strings, as stored.
- ``status`` / ``origin``: the appointment's stored values.
- ``price``: the *current* price-book price for the service at
  the staff member's staff level (active ``ServicePrice``),
  formatted to two decimal places as a string, because
  ``Decimal`` is not JSON-serializable and money is never a
  float. ``None`` when no such price exists. It is a price-book
  lookup, never a historical amount charged.

No notes are exported: appointment notes and persistent client
record notes are two kinds that never blur, and neither kind
belongs in an appointment-history export. No client contact
details (email, phone, address) are included.

Date window: ``start_date`` / ``end_date`` are optional
inclusive local dates filtered on the appointment's ``start``
in the salon's timezone (the :mod:`bookings.note_export` /
:mod:`bookings.breaks` convention) -- the window is [start of
``start_date``, start of the day after ``end_date``). Either
bound may be given alone (an open-ended window); datetimes are
reduced to their salon-local date. Both default ``None``, which
is exactly the previous unbounded output, byte-identical. A
reversed window exports as ``[]`` / a header-only CSV. The
window composes with the ``client`` and ``upcoming_only``
parameters: membership and ordering still come from
:mod:`bookings.client_history` alone, and the window only drops
rows whose ``start`` falls outside it.
"""
import csv
import datetime
import io
from decimal import Decimal

from bookings.availability import _tz
from bookings.client_history import client_appointments
from saloncore.models import ServicePrice

__all__ = [
    "CLIENT_HISTORY_EXPORT_FIELDNAMES",
    "CLIENT_HISTORY_FIELDNAMES",
    "export_client_history",
    "export_client_history_csv",
    "export_client_history_rows",
    "client_history_rows",
    "client_history_csv",
]

#: Column / key order shared by the dict export and the CSV export.
CLIENT_HISTORY_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "client_id",
    "client_name",
    "staff_member_id",
    "staff_name",
    "service_id",
    "service_name",
    "start",
    "end",
    "status",
    "origin",
    "price",
]
CLIENT_HISTORY_FIELDNAMES = CLIENT_HISTORY_EXPORT_FIELDNAMES

_ZERO = Decimal("0.00")


def _money(value):
    return str(Decimal(value).quantize(_ZERO))


def _resolve(salon, client):
    """Resolve the (salon, client) pair, supporting (client,) form."""
    if client is None and salon is not None and hasattr(salon, "first_name"):
        # Called as export_client_history(client): the salon is
        # the client's own salon.
        client, salon = salon, salon.salon
    if salon is None and client is not None:
        salon = client.salon
    return salon, client


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


def export_client_history(salon, client=None, upcoming_only=False, now=None,
                          start_date=None, end_date=None):
    """Return one client's appointment-history rows as dicts.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
        client: ``clients.Client`` instance whose history is
            exported; must belong to ``salon``. May be passed as
            the sole positional argument, in which case the
            salon is the client's own salon.
        upcoming_only / now: passed through unchanged to
            :func:`bookings.client_history.client_appointments`.
        start_date / end_date: optional inclusive local dates
            bounding the appointment ``start`` (see the module
            docstring); both default ``None`` = unbounded, the
            previous output verbatim.

    Returns:
        A list of dicts with exactly
        :data:`CLIENT_HISTORY_EXPORT_FIELDNAMES` keys, in the
        history service's ordering. A missing salon/client or a
        salon/client mismatch exports as ``[]``.
    """
    salon, client = _resolve(salon, client)
    if salon is None or client is None or client.salon_id != salon.pk:
        return []
    appointments = list(
        client_appointments(client, upcoming_only=upcoming_only, now=now)
    )
    if start_date is not None or end_date is not None:
        appointments = [
            appt for appt in appointments
            if _in_window(appt.start, salon, start_date, end_date)
        ]
    # One price-book query for every (service, staff level) pair,
    # as in bookings.export, rather than a lookup per appointment.
    prices = {}
    pairs = {
        (appt.service_id, appt.staff_member.staff_level_id)
        for appt in appointments
        if appt.service_id is not None
        and getattr(appt.staff_member, "staff_level_id", None) is not None
    }
    if pairs:
        price_rows = ServicePrice.objects.filter(active=True).filter(
            service_id__in={service_id for service_id, _ in pairs},
            staff_level_id__in={level_id for _, level_id in pairs},
        )
        for row in price_rows:
            if (row.service_id, row.staff_level_id) in pairs:
                prices[(row.service_id, row.staff_level_id)] = row.amount
    rows = []
    for appt in appointments:
        amount = prices.get(
            (appt.service_id, appt.staff_member.staff_level_id)
        )
        rows.append({
            "id": appt.pk,
            "salon_id": salon.pk,
            "client_id": appt.client_id,
            "client_name": str(appt.client),
            "staff_member_id": appt.staff_member_id,
            "staff_name": appt.staff_member.display_name,
            "service_id": appt.service_id,
            "service_name": (
                appt.service.name if appt.service else appt.service_name
            ),
            "start": appt.start.isoformat() if appt.start else None,
            "end": appt.end.isoformat() if appt.end else None,
            "status": appt.status,
            "origin": appt.origin,
            "price": _money(amount) if amount is not None else None,
        })
    return rows


def export_client_history_csv(salon, client=None, upcoming_only=False, now=None,
                              start_date=None, end_date=None):
    """Return one client's appointment history as a CSV string.

    Arguments are the same as :func:`export_client_history`.
    The header row is :data:`CLIENT_HISTORY_EXPORT_FIELDNAMES`
    and every data row comes from :func:`export_client_history`
    with the same arguments, so the CSV and list exports always
    agree. An empty history exports as the header row alone.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLIENT_HISTORY_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in export_client_history(
        salon, client, upcoming_only=upcoming_only, now=now,
        start_date=start_date, end_date=end_date,
    ):
        writer.writerow({
            name: ("" if row[name] is None else row[name])
            for name in CLIENT_HISTORY_EXPORT_FIELDNAMES
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_client_history_rows = export_client_history
client_history_rows = export_client_history
client_history_csv = export_client_history_csv
