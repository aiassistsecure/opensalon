from django.contrib import admin

from team.models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("staff_member", "event_type", "recorded_at")
    list_filter = ("event_type",)
