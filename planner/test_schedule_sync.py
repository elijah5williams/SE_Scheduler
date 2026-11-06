import json
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Assignment, Event, Profile, StaffMember, Team
from .schedule_sync import parse, parse_record, sync_team

URL = "https://assumptiongreyhounds.com/sports/football/schedule"


def page(games, record=(("Overall", "1-0"), ("PCT", "1.000"), ("Conf", "1-0"), ("PCT", "1.000"))):
    """A tiny Sidearm-style schedule page. games: (id, iso_start, opponent, home, venue, result, logo)."""
    ld, items = [], []
    for gid, start, opp, home, venue, result, logo in games:
        ld.append({
            "@type": "SportsEvent",
            "name": f"Assumption University {'Vs' if home else 'At'} {opp}",
            "homeTeam": {"name": "Assumption University"},
            "awayTeam": {"name": opp},
            "startDate": start,
            "location": {"name": venue},
        })
        side = "home" if home else "away"
        items.append(
            f'<li class="sidearm-schedule-game sidearm-schedule-{side}-game" data-game-id="{gid}">'
            f'<img class="lazyload" data-src="/images/logos/{logo}?width=80" alt="x">'
            f'<div class="sidearm-schedule-game-result text-italic"><span>{result}</span></div></li>'
        )
    rec = "".join(f"<li><span>{k}</span><span>{v}</span></li>" for k, v in record)
    return (
        f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        f'<div class="sidearm-schedule-record noprint"><ul>{rec}</ul></div><ul>{"".join(items)}</ul>'
    )


GAMES = [
    ("101", "2026-09-03T18:00:00", "Kutztown University", True, "Brian Kelly '83 Stadium", "L, 35-56", "Kutztown.png"),
    ("102", "2026-09-12T12:00:00", "Frostburg State University", False, "Bobcats Stadium", "", "STA Hawks.png"),
]


class ParseTests(TestCase):
    def test_reads_games_home_away_scores_and_logos(self):
        games = parse(page(GAMES), base_url=URL)
        self.assertEqual([g.external_id for g in games], ["101", "102"])
        first, second = games
        self.assertEqual(first.title, "vs. Kutztown University")
        self.assertEqual(second.title, "at Frostburg State University")
        self.assertEqual((first.date, first.start_time, first.end_time), (date(2026, 9, 3), time(18), time(21)))
        self.assertEqual(first.result, "L, 35-56")
        self.assertEqual(second.result, "")
        self.assertTrue(first.is_home)
        self.assertFalse(second.is_home)
        self.assertEqual(second.opponent_logo, "https://assumptiongreyhounds.com/images/logos/STA%20Hawks.png?width=80")

    def test_reads_season_record(self):
        self.assertEqual(
            parse_record(page(GAMES)),
            [["Overall", "1-0"], ["PCT", "1.000"], ["Conf", "1-0"], ["Conf PCT", "1.000"]],
        )


class SyncTests(TestCase):
    def setUp(self):
        self.athlete = User.objects.create_user("sray")
        self.team = Team.objects.create(name="Assumption Football", schedule_url=URL)
        self.team.athletes.add(self.athlete)

    def test_adds_games_to_every_athlete(self):
        self.assertEqual(sync_team(self.team, page=page(GAMES)), {"added": 2, "updated": 0, "removed": 0})
        self.assertEqual(Event.objects.filter(user=self.athlete, event_type=Event.GAME).count(), 2)
        self.team.refresh_from_db()
        self.assertEqual(self.team.season_record[0], ["Overall", "1-0"])

    def test_score_and_time_changes_reach_athletes(self):
        sync_team(self.team, page=page(GAMES))
        changed = [GAMES[0], ("102", "2026-09-12T13:00:00", *GAMES[1][2:5], "W, 24-19", GAMES[1][6])]
        self.assertEqual(sync_team(self.team, page=page(changed))["updated"], 1)
        game = Assignment.objects.get(external_id="102")
        self.assertEqual(game.result, "W, 24-19")
        copy = Event.objects.get(user=self.athlete, assignment=game)
        self.assertEqual(copy.start_time, time(13))
        self.assertIn("Final: W, 24-19", copy.notes)

    def test_cancelled_game_is_removed(self):
        sync_team(self.team, page=page(GAMES))
        self.assertEqual(sync_team(self.team, page=page(GAMES[:1]))["removed"], 1)
        self.assertFalse(Event.objects.filter(user=self.athlete, title__contains="Frostburg").exists())

    def test_coach_typed_events_are_left_alone(self):
        practice = Assignment.objects.create(
            team=self.team, title="Practice", date=date(2026, 9, 1), start_time=time(16), end_time=time(18)
        )
        sync_team(self.team, page=page(GAMES))
        self.assertTrue(Assignment.objects.filter(pk=practice.pk).exists())


