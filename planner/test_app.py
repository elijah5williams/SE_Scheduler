"""The installed phone app: More page, icon badge, offline schedule and notifications."""

import json
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AcademicTask, Assignment, Event, Profile, PushSubscription, StaffMember, Team
from .push import is_allowed_endpoint
from .schedule_sync import sync_team
from .test_schedule_sync import URL, page

PUSH_KEYS = {"VAPID_PUBLIC_KEY": "BPublicKeyForTests", "VAPID_PRIVATE_KEY": "private", "PUSH_SEND_INLINE": True}
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def make_user(username, role=Profile.STUDENT, **extra):
    user = User.objects.create_user(username, password="pw-test-123", **extra)
    profile = user.profile
    profile.role = profile.verified_role = role
    profile.verification_status = Profile.VERIFIED
    profile.save()
    return user


def subscribe(user, endpoint=FCM):
    return PushSubscription.objects.create(user=user, endpoint=endpoint, p256dh="key", auth="auth")


class AppPageTests(TestCase):
    def setUp(self):
        self.user = make_user("student", first_name="Jordan")
        self.client.login(username="student", password="pw-test-123")

    def test_more_page(self):
        response = self.client.get(reverse("planner:app_more"))
        self.assertContains(response, "Academic work")
        self.assertContains(response, 'data-theme-value="dark"')
        self.assertNotContains(response, 'data-key=""')  # keys are created automatically

    @override_settings(**PUSH_KEYS)
    def test_more_page_offers_notifications_when_configured(self):
        self.assertContains(self.client.get(reverse("planner:app_more")), 'data-key="BPublicKeyForTests"')

    def test_tab_bar_and_add_menu_on_every_page(self):
        response = self.client.get(reverse("planner:dashboard"))
        self.assertContains(response, 'class="app-tabbar"')
        self.assertContains(response, reverse("planner:task_create"))
        self.assertContains(response, "dark.css")

    def test_badge_counts_what_is_left_today(self):
        later_today = timezone.localtime().replace(hour=23, minute=59, second=0, microsecond=0)
        AcademicTask.objects.create(user=self.user, title="Lab", course="BIO 101", due_date=later_today, estimated_minutes=30)
        AcademicTask.objects.create(user=self.user, title="Essay", course="ENG 101",
                                    due_date=later_today + timedelta(days=3), estimated_minutes=30)
        data = self.client.get(reverse("planner:app_status")).json()
        self.assertEqual(data["badge"], 1)

    def test_offline_data_has_two_weeks_of_own_schedule(self):
        today = timezone.localdate()
        Event.objects.create(user=self.user, title="Practice", event_type=Event.PRACTICE, date=today,
                             start_time=time(16), end_time=time(18), location="Stadium")
        other = make_user("other")
        Event.objects.create(user=other, title="Someone else's class", event_type=Event.CLASS, date=today,
                             start_time=time(9), end_time=time(10))
        response = self.client.get(reverse("planner:app_offline_data"))
        self.assertEqual(response["Cache-Control"], "private, no-cache")
        data = response.json()
        self.assertEqual(len(data["days"]), 14)
        self.assertEqual(data["user"], "Jordan")
        titles = [item["title"] for item in data["days"][0]["items"]]
        self.assertEqual(titles, ["Practice"])

    def test_app_data_needs_login(self):
        self.client.logout()
        for name in ("planner:app_offline_data", "planner:app_status", "planner:app_more"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)


