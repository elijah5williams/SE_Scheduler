import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.forms.utils import ErrorDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from planner.forms import SignupForm

from . import throttle

logger = logging.getLogger(__name__)

TOO_MANY_LOGINS = "Too many failed sign-in attempts. Please wait 15 minutes and try again, or reset your password."


class ThrottledLoginView(auth_views.LoginView):
    """The normal login page, but it stops accepting guesses after repeated wrong passwords."""

    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip()
        ip = throttle.client_ip(request)
        if throttle.login_by_ip.blocked(ip) or (username and throttle.login_by_username.blocked(username)):
            form = self.get_form()
            # Show the message without validating the form, so no password is checked while locked.
            form._errors = ErrorDict()
            form.cleaned_data = {}
            form.add_error(None, TOO_MANY_LOGINS)
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        username = self.request.POST.get("username", "").strip()
        throttle.login_by_ip.fail(throttle.client_ip(self.request))
        if username:
            throttle.login_by_username.fail(username)
        return super().form_invalid(form)

    def form_valid(self, form):
        throttle.login_by_username.reset(form.get_user().get_username())
        return super().form_valid(form)


@login_not_required  # visitors must be able to reach this page while logged out
def signup(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_active = False  # can't log in until the school email is verified
        user.email = form.cleaned_data["school_email"]
        user.save()  # the signal creates the profile here

        profile = user.profile
        profile.role = form.cleaned_data["role"]
        profile.school_email = form.cleaned_data["school_email"]
        profile.save()

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        link = request.build_absolute_uri(reverse("verify_email", args=[uid, token]))
        try:
            send_mail(
                "Verify your Athlete Academic Assistant account",
                (
                    f"Hi {user.username},\n\n"
                    "Confirm your school email to finish creating your account:\n"
                    f"{link}\n\n"
                    "If you didn't sign up, you can ignore this email."
                ),
                None,
                [user.email],
            )
        except Exception:
            # Don't leave an account nobody can activate: undo it so they can try again.
            logger.exception("Could not send verification email to %s", user.email)
            user.delete()
            form.add_error(None, "We couldn't send the verification email right now. Please try again in a few minutes.")
            return render(request, "registration/signup.html", {"form": form})
        request.session["verification_email"] = user.email
        return redirect("verification_sent")

    return render(request, "registration/signup.html", {"form": form})


@login_not_required  # people click this from their email while logged out
def verify_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user and user.is_active and user.profile.email_verified:
        messages.info(request, "Your email is already verified. You can log in.")
        return redirect("login")

    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()

        profile = user.profile
        profile.email_verified = True
        if profile.role == profile.STUDENT:
            profile.verification_status = profile.VERIFIED
            profile.verified_role = profile.STUDENT
        else:
            # teachers wait for an admin to approve them
            profile.verification_status = profile.PENDING
        profile.save()

        messages.success(request, "Your school email is verified. You can log in now.")
        return redirect("login")

    return render(request, "registration/verification_failed.html")