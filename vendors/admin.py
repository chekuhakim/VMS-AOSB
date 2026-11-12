from django.contrib import admin

from .models import Company, CompanyDocument


class CompanyDocumentInline(admin.TabularInline):
    model = CompanyDocument
    extra = 0
    readonly_fields = (
        "doc_type",
        "storage_path",
        "storage_backend",
        "original_filename",
        "version",
        "expiry_date",
        "uploaded_at",
    )
    can_delete = False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "registration_status",
        "registration_type",
        "wizard_step",
        "updated_at",
    )
    list_filter = ("registration_status", "registration_type", "includes_electrical_work")
    search_fields = (
        "name",
        "owner__username",
        "owner__email",
        "ssm_registration_number",
        "ic_number",
    )
    raw_id_fields = ("owner",)
    inlines = [CompanyDocumentInline]


@admin.register(CompanyDocument)
class CompanyDocumentAdmin(admin.ModelAdmin):
    list_display = ("company", "doc_type", "version", "original_filename", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("company__name", "original_filename")
