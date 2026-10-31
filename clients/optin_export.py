"""Client reminder opt-in CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's clients' opt-in state
as a plain, JSON-serializable list of dicts
(:func:`export_optins`) and as a CSV string
(:func:`export_optins_csv`) built from that same list, so the two
formats can never disagree -- one source of truth.

Opt-ins exactly as stored: ``Client`` carries a single flag per
channel -- ``sms_opt_in`` and ``email_opt_in`` -- and each flag
gates both marketing and appointment reminders on that channel
(see ``clients.optins`` and ``clients.export``). This export
therefore reports exactly those two stored flags; it does not
invent separate marketing/reminder flags.

Counts summary: :func:`summarize_optins` derives every count from
a rows list (the same dicts the CSV is built from), and
:func:`export_optin_summary` applies it to
:func:`export_optins`'s output, so the summary can never disagree
with the exported rows -- it is never computed by separate queries.

Ordering is deterministic: ``last_name``, then ``first_name``,
then ``id``, matching ``Client``'s model ordering (tightened with
the ``id`` tie-break used by ``clients.export_all``).
"""
import csv
import io

from clients.models import Client

__all__ = [
    "OPTIN_FIELDNAMES",
    "export_optins",
    "export_optins_csv",
    "summarize_optins",
    "export_optin_summary",
    "optins_csv",
    "optin_summary",
]

#: Column / key order shared by the dict export and the CSV export.
OPTIN_FIELDNAMES = [
    "id",
    "salon_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "sms_opt_in",
    "email_opt_in",
    "active",
]


def _record(client):
    return {
        "id": client.pk,
        "salon_id": client.salon_id,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "sms_opt_in": bool(client.sms_opt_in),
        "email_opt_in": bool(client.email_opt_in),
        "active": bool(client.active),
    }


def export_optins(salon):
    """Return ``salon``'s clients' opt-in state as a list of dicts.

    Each entry is a dict with exactly :data:`OPTIN_FIELDNAMES`
    keys. Only ``salon``'s clients are included, ordered by
    (``last_name``, ``first_name``, ``id``). An empty client book
    exports as ``[]``.
    """
    clients = Client.objects.filter(salon=salon).order_by(
        "last_name", "first_name", "id"
    )
    return [_record(client) for client in clients]


def summarize_optins(records):
    """Return opt-in counts derived from ``records`` alone.

    ``records`` is a list as returned by :func:`export_optins`.
    Keys: ``total``, ``sms_opt_in``, ``email_opt_in``,
    ``both_opt_in``, ``sms_only``, ``email_only``, and
    ``neither_opt_in``. The four combination counts sum to
    ``total``, and each channel count is its ``*_only`` count
    plus ``both_opt_in`` -- by construction from the rows.
    """
    summary = {
        "total": 0,
        "sms_opt_in": 0,
        "email_opt_in": 0,
        "both_opt_in": 0,
        "sms_only": 0,
        "email_only": 0,
        "neither_opt_in": 0,
    }
    for record in records:
        sms = bool(record["sms_opt_in"])
        email = bool(record["email_opt_in"])
        summary["total"] += 1
        if sms:
            summary["sms_opt_in"] += 1
        if email:
            summary["email_opt_in"] += 1
        if sms and email:
            summary["both_opt_in"] += 1
        elif sms:
            summary["sms_only"] += 1
        elif email:
            summary["email_only"] += 1
        else:
            summary["neither_opt_in"] += 1
    return summary


def export_optin_summary(salon):
    """Return the opt-in counts summary for ``salon``.

    Computed by :func:`summarize_optins` over
    :func:`export_optins` ``(salon)``, so it is consistent with
    the exported rows by construction.
    """
    return summarize_optins(export_optins(salon))


def export_optins_csv(salon):
    """Return ``salon``'s clients' opt-in state as a CSV string.

    The header row is :data:`OPTIN_FIELDNAMES` and every data row
    comes from :func:`export_optins` with the same argument, so
    the CSV and list exports always agree. An empty client book
    exports as the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=OPTIN_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_optins(salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
optins_csv = export_optins_csv
optin_summary = export_optin_summary