class PushSubscriptionTests(TestCase):
    def setUp(self):
        self.user = make_user("student")
        self.client.login(username="student", password="pw-test-123")
        self.url = reverse("planner:push_subscribe")

    def post(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def test_keys_are_created_once_and_reused(self):
        from py_vapid import Vapid

        from . import push
        from .models import PushKeys

        public, private = push.keys()
        self.assertEqual(push.keys(), (public, private))
        self.assertEqual(PushKeys.objects.count(), 1)
        self.assertEqual(len(public), 87)  # uncompressed P-256 point, base64url
        self.assertIn("Authorization", Vapid.from_string(private).sign({"aud": "https://fcm.googleapis.com", "sub": "mailto:a@b.c"}))
        self.assertContains(self.client.get(reverse("planner:app_more")), f'data-key="{public}"')

    def test_subscribe_works_without_any_setup(self):
        response = self.post(self.url, {"endpoint": FCM, "keys": {"p256dh": "k", "auth": "a"}})
        self.assertEqual(response.status_code, 200)

    @override_settings(**PUSH_KEYS)
    def test_subscribe_and_unsubscribe(self):
        self.assertEqual(self.post(self.url, {"endpoint": FCM, "keys": {"p256dh": "k", "auth": "a"}}).status_code, 200)
        self.assertEqual(PushSubscription.objects.get().user, self.user)
        self.post(reverse("planner:push_unsubscribe"), {"endpoint": FCM})
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(**PUSH_KEYS)
    def test_only_real_push_services_are_accepted(self):
        for endpoint in ("http://fcm.googleapis.com/x", "https://localhost/x", "https://169.254.169.254/x",
                         "https://evil.example.com/fcm.googleapis.com", "https://fcm.googleapis.com.evil.com/x"):
            response = self.post(self.url, {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}})
            self.assertEqual(response.status_code, 400, endpoint)
        self.assertFalse(PushSubscription.objects.exists())
        self.assertTrue(is_allowed_endpoint("https://web.push.apple.com/QGx"))
        self.assertTrue(is_allowed_endpoint("https://wns2-par02p.notify.windows.com/w/?token=x"))

    @override_settings(**PUSH_KEYS)
    def test_cannot_remove_someone_elses_device(self):
        subscribe(make_user("other"))
        self.post(reverse("planner:push_unsubscribe"), {"endpoint": FCM})
        self.assertTrue(PushSubscription.objects.exists())


@override_settings(**PUSH_KEYS)
class NotificationTests(TestCase):
    def setUp(self):
        self.coach = make_user("coach", role=Profile.COACH, first_name="Hal", last_name="Head")
        self.athlete = make_user("athlete")
        self.team = Team.objects.create(name="Assumption Football", coach=self.coach, schedule_url=URL)
        StaffMember.objects.create(team=self.team, user=self.coach, title="Head Coach")
        self.team.athletes.add(self.athlete)
        subscribe(self.athlete)
        self.client.login(username="coach", password="pw-test-123")
        patcher = mock.patch("pywebpush.webpush")
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self):
        return [json.loads(call.kwargs["data"]) for call in self.webpush.call_args_list]

    def test_athletes_hear_about_new_coach_events(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("planner:assignment_create", args=[self.team.pk]), {
                "event_type": Event.WORKOUT, "title": "Lower body lift", "date": tomorrow,
                "start_time": "07:00", "end_time": "08:00", "location": "Weight room",
            })
        [message] = self.sent()
        self.assertEqual(message["title"], "New from Hal Head: Lower body lift")
        self.assertIn("Weight room", message["body"])
        self.assertEqual(message["url"], "/schedule/")

    def test_game_time_change_and_final_score(self):
        day = timezone.localdate() + timedelta(days=3)
        game = ("201", f"{day}T13:00:00", "Bentley University", True, "Home field", "", "Bentley.png")
        with self.captureOnCommitCallbacks(execute=True):
            sync_team(self.team, page=page([game]))
        self.assertEqual(self.sent(), [])  # adding the season's games doesn't notify

        moved = (*game[:1], f"{day}T18:00:00", *game[2:])
        with self.captureOnCommitCallbacks(execute=True):
            sync_team(self.team, page=page([moved]))
        self.assertTrue(self.sent()[-1]["title"].startswith("Game time changed"))
        self.assertIn("6:00 PM", self.sent()[-1]["body"])

        Assignment.objects.filter(external_id="201").update(date=timezone.localdate())
        final = (moved[0], f"{timezone.localdate()}T18:00:00", *moved[2:5], "W, 28-14", moved[6])
        with self.captureOnCommitCallbacks(execute=True):
            sync_team(self.team, page=page([final]))
        self.assertEqual(self.sent()[-1]["title"], "Final: Football W 28-14")

    def test_dead_subscriptions_are_removed(self):
        from pywebpush import WebPushException

        self.webpush.side_effect = WebPushException("gone", response=mock.Mock(status_code=410))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("planner:push_test"))
        self.assertTrue(PushSubscription.objects.filter(user=self.athlete).exists())  # coach has none
        self.client.login(username="athlete", password="pw-test-123")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("planner:push_test"))
        self.assertFalse(PushSubscription.objects.exists())
