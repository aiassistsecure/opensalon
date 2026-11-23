from decimal import ROUND_HALF_UP, Decimal

from django.db import models

from catalog.models import Product
from clients.models import Client
from saloncore.models import Salon, Service, StrictConstraints

# StrictConstraints rollout (NEDB DYOR §9.3/§9.4), following the
# saloncore/clients/team precedent: declared Meta.constraints are
# enforced in the app layer on save(), since schemaless NEDB
# creates no database-level constraints.


def _recorded_discount(value):
    """A recorded discount amount, with a missing value read as none.

    Rows written before the discount fields existed (or restored
    onto schemaless NEDB, which applies no column default on read)
    come back with ``discount_amount`` as None. A missing discount
    is no discount — never a crash in the totals below.
    """
    return Decimal("0.00") if value is None else value


class Sale(StrictConstraints):
    """A single checkout sale for a salon.

    Totals are never stored: ``total`` is computed from the sale's
    items, so the items are the one source of truth. How a sale is
    settled is a separate concern handled outside this model.

    Discounts are recorded, never folded into prices: a line may
    carry its own ``SaleItem.discount_amount`` and the sale may
    carry a whole-sale ``discount_amount`` on top. ``subtotal``
    is the pre-discount sum (``unit_price * quantity`` per line),
    ``discount_total`` is every recorded discount, and ``total``
    — the amount to settle — is ``subtotal - discount_total``.
    A discount amount is never negative (enforced below).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"
        VOIDED = "voided", "Voided"

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="sales"
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name="sale_discount_amount_nonnegative",
            )
        ]

    def __str__(self):
        return f"Sale #{self.pk} — {self.salon} ({self.status})"

    @property
    def subtotal(self):
        """Pre-discount sum of ``unit_price * quantity`` per line."""
        if self.pk is None:
            return Decimal("0.00")
        return sum(
            (item.subtotal for item in self.items.all()), Decimal("0.00")
        )

    @property
    def discount_total(self):
        """This sale's discount plus every line's discount."""
        if self.pk is None:
            return _recorded_discount(self.discount_amount)
        return _recorded_discount(self.discount_amount) + sum(
            (
                _recorded_discount(item.discount_amount)
                for item in self.items.all()
            ),
            Decimal("0.00"),
        )

    @property
    def total(self):
        """Amount to settle: subtotal less all recorded discounts.

        Decimal('0.00') for an empty, undiscounted sale.
        """
        if self.pk is None:
            return Decimal("0.00")
        return sum(
            (item.line_total for item in self.items.all()), Decimal("0.00")
        ) - _recorded_discount(self.discount_amount)


class SaleItem(StrictConstraints):
    """One line on a sale: a service rendered, a product sold, or a
    series/package sold.

    ``description`` and ``unit_price`` are snapshots taken at sale
    time, so later price-book or catalogue changes never rewrite a
    past sale. The optional service/product links are SET_NULL so
    deleting a catalogue entry preserves the sale record.

    ``discount_amount`` is this line's own recorded discount
    (default none, never negative): ``line_total`` is the line's
    subtotal less that discount, while ``unit_price`` stays the
    true snapshot price.
    """

    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        PRODUCT = "product", "Product"
        SERIES = "series", "Series"

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="items"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    description = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name="saleitem_discount_amount_nonnegative",
            )
        ]

    def __str__(self):
        label = self.description or self.get_kind_display()
        return f"{label} x{self.quantity} — {self.line_total}"

    @property
    def subtotal(self):
        """Pre-discount line amount: ``unit_price * quantity``."""
        return self.unit_price * self.quantity

    @property
    def line_total(self):
        """Line amount after this line's recorded discount."""
        return self.subtotal - _recorded_discount(self.discount_amount)


