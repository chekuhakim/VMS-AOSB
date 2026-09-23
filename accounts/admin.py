from django.contrib import admin

from .models import Notification, VendorProfile


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "created_at")
    search_fields = ("user__username", "user__email", "display_name")
    raw_id_fields = ("user",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "level", "created_at", "read_at", "dismissed_at")
    list_filter = ("level",)
    search_fields = ("title", "body", "user__email", "dedupe_key")
    raw_id_fields = ("user",)

