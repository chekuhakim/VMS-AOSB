from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only admin for ISO audit evidence — no add/change/delete."""

    list_display = (
        "log_id",
        "created_at",
        "actor_label",
        "category",
        "action",
        "object_type",
        "object_id",
        "ip_address",
    )
    list_filter = ("category",)
    search_fields = ("log_id", "actor_label", "action", "object_id")
    readonly_fields = (
        "log_id",
        "created_at",
        "actor",
        "actor_label",
        "category",
        "action",
        "changes",
        "object_type",
        "object_id",
        "ip_address",
    )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
