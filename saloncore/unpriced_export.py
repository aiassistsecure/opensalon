"""Unpriced-services CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a service, a category,
a staff level, or a price.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing unpriced
report (:mod:`saloncore.unpriced`) as a plain,
JSON-serializable list of dicts
(:func:`export_unpriced_services`) and as a CSV string
(:func:`export_unpriced_services_csv`) built from that same
list, so the two formats can never disagree -- one source of
truth.

One source of truth for "unpriced": rows come only from
:func:`saloncore.unpriced.unpriced_services` (or, for the
fully-unpriced wrappers, from
:func:`saloncore.unpriced.fully_unpriced_services`), called
with exactly the arguments given here. This module does not
re-implement the priced rule (an active ``ServicePrice`` for
a level), the active-only filtering, the salon scoping, or
the ordering. Ordering is exactly the underlying service's:
by category ``sort_order``, then category name, then service
name. The ``fully_unpriced_count`` in
:func:`saloncore.unpriced.price_book_completeness` equals
``len(export_fully_unpriced_services(salon))`` for the same
salon, because both read the same underlying list.

Columns are only real fields the underlying services return,
flattened from the ``UnpricedService`` / ``MissingLevel``
dataclasses:

- ``salon_id``: the salon pk (``price_book_completeness``
  returns it as ``salon_id``; here it is the scoping salon).
- ``service_id`` / ``service_name``: ``UnpricedService``
  ``service_id`` / ``service_name``.
- ``category_id`` / ``category_name``: ``UnpricedService``
  ``category_id`` / ``category_name``.
- ``missing_level_ids``: the ``level_id`` of each entry in
  ``UnpricedService.missing_levels`` (also
  ``UnpricedService.to_dict()["missing_level_ids"]``),
  joined with ``";"`` in the order the service returns them;
  empty string when the list is empty.
- ``missing_level_names``: the ``level_name`` of each entry
  in ``missing_levels``, joined with ``";"`` in the same
  order.
- ``missing_level_count``: ``len(missing_levels)``.

No price, amount, or any other field is invented: an unpriced
service by definition has no price to export.
"""
import csv
import io

from saloncore.unpriced import fully_unpriced_services, unpriced_services

__all__ = [
    "EXPORT_FIELDNAMES",
    "UNPRICED_EXPORT_FIELDNAMES",
    "UNPRICED_FIELDNAMES",
    "export_fully_unpriced_services",
    "export_fully_unpriced_services_csv",
    "export_unpriced_services",
    "export_unpriced_services_csv",
    "unpriced_csv",
]

#: Column / key order shared by the dict export and the CSV export.
UNPRICED_FIELDNAMES = [
    "salon_id",
    "service_id",
    "service_name",
    "category_id",
    "category_name",
    "missing_level_ids",
    "missing_level_names",
    "missing_level_count",
]
UNPRICED_EXPORT_FIELDNAMES = UNPRICED_FIELDNAMES
EXPORT_FIELDNAMES = UNPRICED_FIELDNAMES


def _record(salon, entry):
    salon_id = getattr(salon, "pk", salon)
    return {
        "salon_id": salon_id,
        "service_id": entry.service_id,
        "service_name": entry.service_name,
        "category_id": entry.category_id,
        "category_name": entry.category_name,
        "missing_level_ids": ";".join(
            str(level.level_id) for level in entry.missing_levels
        ),
        "missing_level_names": ";".join(
            level.level_name for level in entry.missing_levels
        ),
        "missing_level_count": len(entry.missing_levels),
    }


def _to_csv(records):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=UNPRICED_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in records:
        writer.writerow(record)
    return buffer.getvalue()


def export_unpriced_services(salon, staff_level=None):
    """Return unpriced services for ``salon`` as dicts.

    Delegates to :func:`saloncore.unpriced.unpriced_services`
    with the same arguments: without ``staff_level`` this is
    the fully-unpriced list; with one, every active service
    missing a price for that level. Each entry is a dict with
    exactly :data:`UNPRICED_FIELDNAMES` keys, in the service's
    order. A salon with no unpriced services exports as ``[]``.
    Raises ``ValueError`` for a ``staff_level`` from another
    salon (the underlying service's rule). Read-only.
    """
    return [
        _record(salon, entry)
        for entry in unpriced_services(salon, staff_level=staff_level)
    ]


def export_unpriced_services_csv(salon, staff_level=None):
    """Return unpriced services for ``salon`` as CSV.

    The header row is :data:`UNPRICED_FIELDNAMES` and every
    data row comes from :func:`export_unpriced_services` with
    the same arguments, so the CSV and list exports always
    agree. A salon with no unpriced services exports as the
    header row alone. Lines end ``"\\n"``.
    """
    return _to_csv(export_unpriced_services(salon, staff_level=staff_level))


def export_fully_unpriced_services(salon):
    """Return fully unpriced services for ``salon`` as dicts.

    Delegates to
    :func:`saloncore.unpriced.fully_unpriced_services`.
    Same record shape and ordering as
    :func:`export_unpriced_services`. Read-only.
    """
    return [_record(salon, entry) for entry in fully_unpriced_services(salon)]


def export_fully_unpriced_services_csv(salon):
    """Return fully unpriced services for ``salon`` as CSV.

    Header and rows come from
    :func:`export_fully_unpriced_services`, so the CSV and
    list exports always agree. Lines end ``"\\n"``.
    """
    return _to_csv(export_fully_unpriced_services(salon))


#: Alias, mirroring the naming convenience in sibling services.
unpriced_csv = export_unpriced_services_csv
