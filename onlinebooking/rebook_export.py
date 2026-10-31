"""CSV export of rebookable appointments (backend only).

Read-only: nothing is created, updated, or deleted, and no
provider code is involved. In particular this module never
calls :func:`onlinebooking.rebook.rebook_appointment` -- that
service creates a booking; an export must not.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the appointments that
are eligible sources for a rebook -- as a list of dicts
(:func:`export_rebook`) and as a CSV string
(:func:`export_rebook_csv`) built from that same list, so the
two formats can never disagree -- one source of truth.

Rebook -- reused, never reimplemented
-------------------------------------
Eligibility comes verbatim from the source rules of
:mod:`onlinebooking.rebook`. That module is a write service
(it exposes no query to delegate a listing to), so this export
enumerates its eligible sources read-only using exactly its
two source refusals, and no others:

* a source whose status is ``Appointment.Status.CANCELLED``
  is refused by the rebook service, so it never exports;
* a source with no service (``service is None``,
  snapshot-only) is refused, so it never exports.

Every other source status (booked, confirmed, completed,
etc.) may be rebooked, so all of them export. The rebook
service's remaining checks -- the staff member's
online-booking toggle and rostered availability -- judge a
*new* slot at rebook time, not the source, so they cannot be
evaluated for an export and are not invented here. Likewise
the rebook service explicitly invents no ``past`` check
beyond the caller's choice of source, so this export applies
no time filter.

Scope and ordering
------------------
Salon-scoped on client, staff member, and the service's
category (a linked service always has a category here, since
service-less sources are excluded); an appointment of a
different salon exports nothing. With a ``client``, the
export is that client's rebookable appointments in ``salon``;
with ``client=None`` it is salon-wide. Ordered
deterministically: ``start``, then ``pk`` -- the appointment
model's own ordering, as in :mod:`onlinebooking.lookup_export`.

Columns -- only fields that exist on the models, exactly
:data:`EXPORT_FIELDNAMES`: appointment ``id``, ``salon_id``,
``client_id``, ``staff_member_id``, ``staff_name`` (the staff
member's ``display_name``), ``service_id``, ``service_name``
(``service.name`` when linked, else the ``service_name``
snapshot, ``""`` when neither exists), ``start`` / ``end``
ISO-8601 strings, ``status``, ``origin``.
"""
import csv
import io

from bookings.models import Appointment

__all__ = [
    "EXPORT_FIELDNAMES",
    "REBOOK_FIELDNAMES",
    "export_rebook",
    "export_rebook_csv",
    "export_rebookable",
    "export_rebookable_csv",
    "rebook_csv",
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
REBOOK_FIELDNAMES = EXPORT_FIELDNAMES


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


def _rebookable(salon, client):
    """Eligible rebook sources in ``salon`` (see module docstring)."""
    qs = Appointment.objects.filter(
        client__salon=salon,
        staff_member__salon=salon,
        service__category__salon=salon,
    ).exclude(
        status=Appointment.Status.CANCELLED,
    ).exclude(
        service__isnull=True,
    )
    if client is not None:
        qs = qs.filter(client=client)
    return qs.select_related(
        "client", "staff_member", "service").order_by("start", "pk")


def export_rebook(salon, client=None):
    """Return rebookable appointments as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
            ``None`` exports ``[]``.
        client: optional ``clients.Client`` instance; when
            given, only that client's rebookable appointments
            in ``salon`` export. When omitted, the export is
            salon-wide.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, ordered by ``start``, then ``pk``.
    """
    if salon is None:
        return []
    return [_record(salon, appt) for appt in _rebookable(salon, client)]


def export_rebook_csv(salon, client=None, **kwargs):
    """Return the rebook export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_rebook` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``. ``client`` may
    also be passed as a keyword.
    """
    if "client" in kwargs:
        client = kwargs.pop("client")
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_rebook(salon, client):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_rebookable = export_rebook
export_rebookable_csv = export_rebook_csv
rebook_csv = export_rebook_csv