class Payment(models.Model):
    """One payment taken (or refunded) against a sale.

    Records only what core needs to reconcile a sale: the tender
    type, the amount, the outcome, and an opaque reference string
    supplied by whatever provider handled the tender. Core stores
    no provider-specific fields; adapters live outside core.
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        EXTERNAL = "external", "External tender"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="payments"
    )
    method = models.CharField(
        max_length=20, choices=Method.choices, default=Method.CASH
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    provider_reference = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return (
            f"Payment #{self.pk} — {self.get_method_display()} "
            f"{self.amount} ({self.status})"
        )


class Refund(models.Model):
    """An append-only record of money returned against a completed sale.

    A refund is its own record, never an edit: recording one does
    not mutate the original ``Sale`` or its ``Payment`` rows, so the
    original settlement stays exactly as taken. ``tender`` is a core
    ``Payment.Method`` slug and must match a tender actually used on
    the sale (enforced by ``checkout.refunds.record_refund``).
    """

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="refunds"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=500, blank=True, default="")
    tender = models.CharField(
        max_length=20,
        choices=Payment.Method.choices,
        default=Payment.Method.CASH,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Refund #{self.pk} — Sale #{self.sale_id}: {self.amount} ({self.tender})"


class Cashup(models.Model):
    """A close-out snapshot of a period's takings, grouped by tender.

    A cashup is a snapshot, not a lock: closing more than once a
    day is fine, a cashup never blocks or alters later sales, and
    sales recorded after it are simply picked up by the next one.
    ``tender_totals`` maps a payment method to its total for the
    period, with money stored as strings to preserve exact decimal
    values (same convention as ``Receipt.tender``).
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="cashups"
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    # Each entry: method slug -> total as a string, e.g. {"cash": "85.00"}.
    tender_totals = models.JSONField(default=dict, blank=True)
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return (
            f"Cashup #{self.pk} — {self.salon} "
            f"{self.period_start} to {self.period_end}: {self.total}"
        )


