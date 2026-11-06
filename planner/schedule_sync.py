"""Keep a team's games in step with its schedule page on the athletics website.

Works with Sidearm Sports sites such as assumptiongreyhounds.com. Each game on the
page carries structured data (opponent, kickoff, venue) and a stable game id, so a
game keeps the same id even if its date or time changes.
"""
import html
import json
import logging
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Assignment, Event, Team

logger = logging.getLogger(__name__)

SCHOOL_PREFIX = "Assumption"
GAME_LENGTH = timedelta(hours=3)
STALE_AFTER = timedelta(hours=1)
GAME_DAY_STALE_AFTER = timedelta(minutes=10)  # check for final scores more often on game day
USER_AGENT = "Mozilla/5.0 (compatible; SE-Scheduler schedule sync)"


class ScheduleError(Exception):
    pass


@dataclass
class Game:
    external_id: str
    title: str
    date: object
    start_time: object
    end_time: object
    location: str
    result: str
    opponent: str = ""
    opponent_logo: str = ""
    is_home: object = None

    def fields(self):
        return {
            "event_type": Event.GAME,
            "title": self.title,
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "location": self.location,
            "result": self.result,
            "opponent": self.opponent,
            "opponent_logo": self.opponent_logo,
            "is_home": self.is_home,
            "repeat_weekly": False,
            "repeat_until": None,
        }


def _ssl_context():
    # Python from python.org on macOS ships without trusted certificates, so HTTPS downloads
    # fail with CERTIFICATE_VERIFY_FAILED. certifi provides the standard list on every computer.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def fetch(url, timeout=10):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # network errors, timeouts, HTTP errors
        raise ScheduleError(f"Could not download {url}: {exc}") from exc


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _is_us(name):
    return (name or "").lower().startswith(SCHOOL_PREFIX.lower())


def parse(page, base_url=""):
    """Return the games on a Sidearm schedule page, in page order."""
    events = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        events += [item for item in items if isinstance(item, dict) and item.get("@type") == "SportsEvent"]
    if not events:
        raise ScheduleError("No games found on the page. Is this a team schedule page?")

    # The visible list has the game ids, results, home/away and opponent logos,
    # in the same order as the structured data.
    details = []
    for item in re.split(r'<li class="sidearm-schedule-game ', page)[1:]:
        game_id = re.search(r'data-game-id="(\d+)"', item)
        result = re.search(r'<div class="sidearm-schedule-game-result[^"]*"[^>]*>(.*?)</div>', item, re.S)
        match = re.match(r"([WLT]),?\s*(\d+\s*-\s*\d+)", _text(result.group(1)) if result else "")
        classes = item.split('"', 1)[0]
        logo = re.search(r'<img[^>]*(?:data-src|src)="(/images/logos/[^"]+)"', item)
        details.append(
            {
                "id": game_id.group(1) if game_id else "",
                "result": f"{match.group(1)}, {match.group(2).replace(' ', '')}" if match else "",
                "home": False if "away-game" in classes else True if "home-game" in classes else None,
                "logo": urllib.parse.quote(
                    urllib.parse.urljoin(base_url, html.unescape(logo.group(1))), safe=":/?&=%"
                ) if logo and base_url else "",
            }
        )
    if len(details) != len(events):
        details = [{"id": "", "result": "", "home": None, "logo": ""}] * len(events)

    games = []
    for event, detail in zip(events, details):
        game_id, result = detail["id"], detail["result"]
        try:
            start = datetime.fromisoformat(event["startDate"])
        except (KeyError, TypeError, ValueError):
            continue
        home = (event.get("homeTeam") or {}).get("name", "")
        away = (event.get("awayTeam") or {}).get("name", "")
        opponent = away if _is_us(home) else home
        # The site lists Assumption as "home" for every game, so trust the page's home/away label,
        # then the event name ("Assumption University At Pace University").
        at_home = detail["home"]
        if at_home is None:
            at_home = " at " not in f" {event.get('name', '').lower()} "
        place = event.get("location") or {}
        venue = place.get("name") or (place.get("address") or {}).get("streetAddress") or ""
        start_time = start.time()
        if start_time == time(0, 0):  # time not announced yet
            start_time = time(12, 0)
        end = datetime.combine(start.date(), start_time) + GAME_LENGTH
        end_time = end.time() if end.date() == start.date() else time(23, 59)
        games.append(
            Game(
                external_id=game_id or f"{start.date().isoformat()}:{opponent}",
                title=f"{'vs.' if at_home else 'at'} {opponent}",
                date=start.date(),
                start_time=start_time,
                end_time=end_time,
                location=venue,
                result=result,
                opponent=opponent,
                opponent_logo=detail["logo"],
                is_home=at_home,
            )
        )
    return games


