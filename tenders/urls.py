from django.urls import path

from tenders import views_staff as staff
from tenders import views_vendor as vendor

app_name = "tenders"

urlpatterns = [
    # Vendor
    path("project/", vendor.project_list, name="project_list"),
    path("project/<int:pk>/", vendor.project_detail, name="project_detail"),
    path("project/<int:pk>/rfq/<int:rfq_pk>/quote/", vendor.quotation_form, name="quotation_form"),
    path("project/rfq/<int:rfq_pk>/document/", vendor.vendor_rfq_document, name="vendor_rfq_document"),
    path("your-bid/", vendor.your_bids, name="your_bids"),
    path("your-bid/<int:pk>/withdraw/", vendor.quotation_withdraw, name="quotation_withdraw"),
    path("your-bid/<int:pk>/document/", vendor.vendor_quotation_document, name="vendor_quotation_document"),
    # Staff
    path("tender/", staff.tender_list, name="tender_list"),
    path("tender/new/", staff.project_create, name="project_create"),
    path("tender/<int:pk>/", staff.tender_detail, name="tender_detail"),
    path("tender/<int:pk>/edit/", staff.project_edit, name="project_edit"),
    path("tender/<int:pk>/publish/", staff.project_publish, name="project_publish"),
    path("tender/<int:pk>/cancel/", staff.project_cancel, name="project_cancel"),
    path("tender/<int:pk>/rfq/new/", staff.rfq_save, name="rfq_add"),
    path("tender/<int:pk>/rfq/<int:rfq_pk>/edit/", staff.rfq_save, name="rfq_edit"),
    path("tender/<int:pk>/rfq/<int:rfq_pk>/delete/", staff.rfq_delete, name="rfq_delete"),
    path("tender/rfq/<int:rfq_pk>/document/", staff.rfq_document, name="rfq_document"),
    path("tender/rfq/<int:rfq_pk>/recommend/", staff.award_recommend, name="award_recommend"),
    path("tender/award/<int:award_pk>/decide/", staff.award_decide, name="award_decide"),
    path("tender/quotation/<int:pk>/document/", staff.quotation_document, name="quotation_document"),
]
