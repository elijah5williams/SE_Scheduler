"""iCalendar (.ics) feed so people can subscribe from their phone or Google Calendar."""
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.utils import timezone

from .models import Assignment, Event, Profile, RoutineSession, StudySession, Team

PAST_DAYS = 30
FUTURE_DAYS = 180


def _escape(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line):
    """Lines longer than 75 bytes must be folded (RFC 5545)."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(day, at):
    local = timezone.make_aware(datetime.combine(day, at), timezone.get_current_timezone())
    return local.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _vevent(uid, day, start, end, summary, location="", description="", all_day=False, cancelled=False):
    lines = ["BEGIN:VEVENT", f"UID:{uid}@se-scheduler", f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc):%Y%m%dT%H%M%SZ}"]
    if all_day:
        lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
    else:
        end_day = day if end > start else day + timedelta(days=1)
        lines += [f"DTSTART:{_utc(day, start)}", f"DTEND:{_utc(end_day, end)}"]
    lines.append(f"SUMMARY:{_escape(summary)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if cancelled:
        lines.append("STATUS:CANCELLED")
    lines.append("END:VEVENT")
    return lines


def _game_summary(game, team_name):
    sport = team_name.removeprefix("Assumption ").strip()
    title = f"{sport}: {game.matchup_word} {game.opponent or game.title}"
    if game.result and not game.is_cancelled:
        title += f" ({game.result})"
    return title


def build_calendar(user):
    today = timezone.localdate()
    days = [today - timedelta(days=PAST_DAYS) + timedelta(days=i) for i in range(PAST_DAYS + FUTURE_DAYS + 1)]
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Athlete Academic Assistant//SE Scheduler//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape('Greyhounds · ' + (user.get_full_name() or user.username))}",
        "X-WR-TIMEZONE:America/New_York", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H",
    ]

    if user.profile.role == Profile.COACH:
        # Coaches see their teams' games and the practices they've assigned.
        for game in Assignment.objects.filter(team__in=Team.coached_by(user)).select_related("team"):
            for day in days:
                if day == game.date or (game.repeat_weekly and day > game.date and day.weekday() == game.date.weekday()
                                        and (not game.repeat_until or day <= game.repeat_until)):
                    summary = _game_summary(game, game.team.name) if game.external_id else f"{game.team.name}: {game.title}"
                    lines += _vevent(f"a{game.pk}-{day:%Y%m%d}", day, game.start_time, game.end_time, summary,
                                     game.location, game.notes, all_day=game.time_tba, cancelled=game.is_cancelled)
    else:
        events = list(Event.objects.filter(user=user).select_related("assignment__team"))
        for day in days:
            for event in events:
                if not event.occurs_on(day):
                    continue
                game = event.assignment if event.assignment_id else None
                if game and game.external_id:
                    summary = _game_summary(game, game.team.name)
                    all_day, cancelled = game.time_tba, game.is_cancelled
                else:
                    summary = event.title if not game else f"{game.team.name}: {event.title}"
                    all_day = cancelled = False
                lines += _vevent(f"e{event.pk}-{day:%Y%m%d}", day, event.start_time, event.end_time, summary,
                                 event.location, event.notes, all_day=all_day, cancelled=cancelled)
        for s in StudySession.objects.filter(task__user=user, date__range=(days[0], days[-1])).select_related("task"):
            lines += _vevent(f"s{s.pk}", s.date, s.start_time, s.end_time, f"Study: {s.task.title}",
                             description=f"{s.task.course} · planned by your Smart Planner")
        for r in RoutineSession.objects.filter(routine__user=user, date__range=(days[0], days[-1])).select_related("routine"):
            lines += _vevent(f"r{r.pk}", r.date, r.start_time, r.end_time, r.routine.title)

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
