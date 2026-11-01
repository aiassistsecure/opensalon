import copy

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.db.models import Q


def _strict_validate(obj):
    """``validate_constraints()`` with the save()-path error surface."""
    try:
        obj.validate_constraints()
    except ValidationError as exc:
        raise IntegrityError("; ".join(exc.messages)) from exc


_LOOKUPS = {
    "exact", "iexact", "gt", "gte", "lt", "lte", "in", "isnull",
    "contains", "icontains",
}


def _strict_lookup(obj, key, expected):
    """Evaluate one simple field lookup against an in-memory instance."""
    parts = key.split("__")
    lookup = parts[-1] if len(parts) > 1 and parts[-1] in _LOOKUPS else "exact"
    if lookup != "exact":
        parts = parts[:-1]
    if len(parts) != 1:  # Related/spanning lookup: cannot judge in memory.
        return True
    try:
        field = obj._meta.get_field(parts[0])
        actual = getattr(obj, field.attname)
    except Exception:
        return True  # Unjudgeable: stay conservative, do not skip the check.
    if isinstance(actual, models.Model):
        actual = actual.pk
    if isinstance(expected, models.Model):
        expected = expected.pk
    try:
        if lookup == "exact":
            return actual == expected
        if lookup == "iexact":
            return str(actual).lower() == str(expected).lower()
        if lookup == "gt":
            return actual is not None and actual > expected
        if lookup == "gte":
            return actual is not None and actual >= expected
        if lookup == "lt":
            return actual is not None and actual < expected
        if lookup == "lte":
            return actual is not None and actual <= expected
        if lookup == "in":
            return actual in expected
        if lookup == "isnull":
            return (actual is None) == bool(expected)
        if lookup == "contains":
            return expected in actual
        if lookup == "icontains":
            return str(expected).lower() in str(actual).lower()
    except TypeError:
        return True
    return True


def _strict_condition_applies(condition, obj):
    """Whether a UniqueConstraint's ``condition`` Q holds for ``obj``."""
    if condition is None:
        return True
    if not isinstance(condition, Q):
        return True
    results = []
    for child in condition.children:
        if isinstance(child, Q):
            results.append(_strict_condition_applies(child, obj))
        else:
            results.append(_strict_lookup(obj, child[0], child[1]))
    if not results:
        return True
    combined = all(results) if condition.connector == Q.AND else any(results)
    return not combined if condition.negated else combined


def _strict_check_batch_unique(objs):
    """Reject duplicate UniqueConstraint keys *within* a batch.

    ``validate_constraints()`` only compares each instance against
    rows already in the database, so two not-yet-written instances
    carrying the same unique key would both pass it. This pairwise
    check closes that hole, honouring each constraint's condition.
    """
    if not objs:
        return
    model = objs[0]._meta.model
    for constraint in model._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint):
            continue
        fields = [model._meta.get_field(name) for name in constraint.fields]
        seen = {}
        for obj in objs:
            if not _strict_condition_applies(constraint.condition, obj):
                continue
            key = tuple(getattr(obj, field.attname) for field in fields)
            key = tuple(v.pk if isinstance(v, models.Model) else v for v in key)
            prior = seen.get(key)
            # Same object twice is one row; two unsaved (pk None)
            # instances are two rows even though both pks are None.
            if (prior is not None and prior is not obj
                    and not (prior.pk is not None and prior.pk == obj.pk)):
                raise IntegrityError(
                    f"StrictConstraints: duplicate {constraint.name} key "
                    f"{key} within the same batch."
                )
            seen.setdefault(key, obj)


class StrictConstraintsQuerySet(models.QuerySet):
    """Bulk-write guard for :class:`StrictConstraints` models (N-M18).

    NEDB DYOR §9.3: the declared schema catalog lives in the app
    layer — "NEDB stays schemaless; the strictness lives here."
    §9.4: savepoints are refused on NEDB, so every guard below
    validates the *whole* operation before issuing any write; a
    rejected batch/update therefore writes nothing, instead of
    relying on a transaction rollback to hide a partial write.

    - ``bulk_create()``: each instance is run through
      ``validate_constraints()`` (vs the database) plus an
      intra-batch unique-key check, before ``super()`` is called.
      ``ignore_conflicts=True`` / ``update_conflicts=True`` are
      explicit caller requests for database conflict handling and
      skip this guard — a KNOWN BYPASS on NEDB, whose schemaless
      store enforces no conflicts to ignore or update on.
    - ``bulk_update()``: same per-instance + intra-batch validation.
    - ``update()``: writes that touch no constrained field pass
      through untouched. Writes touching a constrained field are
      validated by materialising each affected row, applying the
      new values to a copy, and validating the copies (against the
      database and against each other). An expression value (e.g.
      ``F()``) on a constrained field cannot be judged in memory,
      so it is refused with ``IntegrityError`` rather than allowed
      to bypass the catalog.
    - Remaining known bypasses: raw SQL / cursor writes and any
      write made outside this ORM queryset never see the catalog.
    All guard failures raise ``IntegrityError`` — the same error
    surface as ``StrictConstraints.save()`` and as a database-level
    constraint on an enforcing backend.
    """

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False,
                    update_conflicts=False, update_fields=None,
                    unique_fields=None):
        objs = list(objs)
        if objs and not ignore_conflicts and not update_conflicts:
            for obj in objs:
                _strict_validate(obj)
            _strict_check_batch_unique(objs)
        return super().bulk_create(
            objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts, update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        if objs:
            for obj in objs:
                _strict_validate(obj)
            _strict_check_batch_unique(objs)
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def update(self, **kwargs):
        constrained = {}
        for constraint in self.model._meta.constraints:
            for name in getattr(constraint, "fields", ()):
                field = self.model._meta.get_field(name)
                constrained[name] = field
                constrained[field.attname] = field
        if not any(key in constrained for key in kwargs):
            return super().update(**kwargs)
        for key, value in kwargs.items():
            if key in constrained and hasattr(value, "resolve_expression"):
                raise IntegrityError(
                    f"StrictConstraints: refusing queryset update() with "
                    f"an expression value for constrained field {key!r}; "
                    f"it cannot be validated against the declared catalog."
                )
        rows = list(self)
        if not rows:
            return super().update(**kwargs)
        candidates = []
        for row in rows:
            candidate = copy.copy(row)
            for key, value in kwargs.items():
                setattr(candidate, key, value)
            candidates.append(candidate)
        _strict_check_batch_unique(candidates)
        for candidate in candidates:
            _strict_validate(candidate)
        return super().update(**kwargs)


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

    ``bulk_create()``/queryset ``update()`` bypass ``save()``; those
    paths are guarded separately by :class:`StrictConstraintsQuerySet`
    (N-M18, attached via ``objects`` below; see its docstring for the
    design and the remaining known bypasses).
    """

    objects = StrictConstraintsQuerySet.as_manager()

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
    # Whole source record preserved verbatim (TF-10), mirroring
    # bookings.Appointment.payload, catalog Product.payload and
    # clients Client.payload: fields with no mapped column here
    # are retained in ``payload``, never dropped on import. The
    # payload lives on Service (not ServicePrice) because the
    # importer consumes one source record per service; per-level
    # prices are derived from inside that record. Empty dict for
    # services created directly in OpenSalon.
    payload = models.JSONField(default=dict, blank=True)

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
