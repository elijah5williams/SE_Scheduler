import os
import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from .models import StaffMember, Team

HEADER = "first_name,last_name,email,role,sport\n"


class ImportRosterTests(TestCase):
    def write_csv(self, body):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        handle.write(HEADER + body)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def run_import(self, body, *args):
        call_command("import_roster", self.write_csv(body), *args, stdout=open(os.devnull, "w"))

    def test_creates_verified_accounts_grouped_by_team(self):
        self.run_import(
            "Pat,Lee,PLee@assumption.edu,coach,Football\n"
            "Sam,Ray,sray@assumption.edu,athlete,Football\n"
            "Kim,Fox,kfox@assumption.edu,athlete,Women's Soccer\n"
        )
        football = Team.objects.get(name="Assumption Football")
        self.assertEqual(football.coach.email, "plee@assumption.edu")
        self.assertEqual([u.email for u in football.athletes.all()], ["sray@assumption.edu"])
        self.assertTrue(Team.objects.filter(name="Assumption Women's Soccer").exists())

        coach = User.objects.get(email="plee@assumption.edu")
        self.assertTrue(coach.profile.is_verified_coach)
        self.assertTrue(coach.is_active)
        self.assertFalse(coach.has_usable_password())
        self.assertTrue(User.objects.get(email="sray@assumption.edu").profile.is_verified_student)

    def test_rerun_does_not_duplicate(self):
        body = "Sam,Ray,sray@assumption.edu,athlete,Football\n"
        self.run_import(body)
        self.run_import(body)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Team.objects.count(), 1)

    def test_athlete_on_two_teams(self):
        self.run_import(
            "Sam,Ray,sray@assumption.edu,athlete,Football\n"
            "Sam,Ray,sray@assumption.edu,athlete,Men's Track & Field\n"
        )
        self.assertEqual(User.objects.get().teams.count(), 2)

    def test_rejects_bad_rows_and_saves_nothing(self):
        with self.assertRaises(CommandError):
            self.run_import(
                "Sam,Ray,sray@assumption.edu,athlete,Football\n"
                "Bad,Domain,someone@gmail.com,athlete,Football\n"
            )
        self.assertFalse(User.objects.exists())

    def test_dry_run_saves_nothing(self):
        self.run_import("Sam,Ray,sray@assumption.edu,athlete,Football\n", "--dry-run")
        self.assertFalse(User.objects.exists())
        self.assertFalse(Team.objects.exists())

    def test_send_invites_emails_new_accounts(self):
        self.run_import("Sam,Ray,sray@assumption.edu,athlete,Football\n", "--send-invites")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sray@assumption.edu"])

    def test_coach_can_sign_in_to_dashboard_after_setting_password(self):
        self.run_import("Pat,Lee,plee@assumption.edu,coach,Football\n")
        coach = User.objects.get()
        coach.set_password("pw-12345")
        coach.save()
        self.client.login(username=coach.username, password="pw-12345")
        response = self.client.get(reverse("planner:coach_dashboard"))
        self.assertContains(response, "Assumption Football")

    def test_password_option_sets_password_for_everyone(self):
        self.run_import("Sam,Ray,sray@assumption.edu,athlete,Football\n")
        self.run_import(
            "Sam,Ray,sray@assumption.edu,athlete,Football\n"
            "Pat,Lee,plee@assumption.edu,coach,Football\n",
            "--password", "greyhounds",
        )
        for user in User.objects.all():
            self.assertTrue(user.check_password("greyhounds"), user.email)
        self.assertTrue(self.client.login(username="plee", password="greyhounds"))

    def test_password_and_invites_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            self.run_import(
                "Sam,Ray,sray@assumption.edu,athlete,Football\n",
                "--password", "greyhounds", "--send-invites",
            )

    def test_titles_build_coaching_staff(self):
        call_command(
            "import_roster",
            self.write_csv_with_titles(
                "Ann,Assist,aassist@assumption.edu,coach,Football,Defensive Coordinator\n"
                "Hal,Head,hhead@assumption.edu,coach,Football,Head Coach\n"
                "Sam,Ray,sray@assumption.edu,athlete,Football,\n"
            ),
            stdout=open(os.devnull, "w"),
        )
        team = Team.objects.get(name="Assumption Football")
        self.assertEqual(team.coach.email, "hhead@assumption.edu")
        self.assertEqual(
            {(m.user.email, m.title) for m in team.staff.all()},
            {("aassist@assumption.edu", "Defensive Coordinator"), ("hhead@assumption.edu", "Head Coach")},
        )
        self.assertFalse(StaffMember.objects.filter(user__email="sray@assumption.edu").exists())

    def test_staff_coach_sees_team_and_can_open_assign_page(self):
        call_command(
            "import_roster",
            self.write_csv_with_titles(
                "Hal,Head,hhead@assumption.edu,coach,Football,Head Coach\n"
                "Ann,Assist,aassist@assumption.edu,coach,Football,Assistant Coach\n"
            ),
            "--password", "pw-12345",
            stdout=open(os.devnull, "w"),
        )
        team = Team.objects.get()
        self.client.login(username="aassist", password="pw-12345")
        self.assertContains(self.client.get(reverse("planner:coach_dashboard")), "Assumption Football")
        page = self.client.get(reverse("planner:coach_staff"))
        self.assertContains(page, "Assistant Coach")
        self.assertContains(page, "Head Coach")
        self.assertEqual(self.client.get(reverse("planner:assignment_create", args=[team.pk])).status_code, 200)

    def test_coach_without_title_defaults(self):
        self.run_import(
            "Hal,Head,hhead@assumption.edu,coach,Football\n"
            "Ann,Assist,aassist@assumption.edu,coach,Football\n"
        )
        titles = dict(StaffMember.objects.values_list("user__email", "title"))
        self.assertEqual(titles, {"hhead@assumption.edu": "Head Coach", "aassist@assumption.edu": "Assistant Coach"})

    def write_csv_with_titles(self, body):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        handle.write("first_name,last_name,email,role,sport,title\n" + body)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def test_sidebar_titles(self):
        call_command(
            "import_roster",
            self.write_csv_with_titles(
                "Hal,Head,hhead@assumption.edu,coach,Football,Head Coach\n"
                "Dee,Coord,dcoord@assumption.edu,coach,Football,Defensive Coordinator\n"
                "Sam,Ray,sray@assumption.edu,athlete,Women's Soccer,\n"
            ),
            stdout=open(os.devnull, "w"),
        )
        title = lambda email: User.objects.get(email=email).profile.display_title
        self.assertEqual(title("hhead@assumption.edu"), "Head Coach")
        self.assertEqual(title("dcoord@assumption.edu"), "Defensive Coordinator")
        self.assertEqual(title("sray@assumption.edu"), "Women's Soccer Player")
        self.assertEqual(User.objects.get(email="sray@assumption.edu").profile.display_team, "Assumption Women's Soccer")
