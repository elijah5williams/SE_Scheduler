from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render


@login_not_required  # visitors must be able to reach this page while logged out
def signup(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_active = False
        user.save()
        messages.success(
            request,
            "Your account was created. An admin needs to approve it before you can log in.",
        )
        return redirect("login")

    return render(request, "registration/signup.html", {"form": form})
