from django.contrib import admin

from .models import (
    Envelope1Document,
    Envelope1Submission,
    FinancialStatement,
    PastProject,
    PrimarySupplier,
    WithdrawalRequest,
)


class FinancialStatementInline(admin.TabularInline):
    model = FinancialStatement
    extra = 0
    raw_id_fields = ("document",)


class PrimarySupplierInline(admin.TabularInline):
    model = PrimarySupplier
    extra = 0


class PastProjectInline(admin.TabularInline):
    model = PastProject
    extra = 0
    raw_id_fields = ("document",)


class Envelope1DocumentInline(admin.TabularInline):
    model = Envelope1Document
    extra = 0
    readonly_fields = (
        "doc_type",
        "version",
        "storage_path",
        "original_filename",
        "expiry_date",
        "uploaded_at",
    )


@admin.register(Envelope1Submission)
class Envelope1SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "cycle_number",
        "status",
        "wizard_step",
        "locked_at",
        "submitted_at",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("company__name", "legal_name")
    inlines = [
        Envelope1DocumentInline,
        FinancialStatementInline,
        PrimarySupplierInline,
        PastProjectInline,
    ]
    raw_id_fields = ("company", "locked_by")


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("submission", "status", "requested_by", "created_at", "reviewed_at")
    list_filter = ("status",)
    raw_id_fields = ("submission", "requested_by", "reviewed_by")


@admin.register(Envelope1Document)
class Envelope1DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "submission",
        "doc_type",
        "version",
        "expiry_date",
        "uploaded_at",
    )
    list_filter = ("doc_type",)
