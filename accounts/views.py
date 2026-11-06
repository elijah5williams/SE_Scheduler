from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from planner.forms import SignupForm


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
        send_mail(
            "Verify your school email",
            f"Click to verify your account:\n{link}",
            None,
            [user.email],
        )
        return redirect("verification_sent")

    return render(request, "registration/signup.html", {"form": form})


@login_not_required  # people click this from their email while logged out
def verify_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

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