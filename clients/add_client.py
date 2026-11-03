"""Single-client creation service for the clients app.

Backend only -- no views, templates, or UI.

Today ``Client`` rows arrive only via bulk import
(``import_clients`` / ``import_salon_data``) or direct ORM
writes in other channels. This module is the validated
single-record write path: it creates exactly one client in
one salon's scope, for clients created directly in OpenSalon
(their ``external_id`` stays blank, as the model documents).

Opt-in founding rule: ``sms_opt_in`` and ``email_opt_in``
default to False and are set True only when a caller passes
them explicitly as True. There is no path here that defaults
an opt-in on.

Validation mirrors the model/importer field shapes: first and
last names are non-blank strings of at most 80 characters
(never silently truncated), email is blank or a valid address
of at most 254 characters, phone is a string of at most 32
characters, and both opt-ins must be explicit booleans. No
uniqueness rule is invented: the real client book contains
duplicate emails and phones, and the model's only constraint
is on non-blank ``external_id``, which this service never sets.
"""
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from clients.models import Client
from saloncore.models import Salon

__all__ = ["add_client", "validate_add_client"]

_FIRST_LIMIT = Client._meta.get_field("first_name").max_length
_LAST_LIMIT = Client._meta.get_field("last_name").max_length
_EMAIL_LIMIT = Client._meta.get_field("email").max_length
_PHONE_LIMIT = Client._meta.get_field("phone").max_length


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_name(value, field, limit):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be blank")
    text = value.strip()
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _clean_email(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    text = value.strip()
    if not text:
        return ""
    if len(text) > _EMAIL_LIMIT:
        raise ValueError(f"email exceeds {_EMAIL_LIMIT} characters")
    try:
        validate_email(text)
    except DjangoValidationError:
        raise ValueError(f"email {text!r} is not a valid address") from None
    return text


def _clean_phone(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("phone must be a string")
    text = str(value).strip()
    if len(text) > _PHONE_LIMIT:
        raise ValueError(f"phone exceeds {_PHONE_LIMIT} characters")
    return text


def _clean_flag(value, field):
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def validate_add_client(salon, first_name, last_name, email="",
                        phone="", sms_opt_in=False, email_opt_in=False):
    """Validate an ``add_client`` call, writing nothing.

    Performs every check :func:`add_client` performs and returns
    the cleaned fields the writer would store, as a dict with keys
    ``salon``, ``first_name``, ``last_name``, ``email``, ``phone``,
    ``sms_opt_in``, ``email_opt_in``. Raises the same ``ValueError``
    the writer would raise. Writes nothing, so it is safe for
    ``--dry-run`` previews on every backend (including NEDB, where
    a rolled-back transaction does not undo writes).
    """
    return dict(
        salon=_clean_salon(salon),
        first_name=_clean_name(first_name, "first_name", _FIRST_LIMIT),
        last_name=_clean_name(last_name, "last_name", _LAST_LIMIT),
        email=_clean_email(email), phone=_clean_phone(phone),
        sms_opt_in=_clean_flag(sms_opt_in, "sms_opt_in"),
        email_opt_in=_clean_flag(email_opt_in, "email_opt_in"))


def add_client(salon, first_name, last_name, email="", phone="",
               sms_opt_in=False, email_opt_in=False):
    """Create one client in ``salon`` and return it.

    Opt-ins default to False; pass ``sms_opt_in=True`` /
    ``email_opt_in=True`` explicitly to set one. Raises
    ``ValueError`` -- creating nothing -- for an unsaved salon,
    a blank/over-long name, an invalid/over-long email, an
    over-long phone, or a non-boolean opt-in.
    """
    with transaction.atomic():
        cleaned = validate_add_client(
            salon, first_name, last_name, email=email, phone=phone,
            sms_opt_in=sms_opt_in, email_opt_in=email_opt_in)
        return Client.objects.create(**cleaned)
