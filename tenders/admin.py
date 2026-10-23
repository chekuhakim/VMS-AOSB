from django.contrib import admin

from tenders.models import RFQ, Project, Quotation, TenderAward


class RFQInline(admin.TabularInline):
    model = RFQ
    extra = 0
    fields = ("code", "title", "quantity", "unit", "position")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "status", "closing_at", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "title")
    inlines = [RFQInline]


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ("rfq", "company", "status", "submitted_at")
    list_filter = ("status",)
    search_fields = ("company__name", "rfq__code", "rfq__project__reference")
    # Sealed bids: no price column in the list view
    readonly_fields = ("declaration_version", "declaration_text", "declaration_accepted_at", "declaration_ip")


@admin.register(TenderAward)
class TenderAwardAdmin(admin.ModelAdmin):
    list_display = ("rfq", "quotation", "status", "recommended_at", "decided_at")
    list_filter = ("status",)
