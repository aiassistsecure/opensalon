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
    """One line on a sale: a service rendered or a product sold.

    ``description`` and ``unit_price`` are snapshots taken at sale
    time, so later price-book or catalogue changes never rewrite a
    past sale. The optional service/product links are SET_NULL so
    deleting a catalogue entry preserves the sale record.
    """

    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        PRODUCT = "product", "Product"

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
