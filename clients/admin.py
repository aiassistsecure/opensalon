from django.contrib import admin

from clients.models import Client, ClientNote


class ClientNoteInline(admin.TabularInline):
    model = ClientNote
    extra = 0
    fields = ("author_name", "body", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "email",
        "phone",
        "salon",
        "sms_opt_in",
        "email_opt_in",
        "active",
        "created_at",
    )
    search_fields = ("first_name", "last_name", "email", "phone")
    list_filter = ("sms_opt_in", "email_opt_in", "active", "salon")
    list_select_related = ("salon",)
    readonly_fields = ("created_at",)
    inlines = (ClientNoteInline,)


@admin.register(ClientNote)
class ClientNoteAdmin(admin.ModelAdmin):
    """Persistent record notes: read-considerate in admin.

    Author, body, and creation time are front and centre; the
    timestamp is system-set and never editable.
    """

    list_display = ("client", "author_name", "body", "created_at")
    search_fields = (
        "body",
        "author_name",
        "client__first_name",
        "client__last_name",
        "client__email",
    )
    list_filter = ("created_at", "client__salon")
    list_select_related = ("client",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
