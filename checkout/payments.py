"""Provider-agnostic payment interface for checkout.

Core never depends on any external payment service: it speaks only
this interface. A salon that wants an external service supplies its
own adapter implementing :class:`PaymentProvider`, and that adapter
lives outside core. The two implementations shipped here need no
external provider at all: cash taken at the till, and tenders that
are settled entirely outside OpenSalon (for example on a standalone
terminal the salon already owns).
"""
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaymentResult:
    """Outcome of a charge or refund attempt."""

    success: bool
    status: str
    amount: Decimal
    reference: str = ""
    message: str = ""


def _validate_amount(amount):
    amount = Decimal(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    return amount


class PaymentProvider(ABC):
    """Contract every payment adapter must implement.

    ``name`` is a short slug recorded on payments taken through the
    provider; it identifies the tender route, never a vendor.
    """

    name = ""

    @abstractmethod
    def charge(self, amount, reference=""):
        """Take ``amount``; ``reference`` is the caller's id for the sale."""
        raise NotImplementedError

    @abstractmethod
    def refund(self, payment, amount):
        """Refund ``amount`` against a previous ``payment``.

        ``payment`` is any object with a ``provider_reference``
        attribute (in practice a ``checkout.Payment``).
        """
        raise NotImplementedError

    def _result(self, kind, amount, reference):
        ref = reference or f"{self.name}-{uuid.uuid4().hex[:16]}"
        return PaymentResult(
            success=True, status=kind, amount=amount, reference=ref
        )


class CashProvider(PaymentProvider):
    """Cash handed over at the till; settled immediately, in person."""

    name = "cash"

    def charge(self, amount, reference=""):
        return self._result("completed", _validate_amount(amount), reference)

    def refund(self, payment, amount):
        amount = _validate_amount(amount)
        return self._result(
            "refunded", amount, getattr(payment, "provider_reference", "")
        )


class ExternalTenderProvider(PaymentProvider):
    """A tender settled outside OpenSalon, recorded here for the books.

    OpenSalon does not move the money: the salon settles on whatever
    external arrangement it already has, and this provider simply
    records a completed charge or refund against its reference.
    """

    name = "external"

    def charge(self, amount, reference=""):
        return self._result("completed", _validate_amount(amount), reference)

    def refund(self, payment, amount):
        amount = _validate_amount(amount)
        return self._result(
            "refunded", amount, getattr(payment, "provider_reference", "")
        )
