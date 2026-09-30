from django.conf import settings
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

    def test_signup_creates_account_and_logs_in(self):
        response = self.client.post(
            reverse("signup"),
            {"username": "newbie", "password1": "Tr1cky-horse-9", "password2": "Tr1cky-horse-9"},
        )
        self.assertRedirects(response, self.home, fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertEqual(self.client.get(self.home).status_code, 200)

    def test_signup_rejects_weak_password(self):
        response = self.client.post(
            reverse("signup"), {"username": "weak", "password1": "12345678", "password2": "12345678"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_logout_needs_post_and_ends_session(self):
        self.client.login(username="alex", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(self.home).status_code, 302)

    def test_admin_login_still_reachable(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
