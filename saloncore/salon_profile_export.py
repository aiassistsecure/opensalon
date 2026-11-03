"""Verbatim salon profile CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a salon.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports a salon's own profile
record -- :class:`~saloncore.models.Salon` itself -- verbatim,
as a plain JSON-serializable dict and as CSV built from that
same dict, so the two formats can never disagree -- one
source of truth.

Why this record needs its own surface: everywhere else the
salon profile appears only inside the salon_data bundle, as
one section among many. There was no standalone export a
salon could take of just its own profile. Here every stored
field renders on its own.

Columns are only real model fields, in the salon_data
bundle's order: ``id``, ``name``, ``timezone``, ``currency``,
``tagline``, ``logo_url``, ``primary_color``,
``accent_color``, ``created_at`` and ``updated_at``
(datetimes ISO-8601 with timezone). The Salon model carries
no PIN, secret, or payment-provider field, so none appears
here. No fields are invented and nothing is derived.

Ordering for the all-salons export follows the model's own
ordering (``name``), tightened with an ``id`` tie-break.
Lines end ``"\\n"``.
"""
import csv
import io

from saloncore.models import Salon

__all__ = [
    "SALON_FIELDNAMES",
    "SALON_PROFILE_FIELDNAMES",
    "salon_profile_row",
    "export_salon_profile",
    "export_salon_profile_csv",
    "salon_profile_csv",
    "export_salon_profiles",
    "export_salon_profiles_csv",
    "salon_profiles_csv",
]

#: Column / key order for a Salon row, shared by the dict
#: export and the CSV export: every field on the model.
SALON_FIELDNAMES = [
    "id",
    "name",
    "timezone",
    "currency",
    "tagline",
    "logo_url",
    "primary_color",
    "accent_color",
    "created_at",
    "updated_at",
]
SALON_PROFILE_FIELDNAMES = SALON_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def salon_profile_row(salon):
    """Return one stored ``salon`` as a verbatim row dict."""
    return {
        "id": salon.pk,
        "name": salon.name,
        "timezone": salon.timezone,
        "currency": salon.currency,
        "tagline": salon.tagline,
        "logo_url": salon.logo_url,
        "primary_color": salon.primary_color,
        "accent_color": salon.accent_color,
        "created_at": _dt(salon.created_at),
        "updated_at": _dt(salon.updated_at),
    }


def _resolve(salon):
    """Resolve a Salon instance or pk to the stored instance."""
    if salon is None:
        return None
    if isinstance(salon, Salon):
        return salon if salon.pk is not None else None
    try:
        return Salon.objects.get(pk=salon)
    except (Salon.DoesNotExist, TypeError, ValueError):
        return None


def export_salon_profile(salon):
    """Return ``salon``'s profile verbatim as a single dict.

    The dict has exactly :data:`SALON_FIELDNAMES` keys.
    ``salon`` may be a Salon instance or its pk. A missing
    or unsaved salon exports as ``None``. Read-only.
    """
    resolved = _resolve(salon)
    return salon_profile_row(resolved) if resolved is not None else None


def export_salon_profiles():
    """Return every salon's profile verbatim as dicts.

    Ordered by (``name``, ``id``). An empty database exports
    as ``[]``. Read-only.
    """
    queryset = Salon.objects.all().order_by("name", "id")
    return [salon_profile_row(row) for row in queryset]


def _csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SALON_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in rows:
        writer.writerow(record)
    return buffer.getvalue()


def export_salon_profile_csv(salon):
    """Return ``salon``'s profile as CSV.

    Header plus the one row from :func:`export_salon_profile`,
    so CSV and dict exports always agree. A missing salon
    exports as the header row alone.
    """
    row = export_salon_profile(salon)
    return _csv([row] if row is not None else [])


#: Alias, mirroring the naming convenience in sibling services.
salon_profile_csv = export_salon_profile_csv


def export_salon_profiles_csv():
    """Return every salon's profile as CSV.

    Header plus one row per salon, each from
    :func:`export_salon_profiles`, so the CSV and list
    exports always agree.
    """
    return _csv(export_salon_profiles())


#: Alias, mirroring the naming convenience in sibling services.
salon_profiles_csv = export_salon_profiles_csv
