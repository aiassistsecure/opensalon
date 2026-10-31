"""Appointment export service for a date range.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports one salon's appointments in a
date range as a plain, JSON-serializable list of dicts — one dict
per appointment, with exactly :data:`EXPORT_FIELDNAMES` keys:

- ``id``: the appointment's pk.
- ``client_id`` / ``staff_member_id``: the client / staff member pks.
- ``service_id``: the price-book service pk, or ``None`` when the
  appointment carries no service (see ``service_name``).
- ``service_name``: resolved exactly as the day book resolves it
  (:mod:`bookings.daybook`) — the live ``Service.name`` when a
  service is linked, otherwise the appointment's stored
  ``service_name`` snapshot, so snapshot-only appointments (service
  FK null, e.g. an imported service absent from the price book)
  still export with their name.
- ``start`` / ``end``: ISO-8601 strings, as stored.
- ``status``: the ``Appointment.status`` value.
- ``price``: see below.

Price: ``Appointment`` stores no price (the import path documents
the same: the source price is not stored), so there is no charged
amount to export. ``price`` is therefore the *current* price-book
price for the appointment's service at the staff member's staff
level — the active ``ServicePrice`` for (service, staff level),
formatted to two decimal places as a string (``"85.00"``, as in
:mod:`catalog.export`, because ``Decimal`` is not
JSON-serializable). It is ``None`` when no such price exists: the
appointment has no service, the staff member has no staff level,
or no active price is entered for that pair. It is a price-book
lookup, never a historical amount charged, and never a float.

Scoping follows :mod:`bookings.search` and
:mod:`bookings.status_counts`: appointments belong to the salon via
both the client and the staff member (``client__salon`` and
``staff_member__salon``), never via the service, so snapshot-only
appointments are included.

Range: membership is by the appointment's ``start`` on a salon-local
date, in the salon's timezone (``bookings.availability._tz``, the
same handling the day book uses): the window is [start of
``date_from``, start of the day after ``date_to``) in that timezone.
Both bounds are inclusive local dates; datetimes are reduced to
their date in the salon timezone. An appointment spanning midnight
exports once, on the day it starts. A reversed range exports ``[]``.

Cancelled: cancelled appointments ARE included by default — an exit
export must be complete, and ``status`` is carried on every row so
callers can filter. Pass ``include_cancelled=False`` for the
day-book rule (cancelled appointments do not occupy the book).
Every other status is always included.

Ordering is deterministic: by ``start``, then ``id``.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from bookings.availability import _tz
from bookings.models import Appointment
from saloncore.models import ServicePrice

__all__ = ["EXPORT_FIELDNAMES", "export_appointments"]

#: Key order of every exported row.
EXPORT_FIELDNAMES = [
    "id",
    "client_id",
    "staff_member_id",
    "service_id",
    "service_name",
    "start",
    "end",
    "status",
    "price",
]

_ZERO = Decimal("0.00")


def _money(value):
    return str(Decimal(value).quantize(_ZERO))


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def export_appointments(salon, date_from, date_to=None, *, include_cancelled=True):
    """Return ``salon``'s appointments in a date range as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to. ``None``
            exports ``[]`` (an export is always one salon's book).
        date_from: first local date of the range, inclusive (a
            ``date``, or a datetime reduced to its date in the
            salon's timezone).
        date_to: last local date of the range, inclusive; defaults
            to ``date_from`` (a single-day export).
        include_cancelled: when True (default), cancelled
            appointments are included; when False they are excluded.
            See the module docstring for the rationale.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, ordered by ``start``, then ``id``. An empty or
        reversed range exports as ``[]``.
    """
    if salon is None or date_from is None:
        return []
    tz = _tz(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return []
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)

    appointments = (
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            start__gte=window_start, start__lt=window_end,
        )
        .select_related("service", "staff_member")
        .order_by("start", "id")
    )
    if not include_cancelled:
        appointments = appointments.exclude(status=Appointment.Status.CANCELLED)
    appointments = list(appointments)

    # One price-book query for every (service, staff level) pair in
    # the range, rather than a lookup per appointment.
    prices = {}
    pairs = {
        (appt.service_id, appt.staff_member.staff_level_id)
        for appt in appointments
        if appt.service_id is not None
        and appt.staff_member.staff_level_id is not None
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
        amount = prices.get((appt.service_id, appt.staff_member.staff_level_id))
        rows.append({
            "id": appt.pk,
            "client_id": appt.client_id,
            "staff_member_id": appt.staff_member_id,
            "service_id": appt.service_id,
            "service_name": (
                appt.service.name if appt.service else appt.service_name
            ),
            "start": appt.start.isoformat() if appt.start else None,
            "end": appt.end.isoformat() if appt.end else None,
            "status": appt.status,
            "price": _money(amount) if amount is not None else None,
        })
    return rows