class Receipt(models.Model):
    """An immutable snapshot of a sale, taken when the receipt is issued.

    Lines, total and tender are copied at issue time so later edits
    to the sale, its items, its payments, or the price book never
    rewrite a receipt a client was already given. One receipt per
    sale (re-issuing replaces nothing; see receipts.build_receipt).
    """

    sale = models.OneToOneField(
        Sale, on_delete=models.CASCADE, related_name="receipt"
    )
    salon_name = models.CharField(max_length=200, blank=True)
    # Each line: {description, kind, quantity, unit_price, line_total}
    # with money stored as strings to preserve exact decimal values.
    lines = models.JSONField(default=list, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    # Each tender: {method, amount, status} as strings.
    tender = models.JSONField(default=list, blank=True)
    recipient_email = models.EmailField(blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]

    def __str__(self):
        return f"Receipt for Sale #{self.sale_id} — {self.total}"


class GiftCard(StrictConstraints):
    """A gift card issued by a salon, settled only through its ledger.

    The card's value is never stored as a mutable number:
    ``balance()`` is computed as ``initial_amount`` less the sum
    of its redeem transactions, so the transaction ledger is the
    one source of truth (the same pattern as ``Sale.total``).
    Core records the card and its movements only — how the
    purchaser paid for it is a tender concern handled elsewhere.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REDEEMED = "redeemed", "Redeemed"
        VOID = "void", "Void"

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="gift_cards"
    )
    code = models.CharField(max_length=64)
    initial_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    purchaser = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gift_cards_purchased",
    )
    recipient_name = models.CharField(max_length=200, blank=True, default="")
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["salon", "code"],
                name="giftcard_code_unique_per_salon",
            ),
            models.CheckConstraint(
                condition=models.Q(initial_amount__gte=0),
                name="giftcard_initial_amount_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Gift card {self.code} — {self.salon} ({self.status})"

    def balance(self):
        """Current balance: initial amount less all redemptions."""
        if self.pk is None:
            return self.initial_amount
        redeemed = sum(
            (
                txn.amount
                for txn in self.transactions.filter(
                    kind=GiftCardTransaction.Kind.REDEEM
                )
            ),
            Decimal("0.00"),
        )
        return self.initial_amount - redeemed

    def redeem(self, amount, sale=None, note=""):
        """Redeem ``amount`` against this card, recording the movement.

        Raises ValueError if the card is not active, the amount is
        not positive, or it exceeds the current balance. Redeeming
        the full balance flips the card to ``redeemed``.
        """
        amount = Decimal(amount)
        if self.status != self.Status.ACTIVE:
            raise ValueError(
                f"Gift card {self.code} is not active (status: {self.status})."
            )
        if amount <= 0:
            raise ValueError("Redemption amount must be positive.")
        if amount > self.balance():
            raise ValueError(
                f"Redemption of {amount} exceeds gift card balance "
                f"{self.balance()}."
            )
        txn = self.transactions.create(
            kind=GiftCardTransaction.Kind.REDEEM,
            amount=amount,
            sale=sale,
            note=note,
        )
        if self.balance() == 0:
            self.status = self.Status.REDEEMED
            self.save(update_fields=["status"])
        return txn


class GiftCardTransaction(StrictConstraints):
    """One movement on a gift card's ledger, append-only.

    ``amount`` is always positive; the ``kind`` says what the
    movement means. Only ``redeem`` movements reduce the card's
    computed balance today; ``issue``/``adjust``/``void`` rows are
    the audit trail for the card's lifecycle.
    """

    class Kind(models.TextChoices):
        ISSUE = "issue", "Issue"
        REDEEM = "redeem", "Redeem"
        ADJUST = "adjust", "Adjust"
        VOID = "void", "Void"

    card = models.ForeignKey(
        GiftCard, on_delete=models.CASCADE, related_name="transactions"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    sale = models.ForeignKey(
        Sale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gift_card_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="giftcardtxn_amount_positive",
            )
        ]

    def __str__(self):
        return (
            f"Gift card {self.card.code} — {self.get_kind_display()} "
            f"{self.amount}"
        )


class CardOnFile(StrictConstraints):
    """A client's saved card, as core is allowed to know it.

    The only processor datum stored is the opaque
    ``provider_reference`` the salon's payment adapter issued;
    brand and last4 are display facts. Card numbers never enter
    core — tokenization happens in the adapter's own front-end.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="cards_on_file"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="cards_on_file"
    )
    provider_reference = models.CharField(max_length=200)
    brand = models.CharField(max_length=40, blank=True, default="")
    last4 = models.CharField(max_length=4, blank=True, default="")
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["salon", "provider_reference"],
                name="cardonfile_reference_unique_per_salon",
            )
        ]

    def __str__(self):
        label = f"{self.brand} ····{self.last4}" if self.last4 else "Card"
        return f"{label} — {self.client}"


class DepositPolicy(StrictConstraints):
    """How one salon takes deposits and cancellation fees.

    The policy is arithmetic, not processing: ``deposit_due``
    says how much a booking owes up front; whether and how that
    amount is charged is the payment adapter's business.
    """

    class Kind(models.TextChoices):
        NONE = "none", "No deposit"
        FLAT = "flat", "Flat amount"
        PERCENT = "percent", "Percent of total"
        FULL_PREPAY = "full_prepay", "Full prepayment"

    salon = models.OneToOneField(
        Salon, on_delete=models.CASCADE, related_name="deposit_policy"
    )
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.NONE
    )
    value = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    cancellation_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    fee_within_hours = models.PositiveIntegerField(default=24)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__gte=0),
                name="depositpolicy_value_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(cancellation_fee__gte=0),
                name="depositpolicy_fee_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Deposit policy — {self.salon} ({self.get_kind_display()})"

    def deposit_due(self, service_price_total):
        """Deposit owed on a booking totalling ``service_price_total``."""
        total = Decimal(service_price_total)
        if self.kind == self.Kind.NONE or total <= 0:
            return Decimal("0.00")
        if self.kind == self.Kind.FLAT:
            return min(self.value, total)
        if self.kind == self.Kind.PERCENT:
            due = (total * self.value / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            return min(due, total)
        return total  # full prepayment
