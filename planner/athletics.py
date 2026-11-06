"""Build every Assumption team from the athletics website: rosters, coaching staff and schedules.

Each sport has a roster page (/sports/<slug>/roster) and a schedule page (/sports/<slug>/schedule)
on assumptiongreyhounds.com. Accounts are created with first.last@assumption.edu emails.
"""
import html
import re

from django.db import transaction

from .models import AthleteBio, Profile, Team
from .roster import import_person, school_email, team_name_for
from .schedule_sync import ScheduleError, fetch, sync_team

SITE = "https://assumptiongreyhounds.com"

# Used if the home page can't be read. Order is how the site lists them.
DEFAULT_SPORTS = [
    "baseball", "mens-basketball", "mens-cross-country", "football", "mens-golf", "mens-ice-hockey",
    "mens-lacrosse", "mens-soccer", "mens-swimming-and-diving", "mens-tennis", "mens-track-and-field",
    "womens-basketball", "womens-cross-country", "field-hockey", "women-flag-football", "womens-golf",
    "womens-ice-hockey", "womens-lacrosse", "womens-rowing", "womens-soccer", "softball",
    "womens-swimming-and-diving", "womens-tennis", "womens-track-and-field", "womens-volleyball",
    "blue-white-mens-soccer", "blue-white-softball", "blue-white-womens-ice-hockey", "blue-white-womens-soccer",
]


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def discover_sports():
    """Sport slugs linked from the athletics home page, falling back to the built-in list."""
    try:
        page = fetch(SITE + "/")
    except ScheduleError:
        return list(DEFAULT_SPORTS)
    slugs = []
    for slug in re.findall(r'href="/sports/([a-z0-9-]+)/roster"', page):
        if slug not in slugs:
            slugs.append(slug)
    return slugs or list(DEFAULT_SPORTS)


def sport_label(slug):
    """'mens-swimming-and-diving' -> "Men's Swimming & Diving", 'blue-white-womens-soccer' -> "Blue & White Women's Soccer"."""
    words = slug.replace("blue-white", "blue-&-white").replace("-and-", "-&-").split("-")
    fixed = {"mens": "Men's", "womens": "Women's", "women": "Women's", "&": "&"}
    return " ".join(fixed.get(w, w.capitalize()) for w in words)


def parse_roster(page):
    """Return (players, coaches): players as (first, last), coaches as (first, last, title)."""
    coach_names = [_text(n) for n in re.findall(r'class="sidearm-roster-coach-name"[^>]*>\s*<p>(.*?)</p>', page, re.S)]
    coach_titles = [_text(t) for t in re.findall(r'class="sidearm-roster-coach-title"[^>]*>(.*?)</', page, re.S)]
    coaches = []
    for i, name in enumerate(coach_names):
        first, _, last = name.partition(" ")
        title = coach_titles[i] if i < len(coach_titles) else ""
        coaches.append((first, last, title))

    taken = {name for name in coach_names}
    players, seen = [], set()
    pairs = re.findall(
        r'sidearm-roster-player-first-name">(.*?)</span>.*?sidearm-roster-player-last-name">(.*?)</span>', page, re.S
    )
    for first, last in pairs:
        first, last = _text(first), _text(last)
        if not first or f"{first} {last}" in taken or (first, last) in seen:
            continue
        seen.add((first, last))
        players.append((first, last))
    return players, coaches


def _field(card, cls):
    m = re.search(rf'class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</(?:span|div)>', card, re.S)
    return _text(m.group(1)) if m else ""


def parse_player_cards(page):
    """{(first, last): {photo_url, number, position, height, year, hometown, bio_url}} from roster cards."""
    cards = {}
    for card in re.split(r'<li class="sidearm-list-card-item"', page)[1:]:
        first, last = _field(card, "sidearm-roster-player-first-name"), _field(card, "sidearm-roster-player-last-name")
        if not first:
            continue
        photo = re.search(r"background-image:url\('([^']+)'\)", card) or re.search(r'data-src="([^"]+\.(?:jpe?g|png)[^"]*)"', card)
        link = re.search(r'href="(/sports/[^"]+/roster/[^"]+)"', card)
        photo_url = html.unescape(photo.group(1)) if photo else ""
        if photo_url.startswith("/"):
            photo_url = SITE + photo_url
        if "placeholder" in photo_url.lower() or "/logos/" in photo_url:
            photo_url = ""
        cards[(first, last)] = {
            "photo_url": photo_url,
            "number": _field(card, "sidearm-roster-player-jersey"),
            "position": _field(card, "sidearm-roster-player-position-short") or _field(card, "sidearm-roster-player-position"),
            "height": _field(card, "sidearm-roster-player-height"),
            "year": _field(card, "sidearm-roster-player-academic-year"),
            "hometown": _field(card, "sidearm-roster-player-hometown"),
            "bio_url": SITE + link.group(1) if link else "",
        }
    return cards


@transaction.atomic
def sync_sport(slug, hashed_password=None, with_schedule=True):
    """Create/update one sport's team, people and schedule. Returns a summary dict."""
    label = sport_label(slug)
    summary = {"sport": label, "athletes": 0, "coaches": 0, "games": 0, "skipped": "", "users_created": 0}
    page = fetch(f"{SITE}/sports/{slug}/roster")
    players, coaches = parse_roster(page) if "sidearm-roster" in page else ([], [])  # some clubs link elsewhere
    cards = parse_player_cards(page)
    if not players and not coaches:
        summary["skipped"] = "no roster posted"
        return summary

    stats = {"users_created": 0, "users_existing": 0, "teams_created": 0}
    rows = [
        {"first_name": f, "last_name": l, "email": school_email(f, l), "role": Profile.COACH,
         "sport": label, "title": title, "order": i}
        for i, (f, l, title) in enumerate(coaches)
    ] + [
        {"first_name": f, "last_name": l, "email": school_email(f, l), "role": Profile.STUDENT,
         "sport": label, "title": "", "order": 0}
        for f, l in players
    ]
    team = None
    for row in rows:
        if not row["email"].split("@")[0].strip("."):
            continue  # name with no usable letters
        user, team = import_person(row, stats, hashed_password=hashed_password)
        card = cards.get((row["first_name"], row["last_name"]))
        if card and row["role"] == Profile.STUDENT:
            AthleteBio.objects.update_or_create(team=team, user=user, defaults=card)
    summary.update(athletes=len(players), coaches=len(coaches), users_created=stats["users_created"])

    team = team or Team.objects.get(name=team_name_for(label))
    schedule_url = f"{SITE}/sports/{slug}/schedule"
    if team.schedule_url != schedule_url:
        team.schedule_url = schedule_url
        team.save(update_fields=["schedule_url"])
    if with_schedule:
        try:
            sync_team(team)
        except ScheduleError as exc:
            summary["skipped"] = f"schedule not updated: {exc}"
        summary["games"] = team.assignments.exclude(external_id="").count()
    return summary
