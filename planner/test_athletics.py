from django.test import TestCase

from .athletics import parse_roster, sport_label
from .models import Profile, Team
from .roster import import_person, password_hash, school_email
from .schedule_sync import parse
from .test_schedule_sync import URL, page


class AthleticsTests(TestCase):
    def test_sport_labels(self):
        self.assertEqual(sport_label("mens-swimming-and-diving"), "Men's Swimming & Diving")
        self.assertEqual(sport_label("womens-basketball"), "Women's Basketball")
        self.assertEqual(sport_label("field-hockey"), "Field Hockey")
        self.assertEqual(sport_label("blue-white-womens-soccer"), "Blue & White Women's Soccer")

    def test_school_email_format(self):
        self.assertEqual(school_email("Jack", "O'Sullivan"), "jack.osullivan@assumption.edu")
        self.assertEqual(school_email("Damion", "Sparrow Jr."), "damion.sparrow@assumption.edu")
        self.assertEqual(school_email("Trevon", "Cole-Jenkins"), "trevon.cole-jenkins@assumption.edu")

    def test_parse_roster_separates_coaches(self):
        html = (
            '<span class="sidearm-roster-player-first-name">Sam</span><span class="sidearm-roster-player-last-name">Ray</span>'
            '<span class="sidearm-roster-player-first-name">Hal</span><span class="sidearm-roster-player-last-name">Head</span>'
            '<div class="sidearm-roster-coach-name"><p>Hal Head</p></div><div class="sidearm-roster-coach-title">Head Coach</div>'
            '<div class="sidearm-roster-coach-name"><p>Ann Assoc</p></div><div class="sidearm-roster-coach-title">Associate Head Coach</div>'
        )
        players, coaches = parse_roster(html)
        self.assertEqual(players, [("Sam", "Ray")])
        self.assertEqual(coaches, [("Hal", "Head", "Head Coach"), ("Ann", "Assoc", "Associate Head Coach")])

    def test_associate_head_coach_is_not_head_coach(self):
        stats = {"users_created": 0, "users_existing": 0, "teams_created": 0}
        for i, (first, title) in enumerate([("Hal", "Head Coach"), ("Ann", "Associate Head Coach")]):
            import_person(
                {"first_name": first, "last_name": "X", "email": f"{first.lower()}.x@assumption.edu",
                 "role": Profile.COACH, "sport": "Men's Basketball", "title": title, "order": i},
                stats, hashed_password=password_hash("pw"),
            )
        team = Team.objects.get(name="Assumption Men's Basketball")
        self.assertEqual(team.coach.first_name, "Hal")
        self.assertTrue(team.coach.check_password("pw"))

    def test_meet_placings_and_cancellations(self):
        games = parse(
            page(
                [
                    ("1", "2026-09-05T10:00:00", "Short Course Classic", False, "Course", "6th (176)", "a.png"),
                    ("2", "2026-09-19T00:00:00", "Invitational", False, "Course", "17th/32 (515)", "b.png"),
                    ("3", "2026-10-24T12:00:00", "Bridgeport", False, "Pool", "Canceled", "c.png"),
                ]
            ),
            base_url=URL,
        )
        self.assertEqual([g.result for g in games], ["6th (176)", "17th/32 (515)", "Canceled"])
        self.assertTrue(games[1].time_tba)
        self.assertFalse(games[0].time_tba)
