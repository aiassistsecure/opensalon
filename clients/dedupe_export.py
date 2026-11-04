"""Duplicate-candidates CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never merges, updates, or deletes a client, and never
sends anything.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: the rows come from
:func:`clients.dedupe.find_duplicate_candidates` called with
exactly the argument given here (``salon`` is passed through
unchanged) -- this module does not re-implement the grouping,
the email/phone normalization, the active-only rule, the salon
scoping, or the ordering. The CSV string is built from the dict
list returned by :func:`export_duplicate_candidates`, so the two
formats can never disagree.

Filter: ``key_type`` (optional, default ``None`` = no filter,
output identical to the unfiltered export) selects only the
groups whose stored key type exactly matches it (``"email"`` or
``"phone"``, the two keys :mod:`clients.dedupe` checks); it
composes with the salon scope. Selection only -- read-only.

Columns are only what ``find_duplicate_candidates`` actually
exposes: per group, its ``key_type`` and its normalized ``key``;
per client in the group, the client id (``client_id``) and the
client's name (``first_name`` / ``last_name``, via the group's
``clients``). One row is emitted per client per group, in the
service's group order and client order within each group. No
contact details beyond the service's own ``key`` are included,
and no invented fields are added.
"""
import csv
import io

from clients.dedupe import find_duplicate_candidates

__all__ = [
    "DEDUPE_FIELDNAMES",
    "export_duplicate_candidates",
    "export_duplicate_candidates_csv",
    "export_dedupe_csv",
    "dedupe_csv",
]

#: Column / key order shared by the dict export and the CSV export.
DEDUPE_FIELDNAMES = [
    "key_type",
    "key",
    "client_id",
    "first_name",
    "last_name",
]


def export_duplicate_candidates(salon=None, key_type=None):
    """Return duplicate candidates as a list of dicts.

    The ``salon`` argument is exactly that of
    :func:`clients.dedupe.find_duplicate_candidates` and is
    passed through to it unchanged: ``salon``, when given, scopes
    the report to one salon; when ``None``, all salons are
    considered. ``key_type``, when given, selects only groups
    whose key type exactly matches it (``"email"`` / ``"phone"``);
    ``None`` (the default) applies no filter, so the output is
    identical to the unfiltered export. Each group the service
    returns (and the filter keeps) contributes one
    entry per client in that group, each a dict with exactly
    :data:`DEDUPE_FIELDNAMES` keys, in the service's order (groups
    by key type then key; clients by last name, first name, pk).
    No candidates exports as ``[]``.
    """
    records = []
    for group in find_duplicate_candidates(salon=salon):
        if key_type is not None and group["key_type"] != key_type:
            continue
        for client in group["clients"]:
            records.append({
                "key_type": group["key_type"],
                "key": group["key"],
                "client_id": client.pk,
                "first_name": client.first_name,
                "last_name": client.last_name,
            })
    return records


def export_duplicate_candidates_csv(salon=None, key_type=None):
    """Return duplicate candidates as a CSV string.

    Arguments are the same as :func:`export_duplicate_candidates`.
    The
    header row is :data:`DEDUPE_FIELDNAMES` and every data row
    comes from :func:`export_duplicate_candidates` with the same
    arguments, so the CSV and list exports always agree. No
    candidates exports as the header row alone. Lines end with
    ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=DEDUPE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_duplicate_candidates(
            salon=salon, key_type=key_type):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_dedupe_csv = export_duplicate_candidates_csv
dedupe_csv = export_duplicate_candidates_csv
