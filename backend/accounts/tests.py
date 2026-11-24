from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccountTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        res = self.client.post(
            reverse("accounts:signup"),
            {"username": "student01", "password1": "Vision!2026a", "password2": "Vision!2026a"},
        )
        self.assertRedirects(res, reverse("analyses:index"))
        user = User.objects.get(username="student01")
        self.assertNotEqual(user.password, "Vision!2026a")  # 해시 저장
        self.assertFalse(user.is_staff)

    def test_login_and_logout(self):
        User.objects.create_user("student02", password="Vision!2026a")
        res = self.client.post(reverse("accounts:login"), {"username": "student02", "password": "Vision!2026a"})
        self.assertRedirects(res, reverse("analyses:index"))
        res = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(res, reverse("accounts:login"))

    def test_anonymous_redirected_from_analysis_page(self):
        res = self.client.get(reverse("analyses:index"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("accounts:login"), res["Location"])

    def test_anonymous_api_is_forbidden(self):
        res = self.client.get("/api/analyses/")
        self.assertIn(res.status_code, (401, 403))
