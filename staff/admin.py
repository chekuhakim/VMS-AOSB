from django.contrib import admin

from staff.models import Envelope1ItemEvaluation


@admin.register(Envelope1ItemEvaluation)
class Envelope1ItemEvaluationAdmin(admin.ModelAdmin):
    list_display = ("submission", "doc_type", "result", "evaluated_by", "evaluated_at")
    list_filter = ("result", "doc_type")
    search_fields = ("submission__company__name", "doc_type", "note")
    readonly_fields = ("created_at", "updated_at")
