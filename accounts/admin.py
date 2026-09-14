from django.contrib import admin

from .models import VendorProfile


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "created_at")
    search_fields = ("user__username", "user__email", "display_name")
    raw_id_fields = ("user",)
