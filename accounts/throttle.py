"""Small cache-based limits on repeated failures (wrong passwords, wrong team codes).

Counts live in Django's cache. With the default in-memory cache each server process keeps
its own counts, which is enough to stop someone trying thousands of guesses.
"""

from django.core.cache import cache


def client_ip(request):
    """The visitor's IP address.

    Behind Render's proxy REMOTE_ADDR is the proxy, so use the last X-Forwarded-For entry:
    that one is added by the proxy itself, so a visitor can't fake it.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


class Limit:
    def __init__(self, name, max_failures, window_seconds):
        self.name = name
        self.max_failures = max_failures
        self.window = window_seconds

    def _key(self, ident):
        return f"throttle:{self.name}:{str(ident).lower()}"

    def blocked(self, ident):
        return cache.get(self._key(ident), 0) >= self.max_failures

    def fail(self, ident):
        key = self._key(ident)
        if cache.add(key, 1, self.window):
            return
        try:
            cache.incr(key)
        except ValueError:  # expired between add and incr
            cache.set(key, 1, self.window)

    def reset(self, ident):
        cache.delete(self._key(ident))


FIFTEEN_MINUTES = 15 * 60

# Wrong passwords for one account, and from one address (covers guessing across many accounts).
login_by_username = Limit("login-user", max_failures=5, window_seconds=FIFTEEN_MINUTES)
login_by_ip = Limit("login-ip", max_failures=20, window_seconds=FIFTEEN_MINUTES)

# Wrong team codes per signed-in user.
team_code_by_user = Limit("team-code", max_failures=10, window_seconds=60 * 60)
