"""Derived online-booking branding payload CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a salon.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the branding payload a
booking page actually renders from -- the DERIVED payload built
by :mod:`onlinebooking.branding` (:func:`salon_branding` /
:func:`salon_branding_for_id`) -- as a plain JSON-serializable
dict and as CSV built from that same dict, so the two formats
can never disagree -- one source of truth.

Why this is not a re-export of the stored record:
:mod:`saloncore.salon_profile_export` already exports the
stored ``Salon`` fields verbatim, and it keeps owning those.
What no export carried before is the derived payload: each
branding field AFTER the per-field fallback rule has run
(blank fields fall back individually to
:data:`~onlinebooking.branding.UNBRANDED_BRANDING`), plus
``is_branded`` and ``fallbacks_applied`` naming every field
that fell back. A wholly unbranded salon therefore exports
its neutral fallback colours here, not the blank strings it
has stored -- the payload is exported verbatim, never
re-derived differently and never re-read field by field from
the model.

Columns are exactly the payload keys, in payload order:
``salon_id``, ``salon_name``, the four branding fields
(``tagline``, ``logo_url``, ``primary_color``,
``accent_color``), ``is_branded`` and ``fallbacks_applied``.
In the dict export ``fallbacks_applied`` stays the payload's
list; in CSV it renders as one cell, the field names joined
with ``";"`` (the list-in-CSV convention of sibling exports).
Lines end ``"\\n"``.
"""
import csv
import io

from onlinebooking.branding import salon_branding
from saloncore.models import Salon

__all__ = [
    "BRANDING_FIELDNAMES",
    "BRANDING_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "branding_row",
    "export_branding",
    "export_branding_csv",
    "branding_csv",
]

#: Column / key order for a branding row, shared by the dict
#: export and the CSV export: exactly the payload keys of
#: :func:`onlinebooking.branding.salon_branding`, in order.
BRANDING_FIELDNAMES = [
    "salon_id",
    "salon_name",
    "tagline",
    "logo_url",
    "primary_color",
    "accent_color",
    "is_branded",
    "fallbacks_applied",
]
BRANDING_EXPORT_FIELDNAMES = BRANDING_FIELDNAMES
EXPORT_FIELDNAMES = BRANDING_FIELDNAMES


def branding_row(salon):
    """Return the derived branding payload for ``salon`` as a dict.

    Delegates verbatim to
    :func:`onlinebooking.branding.salon_branding` -- fallback
    values, ``is_branded`` and ``fallbacks_applied`` included --
    and re-keys it in :data:`BRANDING_FIELDNAMES` order.
    """
    payload = salon_branding(salon)
    return {field: payload[field] for field in BRANDING_FIELDNAMES}


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


def export_branding(salon):
    """Return ``salon``'s derived branding payload as a single dict.

    The dict has exactly :data:`BRANDING_FIELDNAMES` keys and
    carries the payload verbatim: fallback values where the
    salon left a field blank, ``is_branded``, and
    ``fallbacks_applied`` as a list. ``salon`` may be a Salon
    instance or its pk. A missing or unsaved salon exports as
    ``None``. Read-only.
    """
    resolved = _resolve(salon)
    return branding_row(resolved) if resolved is not None else None


def _csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=BRANDING_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in rows:
        row = dict(record)
        row["fallbacks_applied"] = ";".join(record["fallbacks_applied"])
        writer.writerow(row)
    return buffer.getvalue()


def export_branding_csv(salon):
    """Return ``salon``'s derived branding payload as CSV.

    Header plus the one row from :func:`export_branding`, so
    CSV and dict exports always agree. A missing salon exports
    as the header row alone.
    """
    row = export_branding(salon)
    return _csv([row] if row is not None else [])


#: Alias, mirroring the naming convenience in sibling services.
branding_csv = export_branding_csv
