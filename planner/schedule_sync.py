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
import sys
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import push
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
    time_tba: bool = False

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
            "time_tba": self.time_tba,
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
        result_text = _text(result.group(1)) if result else ""
        match = re.match(r"([WLT]),?\s*(\d+\s*-\s*\d+)", result_text)
        # Meets post a placing ("6th (176)", "1st/8 (+9)"); some events are cancelled.
        placing = re.match(r"(\d+(?:st|nd|rd|th)(?:/\d+)?(?:\s*\([^)]*\))?)", result_text)
        status = re.match(r"(Cancel+ed|Postponed)", result_text, re.I)
        classes = item.split('"', 1)[0]
        logo = re.search(r'<img[^>]*(?:data-src|src)="(/images/logos/[^"]+)"', item)
        details.append(
            {
                "id": game_id.group(1) if game_id else "",
                "result": (
                    f"{match.group(1)}, {match.group(2).replace(' ', '')}" if match
                    else placing.group(1) if placing
                    else status.group(1).capitalize() if status
                    else ""
                ),
                "home": False if "away-game" in classes else True if "home-game" in classes else None,
                "neutral": "neutral-game" in classes,
                "logo": urllib.parse.quote(
                    urllib.parse.urljoin(base_url, html.unescape(logo.group(1))), safe=":/?&=%"
                ) if logo and base_url else "",
            }
        )
    if len(details) != len(events):
        details = [{"id": "", "result": "", "home": None, "neutral": False, "logo": ""}] * len(events)

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
        at_home = None if detail["neutral"] else detail["home"]
        if at_home is None and not detail["neutral"]:
            at_home = " at " not in f" {event.get('name', '').lower()} "
        place = event.get("location") or {}
        venue = place.get("name") or (place.get("address") or {}).get("streetAddress") or ""
        start_time = start.time()
        time_tba = start_time == time(0, 0)  # the site uses midnight for "time not announced"
        if time_tba:
            start_time = time(12, 0)
        end = datetime.combine(start.date(), start_time) + GAME_LENGTH
        end_time = end.time() if end.date() == start.date() else time(23, 59)
        games.append(
            Game(
                external_id=game_id or f"{start.date().isoformat()}:{opponent}",
                title=f"{'at' if at_home is False else 'vs.'} {opponent}",
                date=start.date(),
                start_time=start_time,
                end_time=end_time,
                location=venue,
                result=result,
                opponent=opponent,
                opponent_logo=detail["logo"],
                is_home=at_home,
                time_tba=time_tba,
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


def _notify_game_change(assignment, changed, had_result):
    """Tell the team when an upcoming game moves, or when a final score is posted."""
    if assignment.result and not had_result:
        if assignment.date >= timezone.localdate() - timedelta(days=2):  # not old games on first sync
            push.game_final(assignment)
    elif changed.keys() & {"date", "start_time", "time_tba"} and assignment.date >= timezone.localdate():
        push.game_time_changed(assignment)


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
            had_result = bool(assignment.result)
            for key, value in changed.items():
                setattr(assignment, key, value)
            assignment.save()
            assignment.sync_events()
            counts["updated"] += 1
            _notify_game_change(assignment, changed, had_result)
    for gone in existing.values():  # dropped from the website, e.g. cancelled
        if gone.date >= timezone.localdate() and not gone.result:
            push.game_removed(gone)
        gone.delete()
        counts["removed"] += 1

    team.season_record = parse_record(page) or team.season_record
    team.schedule_synced_at = timezone.now()
    team.save(update_fields=["schedule_synced_at", "season_record"])
    return counts


def _sync_in_background(team_ids):
    from django.db import connection

    try:
        for team in Team.objects.filter(pk__in=team_ids):
            try:
                sync_team(team, page=fetch(team.schedule_url, timeout=8))
            except Exception:
                logger.warning("Schedule sync failed for %s", team, exc_info=True)
    finally:
        connection.close()


def sync_if_stale(teams, background=None):
    """
    Refresh any of these teams not synced in the last hour (10 minutes on game day). Never raises.
    By default the download runs in a background thread so pages don't wait on the athletics site;
    the fresh scores show on the next page load.
    """
    if background is None:
        background = not _running_tests()
    due = []
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
        due.append(team.pk)
    if not due:
        return
    if background:
        threading.Thread(target=_sync_in_background, args=(due,), daemon=True).start()
    else:
        _sync_in_background(due)


def _running_tests():
    return "test" in sys.argv[1:2]


def game_hub(team, now=None):
    """What the game-day panel needs: next game (with kickoff time), recent results and the season record."""
    now = now or timezone.localtime()
    tz = timezone.get_current_timezone()
    games = list(team.assignments.exclude(external_id="").order_by("date", "start_time"))
    for game in games:
        game.kickoff = timezone.make_aware(datetime.combine(game.date, game.start_time), tz)
        game.final_whistle = timezone.make_aware(datetime.combine(game.date, game.end_time), tz)
    live = next((g for g in games if g.kickoff <= now < g.final_whistle and not g.result and not g.time_tba), None)
    upcoming = [g for g in games if g.kickoff > now and not g.result]
    played = [g for g in games if g.result and not g.is_cancelled]
    today_game = next((g for g in games if g.date == now.date() and not g.is_cancelled), None)
    if today_game:
        today_game.is_live = today_game is live
        minutes = max(0, int((today_game.kickoff - now).total_seconds() // 60))
        hours = round(minutes / 60)
        today_game.until = f"in {minutes} min" if minutes < 60 else f"in {hours} hr{'s' if hours != 1 else ''}"
    scored = any(g.outcome for g in played) or not played and any(g.is_home is not None for g in games)
    return {
        "team": team,
        "sport": team.name.removeprefix("Assumption ").strip() or team.name,
        "event_word": "game" if scored else "event",
        "results_word": "scores" if scored else "results",
        "weather": _weather(live or (upcoming[0] if upcoming else None)),
        "live_game": live,
        "today_game": today_game,
        "next_game": upcoming[0] if upcoming else None,
        "recent": list(reversed(played))[:3],
        "record": team.season_record,
        "games": games,
    }


def _weather(game):
    from .weather import forecast_for

    try:
        return forecast_for(game)
    except Exception:
        logger.warning("Weather failed", exc_info=True)
        return None
