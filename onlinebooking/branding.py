"""Salon branding payload for online booking (read-only).

Backend only — no views, templates, or static assets. This module
is the one place online booking reads a salon's identity from:
the branding fields declared on ``saloncore.Salon`` (``tagline``,
``logo_url``, ``primary_color``, ``accent_color`` — see that
model's docstring). Online booking is branded BY THE SALON, so
callers render from this payload instead of re-reading the model
field by field or hard-coding any platform identity.

Fallback rule — per field, never all-or-nothing:

* A non-blank salon field is used verbatim (stripped of
  surrounding whitespace). Colour values are stored validated as
  ``#RRGGBB`` on the model and are not re-validated or
  re-normalised here — the model is the single source of truth.
* A blank (or whitespace-only) field falls back individually to
  :data:`UNBRANDED_BRANDING`: no invented tagline and no invented
  logo (both stay ``""``, so a consumer renders the salon name as
  the wordmark), plus neutral charcoal/grey colours that carry no
  salon's — and no platform's — identity.
* ``is_branded`` is True when the salon set at least one branding
  field, and ``fallbacks_applied`` names every field that fell
  back, in payload order, so a consumer can tell a fully branded
  salon from a partially branded or wholly unbranded one without
  comparing values itself.

Salon-scoped and read-only: the payload is built from exactly the
one ``Salon`` given (or fetched by id by
:func:`salon_branding_for_id`) — never from another salon's
record, an ordering guess, or a global default salon. Nothing is
written: the salon is not saved or mutated, and each call returns
a fresh dict the caller may freely mutate.
"""
from saloncore.models import Salon

__all__ = [
    "BRANDING_FIELDS",
    "UNBRANDED_BRANDING",
    "salon_branding",
    "branding_payload",
    "salon_branding_for_id",
]

#: The Salon branding fields carried by the payload, in order.
BRANDING_FIELDS = ("tagline", "logo_url", "primary_color", "accent_color")

#: Unbranded fallback values, one per branding field. Tagline and
#: logo stay empty — inventing either would brand the page with
#: something the salon never chose. The colours are neutral
#: greys: usable as text/accent defaults, belonging to nobody.
UNBRANDED_BRANDING = {
    "tagline": "",
    "logo_url": "",
    "primary_color": "#212121",
    "accent_color": "#757575",
}


def _clean(value):
    """A stored branding value as a stripped string ("" if unset)."""
    return str(value).strip() if value else ""


def salon_branding(salon):
    """Return the online-booking branding payload for ``salon``.

    Args:
        salon: a ``saloncore.Salon`` instance, or ``None`` (no
            salon configured yet — the wholly unbranded payload,
            with ``salon_id``/``salon_name`` empty, is returned
            rather than raising).

    Returns:
        A fresh ``dict`` with keys ``salon_id``, ``salon_name``,
        the four :data:`BRANDING_FIELDS`, ``is_branded`` (bool),
        and ``fallbacks_applied`` (list of field names, in
        :data:`BRANDING_FIELDS` order).
    """
    payload = {
        "salon_id": salon.pk if salon is not None else None,
        "salon_name": _clean(getattr(salon, "name", "")),
    }
    fallbacks = []
    for field in BRANDING_FIELDS:
        value = _clean(getattr(salon, field, ""))
        if value:
            payload[field] = value
        else:
            payload[field] = UNBRANDED_BRANDING[field]
            fallbacks.append(field)
    payload["is_branded"] = len(fallbacks) < len(BRANDING_FIELDS)
    payload["fallbacks_applied"] = fallbacks
    return payload


# Readable alias for call sites that think in payloads.
branding_payload = salon_branding


def salon_branding_for_id(salon_id):
    """Return the branding payload for the salon with ``salon_id``.

    Fetches exactly that salon; an unknown or ``None`` id returns
    the wholly unbranded payload (``salon_id`` None) — never
    another salon's branding.
    """
    if salon_id is None:
        return salon_branding(None)
    salon = Salon.objects.filter(pk=salon_id).first()
    if salon is None:
        return salon_branding(None)
    return salon_branding(salon)