class AssignTests(TestCase):
    """Coach assignments land on every athlete's schedule (this used to crash)."""

    def test_assignment_reaches_athletes(self):
        coach = User.objects.create_user("coach", password="pw")
        coach.profile.role = coach.profile.verified_role = Profile.COACH
        coach.profile.verification_status = Profile.VERIFIED
        coach.profile.save()
        athlete = User.objects.create_user("sray")
        team = Team.objects.create(name="Assumption Football", coach=coach)
        StaffMember.objects.create(team=team, user=coach, title="Head Coach")
        team.athletes.add(athlete)
        self.client.login(username="coach", password="pw")
        response = self.client.post(
            reverse("planner:assignment_create", args=[team.pk]),
            {"event_type": "practice", "title": "Practice", "date": "2026-11-10",
             "start_time": "16:00", "end_time": "18:00", "location": "Field"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Event.objects.filter(user=athlete, title="Practice", assignment__team=team).exists())


class CoachPagesTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user("coach", password="pw", first_name="Hal", last_name="Head")
        self.coach.profile.role = self.coach.profile.verified_role = Profile.COACH
        self.coach.profile.verification_status = Profile.VERIFIED
        self.coach.profile.save()
        self.team = Team.objects.create(name="Assumption Football", coach=self.coach)
        StaffMember.objects.create(team=self.team, user=self.coach, title="Head Coach")
        self.team.athletes.add(User.objects.create_user("sray", first_name="Sam", last_name="Ray"))
        self.client.login(username="coach", password="pw")

    def test_each_section_has_its_own_page(self):
        pages = {
            "planner:coach_dashboard": ("Team schedule", "Sam Ray"),
            "planner:coach_roster": ("Sam Ray", "Coaching staff<"),
            "planner:coach_staff": ("Head Coach", "Sam Ray"),
            "planner:coach_schedule": ("Team schedule", "Sam Ray"),
        }
        for name, (shown, hidden) in pages.items():
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, shown, msg_prefix=name)
            self.assertNotContains(response, hidden, msg_prefix=name)

    def test_athletes_cannot_open_coach_pages(self):
        User.objects.create_user("athlete", password="pw")
        self.client.login(username="athlete", password="pw")
        self.assertRedirects(self.client.get(reverse("planner:coach_roster")), reverse("planner:dashboard"), fetch_redirect_response=False)


class GameDayBannerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sray", password="pw-test-123")
        from django.utils import timezone as tz
        # Marked as just synced, so pages don't fetch the real website mid-test.
        self.team = Team.objects.create(name="Assumption Football", schedule_url=URL, schedule_synced_at=tz.now())
        self.team.athletes.add(self.user)
        self.client.login(username="sray", password="pw-test-123")

    def add_game(self, start, **extra):
        from django.utils import timezone as tz
        local = tz.localtime() + start
        return Assignment.objects.create(
            team=self.team, external_id="g1", event_type=Event.GAME, title="vs. Pace University",
            opponent="Pace University", is_home=True, date=local.date(),
            start_time=local.time().replace(second=0, microsecond=0),
            end_time=(local + timedelta(hours=3)).time().replace(second=0, microsecond=0) if (local + timedelta(hours=3)).date() == local.date() else time(23, 59),
            **extra,
        )

    def test_banner_shows_on_game_day_with_time_until_kickoff(self):
        from django.utils import timezone as tz
        if (tz.localtime() + timedelta(minutes=30)).date() != tz.localdate():
            self.skipTest("too close to midnight")
        self.add_game(timedelta(minutes=30))
        page = self.client.get(reverse("planner:dashboard"))
        self.assertContains(page, "Game day")
        self.assertContains(page, "vs. Pace University")
        self.assertContains(page, "in 2")  # "in 29 min" / "in 30 min"

    def test_banner_shows_final_score(self):
        from django.utils import timezone as tz
        if (tz.localtime() + timedelta(minutes=5)).date() != tz.localdate():
            self.skipTest("too close to midnight")
        self.add_game(timedelta(minutes=5), result="W, 35-20")  # a posted result means the game is final
        page = self.client.get(reverse("planner:schedule"))
        self.assertContains(page, "Final")
        self.assertContains(page, "W 35-20")

    def test_no_banner_without_a_game_today(self):
        self.assertNotContains(self.client.get(reverse("planner:dashboard")), "gameday-logo")


class HomePageTests(TestCase):
    def test_home_is_the_landing_page_with_next_game_and_scores(self):
        from django.utils import timezone as tz
        user = User.objects.create_user("sray", password="pw-test-123")
        team = Team.objects.create(name="Assumption Football", schedule_url=URL, schedule_synced_at=tz.now())
        team.athletes.add(user)
        today = tz.localdate()
        Assignment.objects.create(team=team, external_id="a", title="vs. Pace University", opponent="Pace University",
                                  is_home=True, date=today + timedelta(days=3), start_time=time(12), end_time=time(15))
        Assignment.objects.create(team=team, external_id="b", title="at Bentley University", opponent="Bentley University",
                                  is_home=False, date=today - timedelta(days=4), start_time=time(12), end_time=time(15), result="W, 29-27")
        self.client.login(username="sray", password="pw-test-123")
        response = self.client.post(reverse("login"), {"username": "sray", "password": "pw-test-123"})
        self.assertRedirects(response, reverse("planner:home"), fetch_redirect_response=False)
        page = self.client.get(reverse("planner:home"))
        self.assertContains(page, "vs. Pace University")      # ticket stub
        self.assertContains(page, "W 29-27")                  # live score ticker
        self.assertContains(page, reverse("planner:dashboard"))
        self.assertEqual(self.client.get(reverse("planner:dashboard")).status_code, 200)
