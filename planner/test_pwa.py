import json

from django.test import TestCase
from django.urls import reverse


class InstallableAppTests(TestCase):
    """The manifest, service worker and offline page work while logged out."""

    def test_manifest(self):
        response = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/dashboard/?source=app")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        self.assertTrue(any(icon.get("purpose") == "maskable" for icon in data["icons"]))

    def test_service_worker_served_from_root(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertContains(response, 'const OFFLINE_URL = "/offline/"')

    def test_offline_page(self):
        response = self.client.get(reverse("pwa_offline"))
        self.assertContains(response, "You're offline")

    def test_pages_link_the_manifest(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, "serviceWorker")
