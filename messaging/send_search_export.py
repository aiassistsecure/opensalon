"""Read-only reminder-send search CSV export service (L8-M14).

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, stored, or mutated here, and no provider adapter is
touched.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing L8-M10 send
search (:mod:`messaging.send_search`) as a plain list of dicts
(:func:`export_search_sends`) and as a CSV string
(:func:`export_search_sends_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.
The search itself is never reimplemented here: every row comes
verbatim from :func:`messaging.send_search.search_sends`,
called with the same arguments, and each row is rendered by
:func:`messaging.send_export.send_export_row`, the record row
renderer the L8-M9 export already uses. No re-querying, no
recounting, and no invented fields.

Columns -- exactly :data:`messaging.send_export.RECORD_FIELDNAMES`,
the real ``ReminderSend`` fields the send export already
exposes: ``id``, ``salon_id`` (the send's client's salon, the
scoping the search service uses), ``appointment_id``,
``client_id``, ``channel``, ``status``, ``sent_at`` (ISO-8601),
``detail``. No client name, email, or phone is exported -- the
search term matches on the client's name in the search service,
but names themselves are not a column here.

Filter semantics follow the search service verbatim: the
search term is the service's ``client_name`` fragment
(case-insensitive, matched against the client's first OR last
name; ``term`` / ``query`` / ``name`` / ``fragment`` accepted
as aliases). A blank or omitted term means no name filter, so
the salon's whole send log is exported. The optional
``channel``, ``status``, and inclusive local-day ``start`` /
``end`` filters (with the search service's own date aliases)
are passed through unchanged, and the service's errors
propagate unchanged (e.g. ``ValueError`` for a reversed
range). Only the given salon's sends are ever exported; a
missing salon exports as ``[]`` / the CSV header row alone.

Ordering is deterministic and matches the service: newest
first (``-sent_at``, then ``-id``). No match exports as ``[]``
/ the CSV header row alone, never ``None``. Lines end with
``"\\n"``. Core stays provider-agnostic -- no provider SDK,
field, or name appears here.
"""
import csv
import io

from .send_export import RECORD_FIELDNAMES, send_export_row
from .send_search import search_sends

__all__ = [
    "EXPORT_FIELDNAMES",
    "SEARCH_EXPORT_FIELDNAMES",
    "export_search_sends",
    "export_search_sends_csv",
    "export_send_search",
    "export_send_search_csv",
    "search_export_row",
    "search_sends_csv",
    "send_search_export_row",
]

#: Column / key order shared by the dict export and the CSV
#: export -- the send export's record fieldnames, verbatim.
EXPORT_FIELDNAMES = list(RECORD_FIELDNAMES)
SEARCH_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES


def _resolve_term(term, kwargs):
    """Fold the term aliases into one search fragment value."""
    value = term
    for alias in ("client_name", "query", "name", "fragment"):
        candidate = kwargs.pop(alias, None)
        if value is None:
            value = candidate
    return value


def export_search_sends(salon, term=None, *, channel=None,
                        status=None, start=None, end=None, **kwargs):
    """Return ``salon``'s sends matching the search, as dicts.

    ``term`` and every filter are passed verbatim to
    :func:`messaging.send_search.search_sends` (the term as its
    ``client_name`` fragment); rows are rendered from its
    results in its own order (newest first) by the send
    export's row renderer. No match is ``[]``. The service's
    errors propagate. Read-only.
    """
    fragment = _resolve_term(term, kwargs)
    sends = search_sends(
        salon, fragment, channel=channel, status=status,
        start=start, end=end, **kwargs,
    )
    return [send_export_row(send) for send in sends]


def export_search_sends_csv(salon, term=None, *, channel=None,
                            status=None, start=None, end=None,
                            **kwargs):
    """Return :func:`export_search_sends` with same args as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_search_sends` with the same
    arguments, so the CSV and list exports always agree. No
    match exports as the header row alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_search_sends(
        salon, term, channel=channel, status=status, start=start,
        end=end, **kwargs,
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Row alias: rows are the send export's rows, verbatim.
search_export_row = send_export_row
send_search_export_row = send_export_row

#: Aliases, mirroring the naming convenience in sibling services.
export_send_search = export_search_sends
export_send_search_csv = export_search_sends_csv
search_sends_csv = export_search_sends_csv
