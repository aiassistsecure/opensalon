from django.db import models

from saloncore.models import Salon


class Product(models.Model):
    """A retail product sold by a salon.

    Carries an optional SKU and an optional barcode. The barcode is
    for standard keyboard-wedge USB/Bluetooth scanners used for
    stocktake, receiving, and scan-to-add at checkout; no proprietary
    hardware is assumed.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=64, blank=True)
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
