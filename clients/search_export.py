"""Client search CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client, and never
sends anything.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: every row comes from
:func:`clients.search.search_clients` called with exactly the
arguments given here (``salon`` and ``query`` are passed through
unchanged) -- this module does not re-implement the matching
rule, the case-insensitive substring logic, the salon scoping,
or the ordering. The CSV string is built from the dict list
returned by :func:`export_search_results`, so the two formats
can never disagree.

Columns are only what ``search_clients`` actually exposes: the
client id (``client_id``) and the fields the search matches
against -- ``first_name``, ``last_name``, ``email``, and
``phone``. No invented fields are included.
"""
import csv
import io

from clients.search import search_clients

__all__ = [
    "SEARCH_FIELDNAMES",
    "export_search_results",
    "export_client_search",
    "export_search_results_csv",
    "export_client_search_csv",
    "export_search_csv",
    "search_csv",
]

#: Column / key order shared by the dict export and the CSV export.
SEARCH_FIELDNAMES = [
    "client_id",
    "first_name",
    "last_name",
    "email",
    "phone",
]


def _record(client):
    return {
        "client_id": client.pk,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
    }


def export_search_results(salon, query=None):
    """Return ``salon``'s clients matching ``query`` as dicts.

    Arguments are exactly those of
    :func:`clients.search.search_clients` and are passed through
    to it unchanged: ``salon`` scopes the search to one salon
    (required) and ``query`` is the search text (an empty,
    whitespace-only, or ``None`` query returns all of the
    salon's clients). Each entry is a dict with exactly
    :data:`SEARCH_FIELDNAMES` keys, in the service's order
    (``last_name``, ``first_name``, ``pk``). No matches exports
    as ``[]``.
    """
    return [_record(client) for client in search_clients(salon, query)]


def export_search_results_csv(salon, query=None):
    """Return ``salon``'s clients matching ``query`` as CSV.

    Arguments are the same as :func:`export_search_results`
    (and therefore the same as ``search_clients``). The header
    row is :data:`SEARCH_FIELDNAMES` and every data row comes
    from :func:`export_search_results` with the same arguments,
    so the CSV and list exports always agree. No matches exports
    as the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SEARCH_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_search_results(salon, query):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_client_search = export_search_results
export_client_search_csv = export_search_results_csv
export_search_csv = export_search_results_csv
search_csv = export_search_results_csv
