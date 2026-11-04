"""Campaign audience CSV export service for the messaging app.

Backend only -- no views, templates, or UI. Read-only and
export only: this service never sends, dispatches, creates,
edits, or deletes anything, and touches no provider adapter.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: the rows come from
:func:`messaging.campaigns.audience_queryset` called with the
campaign unchanged -- this module does not re-implement the
audience rule (the campaign channel's opt-in flag, ``active``
clients only, the campaign's salon only) or the ordering (the
audience service returns ``Client``'s default order:
``last_name``, then ``first_name``). The counts printed by the
create / discard / send campaign commands count exactly this
queryset; this module exports the list those counts count. The
CSV string is built from the dict list returned by
:func:`export_campaign_audience`, so the two formats can never
disagree.

Columns follow the clients app's export conventions
(``clients.export`` / ``clients.optin_export``): the client's
scalar fields in that order -- ``id``, ``salon_id``,
``external_id``, ``first_name``, ``last_name``, ``email``,
``phone``, ``sms_opt_in``, ``email_opt_in``, ``active``,
``created_at`` (ISO-8601). The nested record notes and the
verbatim source ``payload`` are not audience fields: the full
client record stays in ``clients.export``, unchanged. An empty
audience exports as ``[]`` / the header row alone. No provider
SDK, field, or name appears here.
"""
import csv
import io

from .campaigns import audience_queryset

__all__ = [
    "AUDIENCE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "audience_export_row",
    "campaign_audience_csv",
    "export_campaign_audience",
    "export_campaign_audience_csv",
]

#: Column / key order shared by the dict export and the CSV export.
AUDIENCE_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "external_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "sms_opt_in",
    "email_opt_in",
    "active",
    "created_at",
]
EXPORT_FIELDNAMES = AUDIENCE_EXPORT_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def audience_export_row(client):
    """Return one audience ``client`` as a row dict."""
    return {
        "id": client.pk,
        "salon_id": client.salon_id,
        "external_id": client.external_id,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "sms_opt_in": bool(client.sms_opt_in),
        "email_opt_in": bool(client.email_opt_in),
        "active": bool(client.active),
        "created_at": _dt(client.created_at),
    }


def export_campaign_audience(campaign):
    """Return ``campaign``'s audience as a list of dicts.

    Each entry is one client from
    :func:`messaging.campaigns.audience_queryset` -- the
    opted-in, active, salon-scoped clients the campaign would
    reach -- as a dict with exactly
    :data:`AUDIENCE_EXPORT_FIELDNAMES` keys, in the audience
    service's own order. Read-only; sends nothing.
    """
    return [audience_export_row(client)
            for client in audience_queryset(campaign)]


def export_campaign_audience_csv(campaign):
    """Return ``campaign``'s audience as a CSV string.

    The header row is :data:`AUDIENCE_EXPORT_FIELDNAMES` and
    every data row is rendered from
    :func:`export_campaign_audience` with the same argument, so
    the CSV and the dict export can never disagree. Lines end
    with ``"\\n"``. Read-only; sends nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=AUDIENCE_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_campaign_audience(campaign):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
campaign_audience_csv = export_campaign_audience_csv
