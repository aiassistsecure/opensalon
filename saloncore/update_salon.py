"""Single-salon update service for the tenant root record.

Backend only -- no views, templates, or UI. Today ``Salon`` rows
are written only by the webui settings view (validation
re-implemented in-view) and the ``import_salon_data`` restore
path (branding fields). This is the validated backend write
path for ``name``, ``timezone``, ``currency``, ``tagline``,
``logo_url``, ``primary_color`` and ``accent_color``: ``None``
means "leave unchanged" (no field at all is refused); validation
mirrors the settings view (name non-blank within the model
limit, real IANA timezone, three-letter currency stored
upper-case); branding fields clear with ``""``, a non-blank
colour must satisfy the model's ``HEX_COLOR_VALIDATOR`` and a
non-blank logo URL must be valid. Only differing fields are
written, via ``save(update_fields=[...])``.
"""
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone as django_timezone

from saloncore.models import HEX_COLOR_VALIDATOR, Salon

__all__ = [
    "SalonChange", "SalonUpdate",
    "update_salon", "validate_update_salon",
]

_FIELDS = ("name", "timezone", "currency", "tagline", "logo_url",
           "primary_color", "accent_color")
_NAME_LIMIT = Salon._meta.get_field("name").max_length
_TIMEZONE_LIMIT = Salon._meta.get_field("timezone").max_length
_TAGLINE_LIMIT = Salon._meta.get_field("tagline").max_length
_LOGO_URL_LIMIT = Salon._meta.get_field("logo_url").max_length


@dataclass(frozen=True)
class SalonChange:
    """One field's old -> new value in a salon update."""

    field: str
    old_value: object
    new_value: object


@dataclass(frozen=True)
class SalonUpdate:
    """Audit-friendly result of :func:`update_salon`."""

    salon: Salon
    name: str
    timezone: str
    currency: str
    tagline: str
    logo_url: str
    primary_color: str
    accent_color: str
    changed_fields: tuple = ()
    changes: tuple = ()
    changed_at: object = None

    @property
    def changed(self):
        return bool(self.changed_fields)


def _result(salon, changes=(), changed_at=None):
    return SalonUpdate(
        salon=salon, name=salon.name, timezone=salon.timezone,
        currency=salon.currency, tagline=salon.tagline,
        logo_url=salon.logo_url, primary_color=salon.primary_color,
        accent_color=salon.accent_color, changes=tuple(changes),
        changed_fields=tuple(c.field for c in changes),
        changed_at=changed_at)


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("salon name must not be blank")
    text = name.strip()
    if len(text) > _NAME_LIMIT:
        raise ValueError(f"salon name exceeds {_NAME_LIMIT} characters")
    return text


def _clean_timezone(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timezone must not be blank")
    text = value.strip()
    if len(text) > _TIMEZONE_LIMIT:
        raise ValueError(f"timezone exceeds {_TIMEZONE_LIMIT} characters")
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"unknown timezone {text!r}") from None
    return text


def _clean_currency(value):
    if not isinstance(value, str):
        raise ValueError("currency must be a three-letter code")
    text = value.strip().upper()
    if len(text) != 3 or not text.isalpha():
        raise ValueError("currency must be a three-letter code")
    return text


def _clean_tagline(value):
    if not isinstance(value, str):
        raise ValueError("tagline must be a string")
    text = value.strip()
    if len(text) > _TAGLINE_LIMIT:
        raise ValueError(f"tagline exceeds {_TAGLINE_LIMIT} characters")
    return text


def _clean_logo_url(value):
    if not isinstance(value, str):
        raise ValueError("logo_url must be a string")
    text = value.strip()
    if len(text) > _LOGO_URL_LIMIT:
        raise ValueError(f"logo_url exceeds {_LOGO_URL_LIMIT} characters")
    if text:
        try:
            URLValidator()(text)
        except Exception:
            raise ValueError(f"logo_url {text!r} is not a valid URL") from None
    return text


def _clean_color(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if text:
        try:
            HEX_COLOR_VALIDATOR(text)
        except Exception:
            raise ValueError(
                f"{field} must be a hex color in the form #RRGGBB") from None
    return text


_CLEANERS = {
    "name": _clean_name,
    "timezone": _clean_timezone,
    "currency": _clean_currency,
    "tagline": _clean_tagline,
    "logo_url": _clean_logo_url,
    "primary_color": lambda v: _clean_color(v, "primary_color"),
    "accent_color": lambda v: _clean_color(v, "accent_color"),
}


def validate_update_salon(salon, *, name=None, timezone=None,
                          currency=None, tagline=None, logo_url=None,
                          primary_color=None, accent_color=None):
    """Validate an ``update_salon`` call, writing nothing.

    Returns a dict with key ``salon`` plus one entry per field
    explicitly given (``None`` omitted, so omitted != cleared);
    raises the same ``ValueError`` the writer would. Safe for
    ``--dry-run`` on every backend (NEDB included).
    """
    salon = _clean_salon(salon)
    given = dict(name=name, timezone=timezone, currency=currency,
                 tagline=tagline, logo_url=logo_url,
                 primary_color=primary_color, accent_color=accent_color)
    cleaned = dict(salon=salon)
    for field in _FIELDS:
        if given[field] is not None:
            cleaned[field] = _CLEANERS[field](given[field])
    if len(cleaned) == 1:
        raise ValueError("at least one field must be given")
    return cleaned


def update_salon(salon, *, name=None, timezone=None, currency=None,
                 tagline=None, logo_url=None, primary_color=None,
                 accent_color=None):
    """Update one salon's profile/branding fields.

    ``None`` fields stay unchanged. Returns a :class:`SalonUpdate`
    (resulting values, changed fields in ``_FIELDS`` order,
    old -> new values, ``changed_at`` only when a change was
    saved). Raises ``ValueError`` -- changing nothing -- on any
    validation failure.
    """
    cleaned = validate_update_salon(
        salon, name=name, timezone=timezone, currency=currency,
        tagline=tagline, logo_url=logo_url, primary_color=primary_color,
        accent_color=accent_color)
    salon = cleaned.pop("salon")
    changes = tuple(
        SalonChange(field, getattr(salon, field), cleaned[field])
        for field in _FIELDS
        if field in cleaned and cleaned[field] != getattr(salon, field))
    if not changes:
        return _result(salon)
    with transaction.atomic():
        for change in changes:
            setattr(salon, change.field, change.new_value)
        salon.save(update_fields=[change.field for change in changes])
    return _result(salon, changes, django_timezone.now())
