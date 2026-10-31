"""Rebooking candidates CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or appointment,
and never sends anything. This is a report export, not marketing:
there is deliberately no messaging, no opt-in handling, and no
provider code of any kind here.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: the rows come from
:func:`clients.rebooking.rebooking_candidates` called with exactly
the arguments given here (``salon``, ``reference_date``,
``lookback_days`` and ``window_days`` are passed through
unchanged) -- this module does not re-implement the candidacy
rule, the visit definition, the window boundary, the future-booking
exclusion, the ordering, or the salon scoping. The CSV string is
built from the dict list returned by
:func:`export_rebooking_candidates`, so the two formats can never
disagree.

Columns are only what ``rebooking_candidates`` actually exposes:
the client id (``client_id``), the client's name (``first_name`` /
``last_name``, via the row's ``client``), the last visit date
(``last_visit_date``) and ``days_since_last_visit``. No contact
details (no email, no phone) and no invented fields are included.
"""
import csv
import io

from clients.rebooking import DEFAULT_LOOKBACK_DAYS, rebooking_candidates

__all__ = [
    "REBOOKING_FIELDNAMES",
    "export_rebooking_candidates",
    "export_rebooking_csv",
    "export_rebooking_candidates_csv",
    "rebooking_csv",
]

#: Column / key order shared by the dict export and the CSV export.
REBOOKING_FIELDNAMES = [
    "client_id",
    "first_name",
    "last_name",
    "last_visit_date",
    "days_since_last_visit",
]


def _record(row):
    last_date = row.last_visit_date
    return {
        "client_id": row.client_id,
        "first_name": row.client.first_name,
        "last_name": row.client.last_name,
        "last_visit_date": (
            last_date.isoformat() if last_date is not None else None
        ),
        "days_since_last_visit": row.days_since_last_visit,
    }


def export_rebooking_candidates(salon, reference_date=None,
                                lookback_days=DEFAULT_LOOKBACK_DAYS, *,
                                window_days=None):
    """Return rebooking candidates as a list of dicts.

    Arguments are exactly those of
    :func:`clients.rebooking.rebooking_candidates` and are passed
    through to it unchanged: ``salon`` scopes the report to one
    salon (required), ``reference_date`` is the reference date,
    ``lookback_days`` sets the window, and ``window_days``, when
    given, takes precedence as its alias. Each entry is a dict
    with exactly :data:`REBOOKING_FIELDNAMES` keys, in the order
    ``rebooking_candidates`` returns its rows (last visit oldest
    first, then client id). No candidates exports as ``[]``.
    """
    rows = rebooking_candidates(
        salon, reference_date=reference_date,
        lookback_days=lookback_days, window_days=window_days
    )
    return [_record(row) for row in rows]


def export_rebooking_csv(salon, reference_date=None,
                         lookback_days=DEFAULT_LOOKBACK_DAYS, *,
                         window_days=None):
    """Return rebooking candidates as a CSV string.

    Arguments are the same as :func:`export_rebooking_candidates`
    (and therefore the same as ``rebooking_candidates``). The
    header row is :data:`REBOOKING_FIELDNAMES` and every data row
    comes from :func:`export_rebooking_candidates` with the same
    arguments, so the CSV and list exports always agree. No
    candidates exports as the header row alone. Lines end with
    ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=REBOOKING_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_rebooking_candidates(
        salon, reference_date=reference_date,
        lookback_days=lookback_days, window_days=window_days
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_rebooking_candidates_csv = export_rebooking_csv
rebooking_csv = export_rebooking_csv
