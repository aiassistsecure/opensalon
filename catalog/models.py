from django.db import models
from django.db.models import Sum

from saloncore.models import Salon, StrictConstraints

# N-M-next: StrictConstraints rollout completed for catalog (NEDB
# DYOR §9.3/§9.4) — declared Meta.constraints are enforced in the
# app layer on save(), since schemaless NEDB creates no database-
# level constraints. Product was the one constrained model the
# N-M17 rollout missed, so its conditional UniqueConstraint
# (uniq_product_external_id) went unenforced on NEDB.


class Product(StrictConstraints):
    """A retail product sold by a salon.

    Carries an optional SKU and an optional barcode. The barcode is
    for standard keyboard-wedge USB/Bluetooth scanners used for
    stocktake, receiving, and scan-to-add at checkout; no proprietary
    hardware is assumed.

    Stock is NOT stored on this model. A product's current stock is
    derived purely from its ``StockMovement`` rows (see
    ``current_stock``) — movements are the one source of truth, so
    there is deliberately no mutable stock counter field to drift
    out of sync with the movement log.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=64, blank=True)
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    active = models.BooleanField(default=True)
    # Source-system identity and verbatim shape (DYOR section 9):
    # the source record's own id, its brand/category/type labels
    # exactly as the source spells them, its cost, and the whole
    # source document preserved in ``payload`` so nothing the
    # source knew is lost in the mapping.
    external_id = models.CharField(max_length=64, blank=True)
    brand_name = models.CharField(max_length=120, blank=True)
    category_name = models.CharField(max_length=120, blank=True)
    product_type = models.CharField(max_length=32, blank=True)
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id"],
                condition=models.Q(external_id__gt=""),
                name="uniq_product_external_id",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def current_stock(self):
        """Current stock, derived as the sum of all movement deltas.

        Returns 0 when the product has no movements yet.
        """
        total = self.stock_movements.aggregate(total=Sum("quantity_delta"))["total"]
        return total or 0

    @classmethod
    def lookup_by_barcode(cls, barcode):
        """Return the product with ``barcode``, or None.

        Blank/whitespace codes and unknown codes both return None, so
        a scanner read can be passed straight in without pre-checks.
        """
        code = (barcode or "").strip()
        if not code:
            return None
        return cls.objects.filter(barcode=code).first()

    @classmethod
    def lookup_by_sku(cls, sku):
        """Return the product with ``sku``, or None (blank/unknown)."""
        code = (sku or "").strip()
        if not code:
            return None
        return cls.objects.filter(sku=code).first()

    @classmethod
    def lookup_by_scan(cls, code):
        """Return a product by barcode, falling back to SKU, or None.

        This is the scan-to-add helper: a scanner delivers one code
        and the caller does not need to know which kind it is.
        Barcode wins when a code somehow matches both.
        """
        return cls.lookup_by_barcode(code) or cls.lookup_by_sku(code)


class StockMovement(models.Model):
    """A single change to a product's stock — the stock event log.

    Each row records a signed ``quantity_delta`` for one product:
    receiving adds stock (positive delta, e.g. ``+10``), a sale
    removes it (negative, e.g. ``-1``), an adjustment records an
    explicit correction in either direction, and a stocktake records
    the *difference* between the counted stock and the stock derived
    up to that point (counted minus derived — positive, negative, or
    zero), never the absolute count. Because every kind is stored as
    a delta, current stock is simply the sum of all deltas (see
    ``Product.current_stock``) and the full history stays auditable.
    """

    class Kind(models.TextChoices):
        RECEIVE = "receive", "Receive"
        SALE = "sale", "Sale"
        ADJUSTMENT = "adjustment", "Adjustment"
        STOCKTAKE = "stocktake", "Stocktake"

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_movements"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    quantity_delta = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.product} {self.kind} {self.quantity_delta:+d}"
