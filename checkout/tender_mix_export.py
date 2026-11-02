"""Read-only tender-mix CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.tender_mix` service as a plain list of dicts
(:func:`export_tender_mix`) and as a CSV string
(:func:`export_tender_mix_csv`) built from that same list, so
the two formats can never disagree -- one source of truth. The
computation is never reimplemented here: every amount and share
comes verbatim from :func:`checkout.tender_mix.tender_mix`.

Columns:

* ``salon_id`` -- the ``pk`` of the ``salon`` argument;
* ``start`` / ``end`` -- the window bounds, as ISO-8601 strings
  when they carry ``isoformat``;
* ``method`` -- each core tender slug, in the service's order;
* ``amount`` -- that tender's total, to two decimal places;
* ``total`` -- the window total, to two decimal places,
  repeated on every row;
* ``share_percent`` -- that tender's share of the window
  total, to two decimal places, or empty when the service
  returns ``None`` (an empty window);
* ``count`` -- the service's payment count, repeated per row.

The service's errors propagate unchanged (e.g. ``ValueError``
for a missing salon or a reversed window). Because the service
zero-fills every core tender, an empty window still exports
one explicit ``"0.00"`` row per tender, with an empty share.
Lines end with ``"\\n"``. Core stays provider-agnostic.
"""
import csv
import io
from decimal import Decimal

from .tender_mix import tender_mix

__all__ = [
    "EXPORT_FIELDNAMES", "export_tender_mix",
    "export_tender_mix_csv", "export_tender_mix_rows",
    "tender_mix_csv", "tender_mix_export_row",
]

EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "method",
    "amount", "total", "share_percent", "count",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else _money(value)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def tender_mix_export_row(entry, mix):
    """Return one :class:`TenderMixEntry` as an export row dict."""
    return {
        "salon_id": mix.salon_id,
        "start": _iso(mix.start),
        "end": _iso(mix.end),
        "method": entry.method,
        "amount": _money(entry.total),
        "total": _money(mix.total),
        "share_percent": _pct(entry.share_percent),
        "count": mix.count,
    }


def export_tender_mix(salon, start=None, end=None, **kwargs):
    """Return the tender mix for ``salon`` as one dict per tender.

    Rows are rendered verbatim from
    :func:`checkout.tender_mix.tender_mix` called with the same
    arguments, in the service's order. Read-only.
    """
    mix = tender_mix(salon, start, end, **kwargs)
    return [tender_mix_export_row(entry, mix) for entry in mix.entries]


def export_tender_mix_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_tender_mix` for the window as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_tender_mix` with the same
    arguments, so the CSV and list exports always agree. An
    empty window exports as the header plus zero-filled rows
    with empty shares. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_tender_mix(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_tender_mix_rows = export_tender_mix
tender_mix_csv = export_tender_mix_csv
