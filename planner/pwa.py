"""Installable web app ("Add to Home Screen"): the manifest, service worker and offline page.

These are served from the site root, not /static/, because a service worker can only
control pages at or below its own URL, and phones expect the manifest on the same origin.
"""

from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

APP_NAME = "Athlete Academic Assistant"
THEME_COLOR = "#0a2240"
BACKGROUND_COLOR = "#f5fafe"

# Bump when the service worker or offline page changes, so phones drop their old copy.
CACHE_VERSION = "2026-11-10b"


@login_not_required
@cache_control(max_age=3600)
def manifest(request):
    return JsonResponse(
        {
            "name": APP_NAME,
            "short_name": "Athlete Planner",
            "description": "Classes, practices, games and study time in one schedule.",
            "id": "/",
            "start_url": "/dashboard/?source=app",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "theme_color": THEME_COLOR,
            "background_color": BACKGROUND_COLOR,
            "icons": [
                {"src": static("planner/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": static("planner/icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {
                    "src": static("planner/icons/icon-maskable-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
            "shortcuts": [
                {"name": "Today", "url": "/dashboard/"},
                {"name": "Schedule", "url": "/schedule/"},
                {"name": "Study planner", "url": "/planner/"},
            ],
        },
        content_type="application/manifest+json",
    )


@login_not_required
@cache_control(no_cache=True)  # phones must always check for a newer service worker
def service_worker(request):
    response = render(
        request,
        "planner/sw.js",
        {
            "version": CACHE_VERSION,
            "icon": static("planner/icons/icon-192.png"),
            "badge": static("planner/icons/badge-96.png"),
            "precache": [
                "/offline/",
                static("planner/icons/icon-192.png"),
                static("planner/icons/favicon-48.png"),
                static("planner/app-mode.css"),
            ],
        },
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


@login_not_required
def offline(request):
    return render(request, "planner/offline.html", {"theme_color": THEME_COLOR})
