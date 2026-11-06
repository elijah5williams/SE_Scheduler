from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .athletics import parse_player_cards
from .models import Assignment, AthleteBio, Event, Profile, Team
from .weather import _place, describe, forecast_for

CARD = (
    '<li class="sidearm-list-card-item" data-player-id="1"><div class="sidearm-roster-player-image" '
    "style=\"background-image:url('/images/2026/9/1/Ray__Sam.jpg?width=400');\">"
    '<a class="sidearm-roster-player-bio-link" href="/sports/football/roster/sam-ray/1">Bio</a>'
    '<span class="sidearm-roster-player-jersey hide-on-small-down"><span> 7 </span></span></div>'
    '<span class="sidearm-roster-player-first-name">Sam</span><span class="sidearm-roster-player-last-name">Ray</span>'
    '<div class="sidearm-list-card-details-item sidearm-roster-player-position-short"> QB </div>'
    '<span class="sidearm-roster-player-height">6\'2&quot;</span><span class="sidearm-roster-player-academic-year">Jr.</span>'
    '<span class="sidearm-roster-player-hometown">Worcester, Mass.</span></li>'
)


class SpotlightTests(TestCase):
    def test_reads_player_cards(self):
        card = parse_player_cards(CARD)[("Sam", "Ray")]
        self.assertEqual(card["number"], "7")
        self.assertEqual(card["position"], "QB")
        self.assertEqual(card["height"], '6\'2"')
        self.assertEqual(card["year"], "Jr.")
        self.assertEqual(card["hometown"], "Worcester, Mass.")
        self.assertTrue(card["photo_url"].startswith("https://assumptiongreyhounds.com/images/"))
        self.assertTrue(card["bio_url"].endswith("/roster/sam-ray/1"))

    def test_home_shows_spotlight(self):
        user = User.objects.create_user("sam.ray", password="pw-test-123", first_name="Sam", last_name="Ray")
        team = Team.objects.create(name="Assumption Football")
        team.athletes.add(user)
        AthleteBio.objects.create(team=team, user=user, photo_url="https://x/sam.jpg", number="7", position="QB", hometown="Worcester, Mass.")
        self.client.login(username="sam.ray", password="pw-test-123")
        page = self.client.get(reverse("planner:home"))
        self.assertContains(page, "Meet the Greyhounds")
        self.assertContains(page, "#7")
        self.assertContains(page, "Worcester, Mass.")


class WeatherTests(TestCase):
    def test_place_parsing(self):
        self.assertEqual(_place("Frostburg, MD / Bobcats Stadium"), ("Frostburg", "Maryland"))
        self.assertEqual(_place("New Haven, Conn. / Jess Dow Field"), ("New Haven", "Connecticut"))
        self.assertIsNone(_place("Brian Kelly '83 Stadium"))

    def test_codes(self):
        self.assertEqual(describe(0)[0], "Clear")
        self.assertEqual(describe(63)[0], "Rain")

    def test_forecast_reads_kickoff_hour(self):
        team = Team.objects.create(name="Assumption Football")
        game = Assignment.objects.create(team=team, external_id="g", title="vs. Pace", opponent="Pace", is_home=True,
                                         date=timezone.localdate() + timedelta(days=1), start_time=time(13), end_time=time(16))
        hourly = {"time": [f"h{h}" for h in range(24)], "temperature_2m": [40 + h for h in range(24)],
                  "precipitation_probability": [70] * 24, "weather_code": [61] * 24, "wind_speed_10m": [12.4] * 24}
        with mock.patch("planner.weather._running_tests", return_value=False), \
             mock.patch("planner.weather._get_json", return_value={"hourly": hourly}):
            wx = forecast_for(game)
        self.assertEqual(wx, {"temp": 53, "text": "Rain", "icon": "🌧️", "rain": 70, "wind": 12})


class CalendarFeedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sam", password="pw-test-123", first_name="Sam", last_name="Ray")
        p = self.user.profile
        p.role = p.verified_role = Profile.STUDENT
        p.verification_status = Profile.VERIFIED
        p.save()
        self.team = Team.objects.create(name="Assumption Football", schedule_synced_at=timezone.now())
        self.team.athletes.add(self.user)
        game = Assignment.objects.create(team=self.team, external_id="g1", event_type=Event.GAME, title="vs. Pace University",
                                         opponent="Pace University", is_home=True, date=timezone.localdate() + timedelta(days=2),
                                         start_time=time(12), end_time=time(15), location="Brian Kelly '83 Stadium")
        game.push_to(self.user)
        Event.objects.create(user=self.user, title="CSC 305", event_type=Event.CLASS, date=timezone.localdate(),
                             start_time=time(10), end_time=time(11), repeat_weekly=True, weekdays="0,2,4")

    def test_feed_needs_no_login_and_lists_games_and_classes(self):
        token = self.user.profile.get_calendar_token()
        response = self.client.get(reverse("planner:calendar_feed", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertIn("SUMMARY:Football: vs. Pace University", body)
        self.assertIn("LOCATION:Brian Kelly '83 Stadium", body)
        self.assertGreater(body.count("SUMMARY:CSC 305"), 10)  # weekly class repeats
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split("\r\n")))

    def test_bad_or_reset_token_is_refused(self):
        self.assertEqual(self.client.get(reverse("planner:calendar_feed", args=["nope"])).status_code, 404)
        old = self.user.profile.get_calendar_token()
        self.client.login(username="sam", password="pw-test-123")
        self.client.post(reverse("planner:calendar_reset"))
        self.assertEqual(self.client.get(reverse("planner:calendar_feed", args=[old])).status_code, 404)

    def test_schedule_page_offers_subscribe_links(self):
        self.client.login(username="sam", password="pw-test-123")
        page = self.client.get(reverse("planner:schedule"))
        self.assertContains(page, "Add your schedule to your calendar")
        self.assertContains(page, "webcal://")
        self.assertContains(page, "calendar.google.com")
