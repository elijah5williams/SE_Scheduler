"""Phone notifications (Web Push) for people who installed the app and turned them on.

No setup needed: the server creates its own keys the first time they're needed and keeps
them in the database. To use your own instead, set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY.
"""

import base64
import json
import logging
import threading
from urllib.parse import urlsplit

from django.conf import settings
from django.db import close_old_connections, transaction

from .models import PushKeys, PushSubscription

logger = logging.getLogger(__name__)

# The server sends a request to whatever address the phone gives us, so only accept the
# real push services. That stops anyone using us to make requests to other sites.
PUSH_SERVICE_HOSTS = (
    "fcm.googleapis.com",                 # Chrome, Android, Edge on some systems
    "updates.push.services.mozilla.com",  # Firefox
    "push.services.mozilla.com",
    "web.push.apple.com",                 # iPhone, iPad and Safari on Mac
    ".notify.windows.com",                # Edge on Windows
    ".push.apple.com",
)


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_keys():
    """A new (public, private) key pair, both base64url, in the format browsers and pywebpush use."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64url(public), _b64url(private)


def keys():
    """(public, private) keys: from the server settings if set, otherwise created once and saved."""
    if settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY:
        return settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY
    saved = PushKeys.objects.filter(pk=1).first()
    if saved is None:
        public, private = generate_keys()
        saved, _ = PushKeys.objects.get_or_create(pk=1, defaults={"public_key": public, "private_key": private})
    return saved.public_key, saved.private_key


def public_key():
    return keys()[0]


def enabled():
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False
    return True


def is_allowed_endpoint(endpoint):
    parts = urlsplit(endpoint or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == allowed or (allowed.startswith(".") and host.endswith(allowed)) for allowed in PUSH_SERVICE_HOSTS)


def _send_one(subscription, payload):
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription.as_subscription_info(),
            data=payload,
            vapid_private_key=keys()[1],
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=12 * 60 * 60,
            timeout=10,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):  # the phone turned notifications off or uninstalled the app
            subscription.delete()
        else:
            logger.warning("Push to %s failed: %s", subscription.user, exc)
    except Exception:
        logger.warning("Push to %s failed", subscription.user, exc_info=True)


def _deliver(subscription_ids, payload):
    try:
        for subscription in PushSubscription.objects.filter(pk__in=subscription_ids).select_related("user"):
            _send_one(subscription, payload)
    finally:
        close_old_connections()


def notify_users(users, title, body, url="/", tag=""):
    """Send a notification to every device these users turned notifications on for.

    Sent after the database change is saved, on a background thread so pages stay fast.
    """
    if not enabled():
        return 0
    user_ids = {getattr(user, "pk", user) for user in users}
    subscription_ids = list(PushSubscription.objects.filter(user_id__in=user_ids).values_list("pk", flat=True))
    if not subscription_ids:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})

    def start():
        if settings.PUSH_SEND_INLINE:
            _deliver(subscription_ids, payload)
        else:
            threading.Thread(target=_deliver, args=(subscription_ids, payload), daemon=True).start()

    transaction.on_commit(start)
    return len(subscription_ids)


# ---------------------------------------------------------------------------
# What the app notifies people about
# ---------------------------------------------------------------------------


def team_members(team):
    """Athletes on the team plus its coaching staff."""
    ids = set(team.athletes.values_list("pk", flat=True))
    ids.update(team.staff.values_list("user_id", flat=True))
    if team.coach_id:
        ids.add(team.coach_id)
    return ids


def _when(assignment):
    day = f"{assignment.date:%a %b} {assignment.date.day}"
    if getattr(assignment, "time_tba", False):
        return f"{day}, time TBA"
    return f"{day}, {assignment.start_time.strftime('%I:%M %p').lstrip('0')}"


def coach_event_changed(assignment, action, coach=None):
    """A coach added, changed or removed a practice, workout or other team event."""
    verb = {"added": "New", "updated": "Changed", "removed": "Cancelled"}[action]
    who = f" from {coach.get_full_name() or coach.username}" if coach else ""
    athletes = set(assignment.team.athletes.values_list("pk", flat=True))
    return notify_users(
        athletes,
        f"{verb}{who}: {assignment.title}",
        f"{assignment.team.name} · {_when(assignment)}" + (f" · {assignment.location}" if assignment.location else ""),
        url="/schedule/",
        tag=f"assignment-{assignment.pk}",
    )


def game_time_changed(assignment):
    return notify_users(
        team_members(assignment.team),
        f"Game time changed: {assignment.title}",
        f"Now {_when(assignment)}" + (f" · {assignment.location}" if assignment.location else ""),
        url="/schedule/",
        tag=f"game-{assignment.pk}",
    )


def game_final(assignment):
    result = f"{assignment.outcome} {assignment.score}" if assignment.outcome else assignment.result
    return notify_users(
        team_members(assignment.team),
        f"Final: {assignment.team.name.replace('Assumption ', '')} {result}",
        f"{assignment.matchup_word} {assignment.opponent}" if assignment.opponent else assignment.title,
        url="/",
        tag=f"game-{assignment.pk}",
    )


def game_removed(assignment):
    return notify_users(
        team_members(assignment.team),
        f"Removed from the schedule: {assignment.title}",
        f"Was {_when(assignment)}. Check with your coach for details.",
        url="/schedule/",
        tag=f"game-{assignment.pk}",
    )