def parse_record(page):
    """The season record bar: [["Overall", "6-2"], ["PCT", ".750"], ["Conf", "5-0"], ["Conf PCT", "1.000"], ...]"""
    box = re.search(r'class="sidearm-schedule-record[^"]*"(.*?)</ul>', page, re.S)
    if not box:
        return []
    record = []
    for label, value in re.findall(r"<li[^>]*>\s*<span[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>", box.group(1), re.S):
        label, value = _text(label), _text(value)
        if label == "PCT" and record and record[-1][0] == "Conf":
            label = "Conf PCT"
        record.append([label, value])
    return record


@transaction.atomic
def sync_team(team, page=None):
    """Bring the team's synced games in line with its schedule page. Returns counts of what changed."""
    if not team.schedule_url:
        raise ScheduleError(f"{team.name} has no schedule link.")
    page = page if page is not None else fetch(team.schedule_url)
    games = parse(page, base_url=team.schedule_url)

    counts = {"added": 0, "updated": 0, "removed": 0}
    existing = {a.external_id: a for a in team.assignments.exclude(external_id="")}
    for game in games:
        assignment = existing.pop(game.external_id, None)
        if assignment is None:
            assignment = Assignment.objects.create(team=team, external_id=game.external_id, **game.fields())
            assignment.push_to_team()
            counts["added"] += 1
            continue
        changed = {k: v for k, v in game.fields().items() if getattr(assignment, k) != v}
        if changed:
            for key, value in changed.items():
                setattr(assignment, key, value)
            assignment.save()
            assignment.sync_events()
            counts["updated"] += 1
    for gone in existing.values():  # dropped from the website, e.g. cancelled
        gone.delete()
        counts["removed"] += 1

    team.season_record = parse_record(page) or team.season_record
    team.schedule_synced_at = timezone.now()
    team.save(update_fields=["schedule_synced_at", "season_record"])
    return counts


def sync_if_stale(teams):
    """Quietly refresh any of these teams not synced in the last hour. Never raises."""
    now = timezone.now()
    today = timezone.localdate()
    for team in teams:
        if not team.schedule_url:
            continue
        game_day = team.assignments.filter(date=today).exclude(external_id="").exists()
        cutoff = now - (GAME_DAY_STALE_AFTER if game_day else STALE_AFTER)
        if team.schedule_synced_at and team.schedule_synced_at > cutoff:
            continue
        # After a failed try, wait 10 minutes before trying again so pages stay fast.
        if not cache.add(f"schedule-sync-attempt-{team.pk}", True, timeout=600):
            continue
        try:
            sync_team(team, page=fetch(team.schedule_url, timeout=5))
        except Exception:
            logger.warning("Schedule sync failed for %s", team, exc_info=True)


def game_hub(team, now=None):
    """What the game-day panel needs: next game (with kickoff time), recent results and the season record."""
    now = now or timezone.localtime()
    tz = timezone.get_current_timezone()
    games = list(team.assignments.exclude(external_id="").order_by("date", "start_time"))
    for game in games:
        game.kickoff = timezone.make_aware(datetime.combine(game.date, game.start_time), tz)
        game.final_whistle = timezone.make_aware(datetime.combine(game.date, game.end_time), tz)
    live = next((g for g in games if g.kickoff <= now < g.final_whistle and not g.result), None)
    upcoming = [g for g in games if g.kickoff > now and not g.result]
    played = [g for g in games if g.result]
    return {
        "team": team,
        "live_game": live,
        "next_game": upcoming[0] if upcoming else None,
        "recent": list(reversed(played))[:3],
        "record": team.season_record,
        "games": games,
    }
