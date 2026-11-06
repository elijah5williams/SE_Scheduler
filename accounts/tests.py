import re
from unittest import mock

from django.conf import settings
from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()
PASSWORD = "s3cret-Pass!"


class LoginFlowTests(TestCase):
    def setUp(self):
        User.objects.create_user("alex", password=PASSWORD)
        User.objects.create_superuser("boss", password=PASSWORD)
        self.home = settings.LOGIN_REDIRECT_URL

    def test_anonymous_visitor_is_sent_to_login(self):
        response = self.client.get(self.home)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_login_and_signup_pages_are_public(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("signup")).status_code, 200)

    def test_login_success_redirects_home(self):
        response = self.client.post(reverse("login"), {"username": "alex", "password": PASSWORD})
        self.assertRedirects(response, self.home, fetch_redirect_response=False)
        self.assertEqual(self.client.get(self.home).status_code, 200)

    def test_wrong_password_shows_error(self):
        response = self.client.post(reverse("login"), {"username": "alex", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct username and password")

    def signup(self, password="Tr1cky-horse-9", **extra):
        data = {"username": "newbie", "school_email": "newbie@assumption.edu", "role": "student",
                "password1": password, "password2": password, **extra}
        return self.client.post(reverse("signup"), data)

    def test_signup_emails_a_verification_link_then_activates(self):
        response = self.signup()
        self.assertRedirects(response, reverse("verification_sent"), fetch_redirect_response=False)
        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_active)

        page = self.client.get(reverse("verification_sent"))
        self.assertContains(page, "newbie@assumption.edu")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["newbie@assumption.edu"])
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.assertRedirects(self.client.get(link), reverse("login"), fetch_redirect_response=False)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.is_verified_student)
        self.assertTrue(self.client.login(username="newbie", password="Tr1cky-horse-9"))

    def test_second_click_on_verification_link_says_already_verified(self):
        self.signup()
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.client.get(link)
        response = self.client.get(link, follow=True)
        self.assertContains(response, "already verified")

    def test_bad_verification_link_shows_friendly_page(self):
        response = self.client.get(reverse("verify_email", args=["Mg", "bad-token"]))
        self.assertContains(response, "That link didn't work")

    def test_signup_rejects_weak_password(self):
        response = self.signup(password="12345678")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_signup_undone_when_email_cannot_be_sent(self):
        with mock.patch("accounts.views.send_mail", side_effect=OSError("smtp down")):
            response = self.signup()
        self.assertContains(response, "couldn&#x27;t send the verification email")
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_password_reset_uses_app_pages_and_sends_email(self):
        User.objects.filter(username="alex").update(email="alex@assumption.edu")
        page = self.client.get(reverse("password_reset"))
        self.assertContains(page, "Forgot your password?")
        self.assertNotContains(page, "Django administration")
        response = self.client.post(reverse("password_reset"), {"email": "alex@assumption.edu"})
        self.assertRedirects(response, reverse("password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)

    def test_logout_needs_post_and_ends_session(self):
        self.client.login(username="alex", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(self.home).status_code, 302)

    def test_admin_login_still_reachable(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
