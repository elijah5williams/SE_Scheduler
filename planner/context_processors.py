def app_shell(request):
    """Data for the phone app's "+" menu. Only looked up when a page actually uses it."""

    def coach_teams():
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.profile.is_verified_coach):
            return []
        from .models import Team

        return list(Team.coached_by(user).order_by("name"))

    return {"app_coach_teams": coach_teams}
