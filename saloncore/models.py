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

    def __str__(self):
        return self.name

    @property
    def total_minutes(self):
        return self.service_minutes + self.processing_minutes + self.finishing_minutes
