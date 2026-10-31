"""CSV export of online booking lookup results (backend only).

Read-only: nothing is created, updated, or deleted, and no
provider code is involved.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports a client's upcoming
online-actionable bookings -- the booking lookup/search result
-- as a list of dicts (:func:`export_lookup`) and as a CSV
string (:func:`export_lookup_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.

Gap filled
----------
Every other onlinebooking query already had a CSV export:
``slots`` -> ``slots_export``, ``cancellations`` ->
``cancellations_export``, ``history`` -> ``export_history``,
``upcoming`` -> ``export_upcoming``, ``outlook`` ->
``outlook_export``. :mod:`onlinebooking.lookup` had none
(``grep lookup onlinebooking/*export*.py`` found no import of
it). This module fills exactly that gap; it does not duplicate
:mod:`onlinebooking.export_upcoming`, which is a different
query: salon-wide, ``origin == ONLINE`` only, and excluding
only cancelled appointments.

Lookup -- reused, never reimplemented
--------------------------------------
Membership, scoping, and ordering come verbatim from
:mod:`onlinebooking.lookup`: this module calls
:func:`onlinebooking.lookup.upcoming_online_bookings` and never
queries ``Appointment`` itself for membership or order. That
service defines the lookup result as:

* ``start >= now`` (``now`` defaults to ``timezone.now()``; an
  appointment starting exactly at ``now`` counts as upcoming).
* Only ``booked`` and ``confirmed`` appointments -- the statuses
  still actionable online.
* No origin filter: an appointment carries no reliable channel
  split for this lookup, so phone / walk-in / unknown origins
  are carried through, with ``origin`` on the row.
* Salon-scoped on client, staff member, and the service's
  category; a client of a different salon exports nothing.
* Ordered soonest first: ``start``, then ``pk``.

Scope: with a ``client``, the export is that client's lookup
result in ``salon``. With ``client=None``, it is salon-wide:
the service is called once per client of the salon, its rows
merged and re-ordered by the service's own ordering
(``start``, then ``pk``) -- the same salon-wide shape as
:mod:`onlinebooking.export_history`.

Columns -- only fields that exist on the models, exactly
:data:`EXPORT_FIELDNAMES`: appointment ``id``, ``salon_id``,
``client_id``, ``staff_member_id``, ``staff_name`` (the staff
member's ``display_name``), ``service_id`` (or ``None``),
``service_name`` (``service.name`` when linked, else the
``service_name`` snapshot, ``""`` when neither exists),
``start`` / ``end`` ISO-8601 strings, ``status``, ``origin``.
"""
import csv
import io

from clients.models import Client
from onlinebooking.lookup import upcoming_online_bookings

__all__ = [
    "EXPORT_FIELDNAMES",
    "LOOKUP_FIELDNAMES",
    "export_lookup",
    "export_lookup_csv",
    "export_lookup_online_bookings",
    "export_lookup_online_bookings_csv",
    "lookup_csv",
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
]
LOOKUP_FIELDNAMES = EXPORT_FIELDNAMES


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
        "staff_name": appt.staff_member.display_name,
        "service_id": appt.service_id,
        "service_name": _service_name(appt),
        "start": appt.start.isoformat() if appt.start else None,
        "end": appt.end.isoformat() if appt.end else None,
        "status": appt.status,
        "origin": appt.origin,
    }


def export_lookup(salon, client=None, now=None):
    """Return a client's upcoming online bookings as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        client: optional ``clients.Client`` instance; when
            given, only that client's lookup result in ``salon``
            exports. When omitted, the export is salon-wide
            (see module docstring).
        now: reference instant for "upcoming" (inclusive);
            defaults inside the lookup service to
            ``timezone.now()``.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, ordered as the lookup service orders: soonest
        first (``start``, then ``pk``).
    """
    if salon is None:
        return []
    if client is not None:
        appts = list(upcoming_online_bookings(salon, client, now=now))
    else:
        appts = []
        for salon_client in Client.objects.filter(salon=salon).order_by("id"):
            appts.extend(upcoming_online_bookings(salon, salon_client, now=now))
        appts.sort(key=lambda a: (a.start, a.pk))
    return [_record(salon, appt) for appt in appts]


def export_lookup_csv(salon, client=None, now=None, **kwargs):
    """Return the lookup export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_lookup` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``. ``client`` and
    ``now`` may also be passed as keywords.
    """
    if "client" in kwargs:
        client = kwargs.pop("client")
    if "now" in kwargs:
        now = kwargs.pop("now")
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_lookup(salon, client, now=now):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_lookup_online_bookings = export_lookup
export_lookup_online_bookings_csv = export_lookup_csv
lookup_csv = export_lookup_csv
