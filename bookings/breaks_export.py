"""Verbatim Break rows dict/CSV export.

Backend only, read-only (Exit Principle: anything a salon can
enter, it can fully export). Built ON TOP of
:mod:`bookings.breaks` -- rows, scoping, date-range filtering,
and ordering are that service's alone, reused verbatim; this
module never re-queries ``Break`` rows and never renders the
:mod:`bookings.break_totals` aggregates. One row per stored
break: ``id``, ``salon_id``, ``staff_member_id``,
``staff_name``, ``start``/``end`` (ISO-8601, as stored), and
``paid`` (the stored boolean). Empty salon/range = ``[]`` /
header row alone. Lines end "\\n".
"""
import csv
import io

from bookings.breaks import breaks

__all__ = [
    "BREAK_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "breaks_csv",
    "breaks_rows",
    "export_breaks",
    "export_breaks_csv",
]

BREAK_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "start",
    "end",
    "paid",
]
EXPORT_FIELDNAMES = BREAK_EXPORT_FIELDNAMES


def export_breaks(salon, date_from=None, date_to=None, *, staff_member=None):
    """Return verbatim break rows as plain dicts.

    Accepts exactly the parameters of
    :func:`bookings.breaks.breaks`, passed through unchanged.
    Each dict has exactly :data:`BREAK_EXPORT_FIELDNAMES` keys.
    """
    return [
        record.as_dict()
        for record in breaks(
            salon, date_from, date_to, staff_member=staff_member)
    ]


#: Alias matching the sibling ``*_rows`` naming.
breaks_rows = export_breaks


def export_breaks_csv(salon, date_from=None, date_to=None, *, staff_member=None):
    """Return verbatim break rows for ``salon`` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=BREAK_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_breaks(salon, date_from, date_to, staff_member=staff_member):
        writer.writerow({
            name: ("" if row[name] is None else row[name])
            for name in BREAK_EXPORT_FIELDNAMES
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
breaks_csv = export_breaks_csv
