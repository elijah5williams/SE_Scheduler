from django.contrib import admin
from django.urls import include, path

from planner import pwa


urlpatterns = [
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("sw.js", pwa.service_worker, name="pwa_service_worker"),
    path("offline/", pwa.offline, name="pwa_offline"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("planner.urls")),
]
