from django.contrib import admin

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ("name", "timezone", "currency", "created_at", "updated_at")
    search_fields = ("name", "timezone", "currency")
    list_filter = ("currency",)


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "salon", "sort_order", "active")
    search_fields = ("name", "salon__name")
    list_filter = ("active", "salon")
    list_editable = ("sort_order", "active")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "service_minutes",
        "processing_minutes",
        "finishing_minutes",
        "active",
    )
    search_fields = ("name", "description", "category__name")
    list_filter = ("active", "category")


@admin.register(StaffLevel)
class StaffLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "salon", "sort_order", "active")
    search_fields = ("name", "salon__name")
    list_filter = ("active", "salon")
    list_editable = ("sort_order", "active")


@admin.register(ServicePrice)
class ServicePriceAdmin(admin.ModelAdmin):
    list_display = ("service", "staff_level", "amount", "is_from", "active")
    search_fields = ("service__name", "staff_level__name")
    list_filter = ("active", "is_from", "staff_level")


@admin.register(PriceChange)
class PriceChangeAdmin(admin.ModelAdmin):
    """Append-only audit: viewable in admin, never editable."""

    list_display = (
        "service_price",
        "old_amount",
        "new_amount",
        "changed_by",
        "changed_at",
    )
    search_fields = ("service_price__service__name", "changed_by", "note")
    list_filter = ("changed_at",)
    readonly_fields = (
        "service_price",
        "changed_by",
        "old_amount",
        "new_amount",
        "changed_at",
        "note",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
