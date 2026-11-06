from unittest import mock

from django.test import TestCase

from .models import AthleticsPhoto
from .photos import latest_stories, refresh_photos
from .schedule_sync import ScheduleError

HOME = '<script>var x = {"url":"/news/2026/11/3/volleyball-wins.aspx"}; var y = {"url":"/news/2026/11/2/logo-only.aspx"};</script>'
STORY = (
    '<meta property="og:title" content="Volleyball rolls past SNHU - Assumption Greyhounds">'
    '<meta property="og:image" content="https://images.sidearmdev.com/fit?url=x%2fimages%2fvb.jpg&amp;height=450&amp;width=800&amp;type=jpeg">'
)
LOGO_ONLY = '<meta property="og:title" content="Notice"><meta property="og:image" content="https://site/images/logos/site/site.png">'


def fake_fetch(url, timeout=10):
    if url.endswith("/"):
        return HOME
    return STORY if "volleyball" in url else LOGO_ONLY


class PhotoTests(TestCase):
    @mock.patch("planner.photos.fetch", side_effect=fake_fetch)
    def test_reads_story_photos_and_skips_logo_only_stories(self, _):
        stories = latest_stories()
        self.assertEqual(len(stories), 1)
        image, title, link = stories[0]
        self.assertEqual(title, "Volleyball rolls past SNHU")
        self.assertIn("width=1400", image)
        self.assertIn("height=1000", image)
        self.assertTrue(link.endswith("/news/2026/11/3/volleyball-wins.aspx"))

    @mock.patch("planner.photos.fetch", side_effect=ScheduleError("offline"))
    def test_keeps_old_photos_when_site_is_down(self, _):
        AthleticsPhoto.objects.create(image_url="https://x/a.jpg", title="Old", link="https://x/a")
        self.assertEqual(refresh_photos(), 0)
        self.assertEqual(AthleticsPhoto.objects.count(), 1)

    def test_login_page_shows_photos_or_falls_back(self):
        with mock.patch("planner.photos._running_tests", return_value=False), mock.patch("planner.photos.threading.Thread") as thread:
            self.assertContains(self.client.get("/accounts/login/"), "School. Sport.")
            AthleticsPhoto.objects.create(image_url="https://x/a.jpg", title="Big win", link="https://x/a")
            response = self.client.get("/accounts/login/")
        self.assertContains(response, "Big win")
        self.assertContains(response, 'src="https://x/a.jpg"')
        thread.assert_called()  # no photos yet, so a background refresh was started
