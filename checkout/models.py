from decimal import Decimal

from django.db import models

from catalog.models import Product
from clients.models import Client
from saloncore.models import Salon, Service


class Sale(models.Model):
    """A single checkout sale for a salon.

    Totals are never stored: ``total`` is computed from the sale's
    items, so the items are the one source of truth. How a sale is
    settled is a separate concern handled outside this model.
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
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Sale #{self.pk} — {self.salon} ({self.status})"

    @property
    def total(self):
        """Sum of item line totals; Decimal('0.00') for an empty sale."""
        if self.pk is None:
            return Decimal("0.00")
        return sum(
            (item.line_total for item in self.items.all()), Decimal("0.00")
        )


class SaleItem(models.Model):
    """One line on a sale: a service rendered, a product sold, or a
    series/package sold.

    ``description`` and ``unit_price`` are snapshots taken at sale
    time, so later price-book or catalogue changes never rewrite a
    past sale. The optional service/product links are SET_NULL so
    deleting a catalogue entry preserves the sale record.
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

    class Meta:
        ordering = ["id"]

    def __str__(self):
        label = self.description or self.get_kind_display()
        return f"{label} x{self.quantity} — {self.line_total}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


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
