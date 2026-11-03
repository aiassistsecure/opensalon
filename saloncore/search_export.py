"""Read-only price-book search CSV export service.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. Renders :mod:`saloncore.search` as dicts
(:func:`export_search_services`) and as CSV
(:func:`export_search_services_csv`) built from that same
list, so the two formats can never disagree -- one source of
truth. Every row comes verbatim from
:func:`saloncore.search.search_services`; no re-querying.

Rows have exactly :data:`EXPORT_FIELDNAMES`: ``id`` /
``service_id``, ``salon_id`` (via category), ``category_id`` /
``category_name``, ``name`` / ``description`` /
``external_id``, the duration segments plus ``total_minutes``
(``Service.total_minutes``), and ``active``. Filter semantics
and ordering follow the search service verbatim; no match is
``[]`` / the CSV header alone. Lines end with ``"\\n"``.
"""
import csv
import io

from saloncore.search import search_services

__all__ = [
    "EXPORT_FIELDNAMES",
    "SEARCH_FIELDNAMES",
    "export_search_services",
    "export_search_services_csv",
    "export_search_rows",
    "search_export_row",
    "search_services_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "service_id",
    "salon_id",
    "category_id",
    "category_name",
    "name",
    "description",
    "external_id",
    "service_minutes",
    "processing_minutes",
    "finishing_minutes",
    "total_minutes",
    "active",
]

SEARCH_FIELDNAMES = EXPORT_FIELDNAMES


def search_export_row(service):
    """Return one ``service`` found by the search service as a row dict."""
    return {
        "id": service.pk,
        "service_id": service.pk,
        "salon_id": service.category.salon_id,
        "category_id": service.category_id,
        "category_name": service.category.name,
        "name": service.name,
        "description": service.description,
        "external_id": service.external_id,
        "service_minutes": service.service_minutes,
        "processing_minutes": service.processing_minutes,
        "finishing_minutes": service.finishing_minutes,
        "total_minutes": service.total_minutes,
        "active": bool(service.active),
    }


def export_search_services(salon, query, include_inactive=False):
    """Return ``salon``'s services matching ``query``, as dicts.

    All arguments are passed verbatim to
    :func:`saloncore.search.search_services`; rows are rendered
    from its results in its own order. No match is ``[]``.
    Read-only.
    """
    services = search_services(
        salon, query, include_inactive=include_inactive
    )
    return [search_export_row(service) for service in services]


def export_search_services_csv(salon, query, include_inactive=False):
    """Return :func:`export_search_services` with the same args as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_search_services` with the same
    arguments, so the CSV and list exports always agree. No
    match exports as the header row alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_search_services(
        salon, query, include_inactive=include_inactive
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_search_rows = export_search_services
search_services_csv = export_search_services_csv
