from django.core.exceptions import ValidationError
from django.db import IntegrityError, models


class StrictConstraints(models.Model):
    """App-layer enforcement of the model's declared ``Meta.constraints``.

    NEDB is schemaless: its migrations create no database-level unique
    or check constraints, so a declared constraint exists only in the
    models — and the models are the declared catalog, with no second
    copy in the database adapter (NEDB strictness probe, 2026-10-31,
    §5; NEDB DYOR §9.3: "NEDB stays schemaless; the strictness lives
    here"; §9.4 on atomicity). Django already evaluates that catalog
    in Python via ``validate_constraints()`` (probe §3), but the ORM
    write path never calls it — ``save()`` bypasses ``full_clean()``.
    This mixin closes that gap on the write path, following the
    in-repo model-layer precedent of ``PriceChange.save()``.

    ``save()`` behaviour (probe §5):
    - If the model declares no ``Meta.constraints``, save normally.
    - Otherwise call ``self.validate_constraints()`` before writing,
      skipping any constraint that cannot be judged from this save:
      a constraint whose fields are not all in ``update_fields``
      (when ``update_fields`` is given) or whose fields include a
      deferred (not-yet-loaded) field is skipped, via the ``exclude``
      argument Django's constraint validation already honours.
    - A ``ValidationError`` from constraint validation is converted
      to ``IntegrityError`` (probe §6): that is the error callers and
      tests already expect from a constraint violation — it is what
      a database-level constraint raises on enforcing backends, so
      the error surface is identical on every backend.

    ``bulk_create()``/queryset ``update()`` bypass ``save()``; guarding
    those paths is a separate slice, not this mixin.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if any(constraints for _cls, constraints in self.get_constraints()):
            exclude = self._strict_constraints_exclude(kwargs.get("update_fields"))
            try:
                self.validate_constraints(exclude=exclude or None)
            except ValidationError as exc:
                raise IntegrityError("; ".join(exc.messages)) from exc
        super().save(*args, **kwargs)

    def _strict_constraints_exclude(self, update_fields):
        """Field names ``validate_constraints()`` must not judge now.

        With ``update_fields``, every field not being saved is
        excluded, so a constraint is judged only when all of its
        fields are part of this save. Deferred fields are excluded
        for the same reason: their in-memory value is not loaded.
        """
        exclude = {field.name for field in self._meta.local_fields}
        exclude |= {field.attname for field in self._meta.local_fields}
        if update_fields is not None:
            saved = set(update_fields)
            exclude -= saved
            # update_fields may name a FK by field name or attname.
            for field in self._meta.local_fields:
                if field.name in saved or field.attname in saved:
                    exclude.discard(field.name)
                    exclude.discard(field.attname)
        else:
            exclude = set()
        deferred = self.get_deferred_fields()
        exclude |= deferred
        exclude |= {
            field.name
            for field in self._meta.local_fields
            if field.attname in deferred
        }
        return exclude


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


class Service(StrictConstraints):
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


class ServicePrice(StrictConstraints):
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
