"""The payment-adapter seam.

Core moves no money and names no processor. A salon that wants
card payments installs an adapter — a small class living OUTSIDE
this repo that implements :class:`PaymentAdapter` — and points the
``OPENSALON_PAYMENT_ADAPTER`` setting at it. Core stores only an
opaque ``provider_reference`` plus card brand/last4 on
:class:`checkout.models.CardOnFile`; card numbers never touch
this codebase.

Deposit and no-show flows (booking-time deposits, cancellation
fees) are expressed against this seam and
:class:`checkout.models.DepositPolicy`, so they work with
whatever adapter a salon brings — or stay cleanly unavailable,
via :class:`NullAdapter`, when none is configured.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass
class StoredCardData:
    """What an adapter hands back after saving a card."""

    provider_reference: str
    brand: str = ""
    last4: str = ""
    exp_month: int | None = None
    exp_year: int | None = None


@dataclass
class ChargeOutcome:
    """The result of a charge or refund attempt."""

    ok: bool
    provider_reference: str = ""
    failure_reason: str = ""


class AdapterNotConfigured(Exception):
    """Raised when a payment action is attempted with no adapter."""


class PaymentAdapter:
    """The contract every payment adapter implements.

    Amounts are Decimal dollars. ``payment_token`` is whatever the
    adapter's own front-end produced (a tokenized card reference);
    core never sees card numbers.
    """

    name = ""

    def save_card(self, salon, client, payment_token):
        raise NotImplementedError

    def charge_saved_card(self, salon, card, amount, description=""):
        raise NotImplementedError

    def charge_token(self, salon, payment_token, amount, description=""):
        raise NotImplementedError

    def refund(self, salon, provider_reference, amount):
        raise NotImplementedError


class NullAdapter(PaymentAdapter):
    """The default: payments are not configured for this salon."""

    name = "none"

    def _refuse(self):
        raise AdapterNotConfigured(
            "No payment adapter is configured. Set "
            "OPENSALON_PAYMENT_ADAPTER to an adapter's dotted path "
            "to enable card payments."
        )

    def save_card(self, salon, client, payment_token):
        self._refuse()

    def charge_saved_card(self, salon, card, amount, description=""):
        self._refuse()

    def charge_token(self, salon, payment_token, amount, description=""):
        self._refuse()

    def refund(self, salon, provider_reference, amount):
        self._refuse()


def get_adapter():
    """The configured payment adapter, or :class:`NullAdapter`."""
    path = getattr(settings, "OPENSALON_PAYMENT_ADAPTER", "") or ""
    if not path:
        return NullAdapter()
    return import_string(path)()


def store_card(salon, client, payment_token):
    """Save a card through the adapter and record it on file."""
    from checkout.models import CardOnFile

    data = get_adapter().save_card(salon, client, payment_token)
    return CardOnFile.objects.create(
        salon=salon,
        client=client,
        provider_reference=data.provider_reference,
        brand=data.brand,
        last4=data.last4,
        exp_month=data.exp_month,
        exp_year=data.exp_year,
    )


def charge_card_on_file(card, amount, description=""):
    """Charge a card on file through the configured adapter."""
    return get_adapter().charge_saved_card(
        card.salon, card, Decimal(amount), description=description
    )
