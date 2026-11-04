"""Single-salon creation service for the tenant root record.

Backend only -- no views, templates, or UI.

Today ``Salon`` rows arrive only via bulk import
(``import_salon_data``). This module is the validated
single-record write path -- the bootstrap for a new tenant:
it creates exactly one salon from its name, locale defaults
(``timezone``, ``currency``) and optional branding
(``tagline``, ``logo_url``, ``primary_color``,
``accent_color``).

Validation is not re-implemented here: the field cleaners are
reused verbatim from :mod:`saloncore.update_salon` (name
non-blank within the model limit, real IANA timezone,
three-letter currency stored upper-case, branding fields a
string within the model limit, a non-blank colour satisfying
the model's ``HEX_COLOR_VALIDATOR`` and a non-blank logo URL
valid). Defaults match the model defaults: ``timezone``
``"UTC"``, ``currency`` ``"USD"``, branding blank. An
explicit ``None`` for an optional field means its default
(the house style of the sibling ``add_*`` services); ``name``
is required.
"""
from django.db import transaction

from saloncore.models import Salon
from saloncore.update_salon import (
    _clean_color,
    _clean_currency,
    _clean_logo_url,
    _clean_name,
    _clean_tagline,
    _clean_timezone,
)

__all__ = ["add_salon", "validate_add_salon"]

_DEFAULT_TIMEZONE = Salon._meta.get_field("timezone").get_default()
_DEFAULT_CURRENCY = Salon._meta.get_field("currency").get_default()


def _clean_timezone_or_default(value):
    return _DEFAULT_TIMEZONE if value is None else _clean_timezone(value)


def _clean_currency_or_default(value):
    return _DEFAULT_CURRENCY if value is None else _clean_currency(value)


def _clean_optional(value, cleaner):
    return "" if value is None else cleaner(value)


def validate_add_salon(name, timezone="UTC", currency="USD",
                       tagline="", logo_url="", primary_color="",
                       accent_color=""):
    """Validate an ``add_salon`` call, writing nothing.

    Performs every check :func:`add_salon` performs, returns the
    cleaned fields the writer would store, raises the same
    ``ValueError``, and writes nothing -- safe for ``--dry-run``
    on every backend (NEDB included: no rollback is relied on).
    """
    return dict(
        name=_clean_name(name),
        timezone=_clean_timezone_or_default(timezone),
        currency=_clean_currency_or_default(currency),
        tagline=_clean_optional(tagline, _clean_tagline),
        logo_url=_clean_optional(logo_url, _clean_logo_url),
        primary_color=_clean_optional(
            primary_color, lambda v: _clean_color(v, "primary_color")),
        accent_color=_clean_optional(
            accent_color, lambda v: _clean_color(v, "accent_color")))


def add_salon(name, timezone="UTC", currency="USD", tagline="",
              logo_url="", primary_color="", accent_color=""):
    """Create one salon and return it.

    Raises ``ValueError`` -- creating nothing -- for a
    blank/over-long name, an unknown/over-long timezone, a
    non-three-letter currency, an over-long/non-string tagline
    or logo URL, an invalid logo URL, or a non-hex colour.
    """
    with transaction.atomic():
        cleaned = validate_add_salon(
            name, timezone=timezone, currency=currency,
            tagline=tagline, logo_url=logo_url,
            primary_color=primary_color, accent_color=accent_color)
        return Salon.objects.create(**cleaned)
