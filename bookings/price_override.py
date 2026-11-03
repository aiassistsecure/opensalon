"""Appointment price-override service.

Pure service module -- no views, no UI. This is the single
backend write path for an appointment's desk price
(``Appointment.price_override``), extracted from the webui
card helper (``webui.views._do_price``) whose money validation
previously lived only in the view.

The card's word becomes ``price_override`` -- the price-book
row is never touched. An empty value (``None`` or a blank /
whitespace-only string) clears the override and the book
speaks again. Money is validated as money: finite,
non-negative, at most 99999.99, cent-quantized, never via
float. A value with sub-cent precision is refused rather
than silently rounded. Invalid money raises
``ValidationError`` -- writing nothing -- with the view's
own messages verbatim (``price is not a number``, ``price
cannot be negative``, ``price is too large``).
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone

from bookings.models import Appointment

__all__ = ["set_appointment_price"]

_CENT = Decimal("0.01")
_MAX_PRICE = Decimal("99999.99")


def set_appointment_price(appointment, raw=None, **kwargs):
    """Set (or clear) ``appointment``'s price override.

    ``raw`` (alias ``price``) is the desk's price as entered:
    a string, ``Decimal``, or int. ``None`` or an empty /
    whitespace-only string CLEARS the override. Returns the
    updated appointment. Raises ``ValidationError`` --
    writing nothing -- for a missing or unknown appointment,
    a non-numeric or non-finite value, a negative value, a
    value over 99999.99, or sub-cent precision.
    """
    if "price" in kwargs:
        if raw is not None:
            raise ValidationError(
                {"price": "Pass either raw or price, not both."})
        raw = kwargs.pop("price")
    if kwargs:
        raise ValidationError(
            {next(iter(kwargs)): "Unknown argument."})
    if appointment is None or not isinstance(appointment, Appointment):
        raise ValidationError(
            {"appointment": "An appointment is required."})
    if appointment.pk is None or not Appointment.objects.filter(
            pk=appointment.pk).exists():
        raise ValidationError(
            {"appointment": "That appointment does not exist."})
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        appointment.price_override = None
        appointment.updated_at = timezone.now()
        appointment.save(update_fields=["price_override", "updated_at"])
        return appointment
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(
            {"price": "price is not a number"}) from None
    if not value.is_finite():
        raise ValidationError({"price": "price is not a number"})
    if value < 0:
        raise ValidationError({"price": "price cannot be negative"})
    if value > _MAX_PRICE:
        raise ValidationError({"price": "price is too large"})
    if value != value.quantize(_CENT):
        raise ValidationError(
            {"price": "price must be to the cent"})
    appointment.price_override = value.quantize(_CENT)
    appointment.updated_at = timezone.now()
    appointment.save(update_fields=["price_override", "updated_at"])
    return appointment
