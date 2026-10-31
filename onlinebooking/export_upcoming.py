"""CSV export of upcoming online bookings (backend only).

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one salon's upcoming
appointments whose origin is online as a list of dicts
(:func:`export_upcoming`) and as a CSV string
(:func:`export_upcoming_csv`) built from that same list, so the
two formats can never disagree -- one source of truth.

Origin -- verbatim from :mod:`onlinebooking.cancellations`:
``origin == Appointment.Origin.ONLINE`` (the online-booking
creation path sets this; phone / walk-in / unknown origins are
excluded -- see ``Appointment.origin`` in
:mod:`bookings.models`).

Upcoming -- verbatim from :mod:`onlinebooking.upcoming` and
:mod:`bookings.upcoming`:

* ``start >= now`` (``now`` defaults to
  ``django.utils.timezone.now()``; an appointment starting exactly
  at ``now`` counts as upcoming).
* Non-cancelled: only ``Appointment.Status.CANCELLED`` is
  excluded; every other status is carried through on the row.
* When ``days`` is given, the window is additionally the
  half-open interval ``[now, now + days)`` on ``start``, as in
  :mod:`bookings.upcoming`; ``days <= 0`` exports nothing.
  With no ``days``, there is no upper bound.
* Salon-scoped via both client and staff member
  (``client__salon`` and ``staff_member__salon``, as in
  :mod:`onlinebooking.cancellations`) -- never via the service,
  so a snapshot-only appointment (``service=None``) still
  exports, with its name from the ``service_name`` snapshot.

Columns -- only fields that exist on the models, exactly
:data:`EXPORT_FIELDNAMES`:

- ``id``: appointment pk; ``salon_id``: the scoped salon's pk.
- ``client_id`` / ``staff_member_id``: client / staff pks.
- ``service_id``: service pk or ``None``; ``service_name``:
  ``service.name`` when linked, else the ``service_name``
  snapshot (``""`` when neither exists).
- ``start``: ISO-8601 string, as stored.
- ``status`` / ``origin``: the appointment's stored values.

Ordering is deterministic: by ``start``, then ``id``.
"""
import csv
import io
from datetime import timedelta

from django.utils import timezone

from bookings.models import Appointment

__all__ = [
    "EXPORT_FIELDNAMES",
    "UPCOMING_FIELDNAMES",
    "export_upcoming",
    "export_upcoming_csv",
    "export_upcoming_online_bookings",
    "export_upcoming_online_bookings_csv",
    "upcoming_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "client_id",
    "staff_member_id",
    "service_id",
    "service_name",
    "start",
    "status",
    "origin",
]
UPCOMING_FIELDNAMES = EXPORT_FIELDNAMES


def _service_name(appt):
    if appt.service is not None:
        return appt.service.name
    return appt.service_name or ""


def _record(salon, appt):
    return {
        "id": appt.pk,
        "salon_id": salon.pk if salon is not None else appt.client.salon_id,
        "client_id": appt.client_id,
        "staff_member_id": appt.staff_member_id,
        "service_id": appt.service_id,
        "service_name": _service_name(appt),
        "start": appt.start.isoformat() if appt.start else None,
        "status": appt.status,
        "origin": appt.origin,
    }


def export_upcoming(salon, now=None, days=None, *, start=None,
                    horizon_days=None):
    """Return ``salon``'s upcoming online appointments as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to. ``None``
            exports ``[]``.
        now: reference instant for "upcoming" (inclusive);
            defaults to ``timezone.now()``. ``start`` is an alias.
        days: optional horizon in days; when given, only
            ``start < now + days`` exports and ``days <= 0``
            exports ``[]``. ``horizon_days`` is an alias and wins.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, ordered by ``start``, then ``id``.
    """
    if horizon_days is not None:
        days = horizon_days
    if now is None:
        now = start
    if salon is None:
        return []
    now = now or timezone.now()
    if days is not None:
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = None
    if days is not None and days <= 0:
        return []
    qs = (
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
            origin=Appointment.Origin.ONLINE,
            start__gte=now,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("client", "staff_member", "service")
        .order_by("start", "id")
    )
    if days is not None:
        qs = qs.filter(start__lt=now + timedelta(days=days))
    return [_record(salon, appt) for appt in qs]


def export_upcoming_csv(salon, now=None, days=None, **kwargs):
    """Return the upcoming online export for ``salon`` as CSV.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_upcoming` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_upcoming(salon, now, days, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_upcoming_online_bookings = export_upcoming
export_upcoming_online_bookings_csv = export_upcoming_csv
upcoming_csv = export_upcoming_csv
