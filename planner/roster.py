"""Shared account creation for roster imports (CSV files and the athletics website)."""
import re
import unicodedata

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Profile, StaffMember, Team

SCHOOL_NAME = "Assumption"
SCHOOL_DOMAIN = "assumption.edu"


def team_name_for(sport):
    sport = " ".join(sport.split())
    if sport.lower().startswith(SCHOOL_NAME.lower() + " "):
        return sport
    return f"{SCHOOL_NAME} {sport}"


def _email_part(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\.?$", "", name.strip(), flags=re.I)
    return re.sub(r"[^a-z\-]", "", name.lower())


def school_email(first, last):
    """Assumption's format: first.last@assumption.edu (apostrophes, spaces and suffixes dropped)."""
    return f"{_email_part(first)}.{_email_part(last)}@{SCHOOL_DOMAIN}"


def password_hash(password):
    """Hash once and reuse it: hashing hundreds of passwords one by one takes minutes."""
    return make_password(password) if password else None


def unique_username(email):
    base = email.split("@", 1)[0][:140]
    username, n = base, 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    return username


def import_person(row, stats, *, hashed_password=None, reset_password=False, new_users=None):
    """
    Create or update one roster person and put them on their team.

    row: first_name, last_name, email, role (Profile.STUDENT or Profile.COACH), sport, title, order
    hashed_password: from password_hash(); new accounts get it, existing ones only if reset_password.
    """
    user = User.objects.filter(email__iexact=row["email"]).first()
    if user is None:
        user = User(
            username=unique_username(row["email"]),
            email=row["email"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_active=True,  # the school roster stands in for the email check
        )
        if hashed_password:
            user.password = hashed_password
        else:
            user.set_unusable_password()
        user.save()  # signal creates the profile
        stats["users_created"] += 1
        if new_users is not None:
            new_users.append(user)
    else:
        stats["users_existing"] += 1
        if hashed_password and reset_password and user.password != hashed_password:
            user.password = hashed_password
            user.save(update_fields=["password"])

    profile = user.profile
    if profile.role != Profile.COACH:  # a coach listed on two teams stays a coach
        profile.role = row["role"]
    profile.school_email = row["email"]
    profile.email_verified = True
    profile.verification_status = Profile.VERIFIED
    profile.verified_role = profile.role
    profile.verified_at = profile.verified_at or timezone.now()
    profile.save()

    team, created = Team.objects.get_or_create(name=team_name_for(row["sport"]))
    if created:
        stats["teams_created"] += 1

    if row["role"] == Profile.COACH:
        title = row.get("title", "")
        # "Head Coach" or "Head Coach / Offensive Line", but not "Associate Head Coach".
        is_head = title.strip().lower().startswith("head coach")
        if team.coach is None or (is_head and team.coach != user):
            team.coach = user
            team.save(update_fields=["coach"])
        staff, _ = StaffMember.objects.get_or_create(
            team=team,
            user=user,
            defaults={
                "title": title or ("Head Coach" if team.coach == user else "Assistant Coach"),
                "order": row.get("order", 0),
            },
        )
        if title and staff.title != title:
            staff.title = title
            staff.save(update_fields=["title"])
    else:
        team.athletes.add(user)
        for assignment in team.assignments.all():
            assignment.push_to(user)
    return user, team
