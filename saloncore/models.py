from django.core.exceptions import ValidationError
from django.db import models


class Salon(models.Model):
    """A salon using OpenSalon.

    The root record of a salon's own data: its display name and the
    locale defaults (timezone, currency) that later features build on.
    """

    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="UTC")
    currency = models.CharField(max_length=3, default="USD")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ServiceCategory(models.Model):
    """A grouping for services in a salon's price book (e.g. Haircuts)."""

    name = models.CharField(max_length=120)
    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="service_categories"
    )
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Service(models.Model):
    """A bookable service offered by a salon.

    Duration is split into three segments: hands-on service time,
    processing time (guest waits while product processes), and
    finishing time. Pricing is handled separately (not on this model).
    """

    name = models.CharField(max_length=200)
    # Stable id from the system the record was imported from (generic
    # field, never provider-named): imports key on it so re-imports
    # update in place. Blank for services created in OpenSalon.
    # Source ids are globally unique, so uniqueness is on the id.
    external_id = models.CharField(max_length=64, blank=True)
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name="services"
    )
    description = models.TextField(blank=True)
    service_minutes = models.PositiveIntegerField()
    processing_minutes = models.PositiveIntegerField(default=0)
    finishing_minutes = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id"],
                condition=models.Q(external_id__gt=""),
                name="uniq_service_external_id",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def total_minutes(self):
        return self.service_minutes + self.processing_minutes + self.finishing_minutes


class StaffLevel(models.Model):
    """A staff seniority / pricing tier within a salon (e.g. Level 6)."""

    name = models.CharField(max_length=120)
    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="staff_levels"
    )
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ServicePrice(models.Model):
    """The price of one service at one staff level.

    Plain salon-entered data: an amount and an optional "from" flag
    for starting-at pricing. No payment-provider concepts live here.
    """

    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="prices"
    )
    staff_level = models.ForeignKey(
        StaffLevel, on_delete=models.CASCADE, related_name="service_prices"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_from = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "staff_level"],
                name="uniq_service_price_per_level",
            )
        ]
        ordering = ["service", "staff_level"]

    def __str__(self):
        return f"{self.service} — {self.staff_level}: {self.amount}"


class PriceChangeQuerySet(models.QuerySet):
    """Append-only queryset: bulk update/delete are blocked."""

    def update(self, **kwargs):
        raise ValidationError("PriceChange records are append-only and cannot be modified.")

    def delete(self):
        raise ValidationError("PriceChange records are append-only and cannot be deleted.")


class PriceChange(models.Model):
    """Append-only audit row for a price change on a ServicePrice.

    Append-only is enforced at the model layer: ``save()`` raises
    ``ValidationError`` when updating an existing row, ``delete()``
    raises ``ValidationError``, and the custom queryset blocks bulk
    ``update()``/``delete()``. Creation is the only permitted write.
    """

    service_price = models.ForeignKey(
        ServicePrice, on_delete=models.CASCADE, related_name="changes"
    )
    changed_by = models.CharField(max_length=120, blank=True)
    old_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    new_amount = models.DecimalField(max_digits=10, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    objects = PriceChangeQuerySet.as_manager()

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.service_price}: {self.old_amount} -> {self.new_amount}"

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            # Also covers objects created in memory then re-saved.
            if PriceChange.objects.filter(pk=self.pk).exists():
                raise ValidationError(
                    "PriceChange records are append-only and cannot be modified."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "PriceChange records are append-only and cannot be deleted."
        )
