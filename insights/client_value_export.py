"""Per-client value CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale or client.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's per-client value
report as a CSV string built ON TOP of
:mod:`insights.client_value` — the definition of settled revenue
per client (completed sales only, effective-date window, salon
scoping, client attribution, ranking) is that service's alone and
is reused verbatim via :func:`insights.client_value.client_value`;
this module never reimplements totals, re-queries sales, or
re-orders rows. Ordering is exactly the service's ordering:
``total`` descending, then ``sale_count`` descending, then client
name ascending.

Columns are only fields the service's rows actually carry:

- ``client_id``: the client pk, as carried by the service row.
- ``client_name``: the client's display name (``str(client)``),
  as carried by the service row.
- ``salon_id``: the salon the export was scoped to.
- ``total``: the row's settled revenue, money as a string to two
  decimal places, never passed through a float.
- ``sale_count``: the row's number of completed sales.

The service's unattributed bucket (sales with no client, or a
client from another salon) is not a client row, so it does not
appear here — exactly as it does not appear in the service's
``rows``.
"""
import csv
import io
from decimal import Decimal

from insights.client_value import client_value

__all__ = [
    "CLIENT_VALUE_FIELDNAMES",
    "export_client_value_csv",
    "client_value_csv",
]

#: Column order of the CSV export.
CLIENT_VALUE_FIELDNAMES = [
    "client_id",
    "client_name",
    "salon_id",
    "total",
    "sale_count",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_client_value_csv(salon, start, end, **kwargs):
    """Return ``salon``'s per-client value report as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to :func:`insights.client_value.client_value`.
        start: inclusive window start, as accepted by that service.
        end: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service.

    Returns:
        A CSV string whose header row is
        :data:`CLIENT_VALUE_FIELDNAMES` and whose data rows follow
        the client-value service's ordering exactly, with values
        matching that service's rows. An empty window exports as
        the header row alone. Lines end with ``"\\n"``.
    """
    result = client_value(salon, start, end, **kwargs)
    salon_id = salon.pk if salon is not None else None
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLIENT_VALUE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in result.rows:
        writer.writerow({
            "client_id": row.client_id,
            "client_name": row.display_name,
            "salon_id": salon_id,
            "total": _money(row.total),
            "sale_count": row.sale_count,
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
client_value_csv = export_client_value_csv
