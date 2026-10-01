"""URL configuration for the AOSB Vendor Management System."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.auth_urls")),
    path("", include("accounts.urls")),
    path("", include("vendors.urls")),
    path("", include("envelope1.urls")),
    path("", include("staff.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
