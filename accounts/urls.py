from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_not_required

from . import views

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("verify/<uidb64>/<token>/", views.verify_email, name="verify_email"),
    path(
        "verification-sent/",
        TemplateView.as_view(template_name="registration/verification_sent.html"),
        name="verification_sent",
    ),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path(
        "verification-sent/",
        login_not_required(
            TemplateView.as_view(template_name="registration/verification_sent.html")
        ),
        name="verification_sent",
    ),
]