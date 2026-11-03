"""Service-price write service for the price book.

Pure service module -- no views, no UI. This is the single write
path for setting one service's price at one staff level
(``saloncore.ServicePrice``).

The logic lived only as a closure inside the ``import_price_book``
command; it is extracted here verbatim in behaviour so the importer,
the ``set_price`` management command, and any future caller can
never disagree about how a price is set:

- the price row is ``update_or_create`` keyed by (service,
  staff level);
- ``is_from=None`` leaves a stored flag untouched (on create the
  model default applies); an explicit bool is stored;
- ``price_active=None`` means active, as the importer defined it;
- a :class:`~saloncore.models.PriceChange` audit row is appended
  ONLY when an existing price's amount actually changes -- never
  on creation and never on an unchanged re-set -- with
  ``changed_by`` naming the caller (e.g. ``"import_price_book"``
  or ``"set_price"``), so the append-only ledger always says who
  made the change.
"""
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional

from django.core.exceptions import ValidationError

from saloncore.models import PriceChange, Service, ServicePrice, StaffLevel

__all__ = ["SetPriceResult", "set_price"]


class SetPriceResult(NamedTuple):
    """Outcome of :func:`set_price`."""

    price: ServicePrice
    created: bool
    old_amount: Optional[Decimal]
    change: Optional[PriceChange]


def _amount(value):
    if isinstance(value, bool) or value is None:
        raise ValidationError({"amount": "A price amount is required."})
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(
            {"amount": f"Amount {value!r} is not a valid price."}) from None


def _resolve(service, staff_level):
    if not isinstance(service, Service) or service.pk is None:
        raise ValidationError("service must be a saved Service instance.")
    if not isinstance(staff_level, StaffLevel) or staff_level.pk is None:
        raise ValidationError(
            "staff_level must be a saved StaffLevel instance.")
    if service.category.salon_id != staff_level.salon_id:
        raise ValidationError(
            "Staff level belongs to a different salon than the service.")


def set_price(service, staff_level, amount, is_from=None, *,
              changed_by="", note="", price_active=None):
    """Set ``service``'s price at ``staff_level`` to ``amount``.

    ``amount`` is stored as a :class:`~decimal.Decimal` (strings
    and ints are converted faithfully, never via float arithmetic).
    ``is_from`` marks starting-at pricing; ``None`` (the default)
    leaves a stored flag untouched. Returns a
    :class:`SetPriceResult` -- the saved price, whether it was
    created, the previous amount (``None`` on creation), and the
    appended :class:`PriceChange` audit row (``None`` when no
    audit row was due: creation, or the amount did not change).

    Raises ``ValidationError`` -- writing nothing -- for an
    unsaved or cross-salon service/staff level or an unparseable
    amount.
    """
    _resolve(service, staff_level)
    amount = _amount(amount)
    defaults = {"amount": amount,
                "active": True if price_active is None else price_active}
    if is_from is not None:
        defaults["is_from"] = bool(is_from)
    old = ServicePrice.objects.filter(
        service=service, staff_level=staff_level).first()
    price, created = ServicePrice.objects.update_or_create(
        service=service, staff_level=staff_level, defaults=defaults)
    change = None
    if old and not created and old.amount != amount:
        change = PriceChange.objects.create(
            service_price=price, changed_by=changed_by or "",
            old_amount=old.amount, new_amount=amount, note=note or "")
    return SetPriceResult(
        price=price, created=created,
        old_amount=None if old is None else old.amount, change=change)
