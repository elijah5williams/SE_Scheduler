"""Pull the latest news photos from the athletics site for the login page carousel."""
import html
import logging
import re
import threading
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import AthleticsPhoto
from .schedule_sync import ScheduleError, fetch

logger = logging.getLogger(__name__)

SITE = "https://assumptiongreyhounds.com"
MAX_PHOTOS = 5
REFRESH_AFTER = timedelta(hours=6)


def _meta(page, prop):
    m = re.search(rf'<meta[^>]+property="{prop}"[^>]+content="([^"]*)"', page) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]+property="{prop}"', page
    )
    return html.unescape(m.group(1)).strip() if m else ""


def latest_stories(limit=MAX_PHOTOS):
    """[(image_url, title, link)] for the newest stories that have a photo."""
    home = fetch(SITE + "/")
    links = list(dict.fromkeys(re.findall(r'"(/news/20\d\d/[^"\s]+\.aspx)"', home)))
    stories = []
    for path in links[: limit * 2]:
        try:
            page = fetch(SITE + path)
        except ScheduleError:
            continue
        image, title = _meta(page, "og:image"), _meta(page, "og:title")
        if not image or "logos" in image.lower() or not title:
            continue  # stories without a real photo use the site logo
        if image.startswith("/"):
            image = SITE + image
        # Ask Sidearm's image service for a bigger copy than the 800x450 share size.
        image = re.sub(r"height=\d+", "height=1000", re.sub(r"width=\d+", "width=1400", image))
        stories.append((image, title.split(" - ")[0].strip(), SITE + path))
        if len(stories) >= limit:
            break
    return stories


def refresh_photos():
    """Replace the stored photos with the latest ones. Keeps the old set if the site can't be read."""
    try:
        stories = latest_stories()
    except ScheduleError:
        logger.warning("Could not refresh athletics photos", exc_info=True)
        return 0
    if not stories:
        return 0
    with transaction.atomic():
        AthleticsPhoto.objects.all().delete()
        AthleticsPhoto.objects.bulk_create(
            AthleticsPhoto(image_url=img, title=title[:300], link=link, position=i)
            for i, (img, title, link) in enumerate(stories)
        )
    return len(stories)


def login_photos():
    """Photos for the login page. Starts a background refresh when they're missing or old."""
    photos = list(AthleticsPhoto.objects.all()[:MAX_PHOTOS])
    stale = not photos or photos[0].fetched_at < timezone.now() - REFRESH_AFTER
    if stale and cache.add("athletics-photos-refreshing", True, timeout=600):
        threading.Thread(target=_refresh_quietly, daemon=True).start()
    return photos


def _refresh_quietly():
    try:
        refresh_photos()
    except Exception:
        logger.warning("Athletics photo refresh failed", exc_info=True)
    finally:
        from django.db import connection

        connection.close()
