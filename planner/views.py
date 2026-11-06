from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from .forms import (
    AcademicTaskForm,
    AssignmentForm,
    EventForm,
    FlexibleRoutineForm,
    JoinTeamForm,
    TeamForm,
)
from .models import (
    AcademicTask,
    Assignment,
    Event,
    FlexibleRoutine,
    Profile,
    RoutineSession,
    StaffMember,
    StudySession,
    Team,
)
from .schedule_sync import ScheduleError, game_hub, sync_if_stale, sync_team
from .services import events_on, generate_study_plan, planner_insights


@login_not_required  # calendar apps can't log in; the private token in the URL is the key
def calendar_feed(request, token):
    from django.http import Http404, HttpResponse

    from .calendar_feed import build_calendar

    profile = Profile.objects.filter(calendar_token=token).select_related("user").first() if token else None
    if profile is None or not profile.user.is_active:
        raise Http404("Unknown calendar link")
    response = HttpResponse(build_calendar(profile.user), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="greyhounds.ics"'
    response["Cache-Control"] = "private, max-age=900"
    return response


@login_required
def calendar_reset(request):
    if request.method == "POST":
        request.user.profile.get_calendar_token(reset=True)
        messages.success(request, "Your calendar link was changed. Add the new link to your calendar app; the old one no longer works.")
    return redirect(request.POST.get("next") or "planner:schedule")


def calendar_links(request):
    token = request.user.profile.get_calendar_token()
    https_url = request.build_absolute_uri(reverse("planner:calendar_feed", args=[token]))
    webcal = "webcal://" + https_url.split("://", 1)[1]
    return {
        "calendar_url": https_url,
        "calendar_webcal": webcal,
        "calendar_google": "https://calendar.google.com/calendar/r?cid=" + webcal,
    }


@login_required
def home(request):
    """Full-page landing: live athletics photos, the user's next game and the latest Greyhound scores."""
    from .photos import login_photos

    profile = request.user.profile
    is_coach = profile.role == Profile.COACH
    teams = list(Team.coached_by(request.user) if is_coach else request.user.teams.all())
    linked = [team for team in teams if team.schedule_url]
    sync_if_stale(linked)
    hubs = [game_hub(team) for team in linked]
    upcoming = sorted((h for h in hubs if h["next_game"]), key=lambda h: h["next_game"].kickoff)
    next_hub = upcoming[0] if upcoming else (hubs[0] if hubs else None)

    since = timezone.localdate() - timedelta(days=21)
    ticker = list(
        Assignment.objects.exclude(external_id="").exclude(result="")
        .filter(date__gte=since).select_related("team").order_by("-date", "-start_time")[:24]
    )
    ticker = [g for g in ticker if not g.is_cancelled]

    from .models import AthleteBio

    bios = list(
        AthleteBio.objects.exclude(photo_url="").filter(team__in=teams).select_related("user", "team").order_by("?")[:12]
    )
    if len(bios) < 6:
        bios += list(AthleteBio.objects.exclude(photo_url="").exclude(pk__in=[b.pk for b in bios])
                     .select_related("user", "team").order_by("?")[: 12 - len(bios)])
    return render(
        request,
        "planner/home.html",
        {
            "photos": login_photos(),
            "is_coach": is_coach,
            "next_hub": next_hub,
            "next_game": next_hub["next_game"] if next_hub else None,
            "ticker": ticker,
            "bios": bios,
            "weather": next_hub.get("weather") if next_hub else None,
        },
    )


@login_required
def dashboard(request):
    if request.user.profile.role == Profile.COACH:
        return redirect("planner:coach_dashboard")
    teams = list(request.user.teams.exclude(schedule_url=""))
    sync_if_stale(teams)
    today = timezone.localdate()
    next_week = today + timedelta(days=7)
    today_events = sorted(events_on(today, request.user), key=lambda event: event.start_time)
    today_sessions = StudySession.objects.filter(date=today, task__user=request.user).select_related("task")
    today_routines = RoutineSession.objects.filter(date=today, routine__user=request.user).select_related("routine")
    upcoming_tasks = AcademicTask.objects.filter(user=request.user, completed=False).order_by("due_date")[:6]
    completed_count = AcademicTask.objects.filter(user=request.user, completed=True).count()
    total_count = AcademicTask.objects.filter(user=request.user).count()
    progress = round((completed_count / total_count) * 100) if total_count else 0
    week_sessions = StudySession.objects.filter(
        date__range=(today, next_week), completed=False, task__user=request.user
    ).count()
    week_sessions += RoutineSession.objects.filter(
        date__range=(today, next_week), completed=False, routine__user=request.user
    ).count()
    context = {
        "today": today,
        "today_events": today_events,
        "today_sessions": today_sessions,
        "today_routines": today_routines,
        "upcoming_tasks": upcoming_tasks,
        "active_tasks": AcademicTask.objects.filter(user=request.user, completed=False).count(),
        "week_sessions": week_sessions,
        "completed_count": completed_count,
        "progress": progress,
        "game_hubs": [game_hub(team) for team in teams],
    }
    return render(request, "planner/dashboard.html", context)


@login_required
def schedule(request):
    sync_if_stale(request.user.teams.exclude(schedule_url=""))
    teams = list(request.user.teams.prefetch_related("assignments").order_by("name"))
    for team in teams:
        team.hub = game_hub(team) if team.schedule_url else None
        team.team_events = [a for a in team.assignments.all() if not a.external_id]
    today = timezone.localdate()
    days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        items = []
        for event in events_on(day, request.user):
            items.append(
                {
                    "kind": "event",
                    "time": event.start_time,
                    "end_time": event.end_time,
                    "title": event.title,
                    "label": event.get_event_type_display(),
                    "type": event.event_type,
                    "location": event.location,
                    "object": event,
                    "game": event.assignment if event.assignment_id and event.assignment.external_id else None,
                    "team_event": bool(event.assignment_id),
                }
            )
        for session in StudySession.objects.filter(date=day, task__user=request.user).select_related("task"):
            items.append(
                {
                    "kind": "study",
                    "time": session.start_time,
                    "end_time": session.end_time,
                    "title": session.task.title,
                    "label": f"Study · {session.task.course}",
                    "type": "study",
                    "location": "",
                    "object": session,
                }
            )
        for session in RoutineSession.objects.filter(date=day, routine__user=request.user).select_related("routine"):
            items.append(
                {
                    "kind": "routine",
                    "time": session.start_time,
                    "end_time": session.end_time,
                    "title": session.routine.title,
                    "label": "Flexible routine",
                    "type": "routine",
                    "location": f"{session.duration_minutes} minutes",
                    "object": session,
                }
            )
        items.sort(key=lambda item: item["time"])
        days.append({"date": day, "items": items})
    return render(
        request,
        "planner/schedule.html",
        {
            "days": days,
            "today": today,
            "teams": teams,
            **calendar_links(request),
            # Team games and coach-assigned events are managed by the team, not here.
            "all_events": Event.objects.filter(user=request.user, assignment__isnull=True),
        },
    )


@login_required
def event_create(request):
    form = EventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.user = request.user
        event.save()
        messages.success(request, f"{event.title} was added to your schedule.")
        return redirect("planner:schedule")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "event", "title": "Add a commitment"})


@login_required
def event_update(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user)
    if event.assignment_id:
        messages.info(request, "Your coach assigned this, so only your coach can change it.")
        return redirect("planner:schedule")
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Schedule updated.")
        return redirect("planner:schedule")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "event", "title": "Edit commitment", "editing": True})


@login_required
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user)
    if event.assignment_id:
        messages.info(request, "Your coach assigned this, so only your coach can change it.")
        return redirect("planner:schedule")
    course_codes = list(
        AcademicTask.objects.filter(user=request.user).order_by("course").values_list("course", flat=True).distinct()
    )
    if request.method == "POST":
        title = event.title
        related_courses = request.POST.getlist("related_courses")
        removed_work = AcademicTask.objects.filter(user=request.user, course__in=related_courses).count()
        if related_courses:
            AcademicTask.objects.filter(user=request.user, course__in=related_courses).delete()
        event.delete()
        message = f"{title} was removed from your schedule."
        if removed_work:
            message += f" {removed_work} related academic item{'s were' if removed_work != 1 else ' was'} also removed."
        messages.success(request, message)
        return redirect("planner:schedule")
    return render(
        request,
        "planner/confirm_delete.html",
        {
            "object": event,
            "cancel_url": reverse("planner:schedule"),
            "related_courses": course_codes if event.event_type == Event.CLASS else [],
        },
    )


@login_required
def task_list(request):
    tasks = AcademicTask.objects.filter(user=request.user)
    courses = tasks.order_by("course").values_list("course", flat=True).distinct()
    return render(request, "planner/tasks.html", {"tasks": tasks, "courses": courses})


@login_required
def task_create(request):
    form = AcademicTaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.user = request.user
        task.save()
        messages.success(request, f"{task.title} was added.")
        return redirect("planner:tasks")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "task", "title": "Add academic work"})


@login_required
def task_update(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk, user=request.user)
    form = AcademicTaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Academic work updated.")
        return redirect("planner:tasks")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "task", "title": "Edit academic work", "editing": True})


@login_required
def task_toggle(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk, user=request.user)
    if request.method == "POST":
        task.completed = not task.completed
        task.save(update_fields=["completed"])
        status = "completed" if task.completed else "active"
        messages.success(request, f"{task.title} marked {status}.")
    return redirect(request.POST.get("next", "planner:tasks"))


@login_required
def task_delete(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk, user=request.user)
    if request.method == "POST":
        title = task.title
        task.delete()
        messages.success(request, f"{title} was removed.")
        return redirect("planner:tasks")
    return render(request, "planner/confirm_delete.html", {"object": task, "cancel_url": reverse("planner:tasks")})


@login_required
def course_delete(request, course):
    tasks = AcademicTask.objects.filter(user=request.user, course__iexact=course)
    if not tasks.exists():
        messages.info(request, f"No academic work remains for {course}.")
        return redirect("planner:tasks")
    if request.method == "POST":
        item_count = tasks.count()
        tasks.delete()
        Event.objects.filter(user=request.user, title__icontains=course).delete()
        messages.success(
            request,
            f"{course} was removed with {item_count} academic item{'s' if item_count != 1 else ''} and its study sessions.",
        )
        return redirect("planner:schedule")
    return render(
        request,
        "planner/confirm_course_delete.html",
        {"course": course, "tasks": tasks, "cancel_url": reverse("planner:tasks")},
    )


@login_required
def routine_create(request):
    form = FlexibleRoutineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        routine = form.save(commit=False)
        routine.user = request.user
        routine.save()
        messages.success(request, f"{routine.title} was added. Generate a new plan to schedule it.")
        return redirect("planner:study_planner")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "routine", "title": "Add a flexible routine"},
    )


@login_required
def routine_update(request, pk):
    routine = get_object_or_404(FlexibleRoutine, pk=pk, user=request.user)
    form = FlexibleRoutineForm(request.POST or None, instance=routine)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Flexible routine updated. Generate a new plan to apply the change.")
        return redirect("planner:study_planner")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "routine", "title": "Edit flexible routine", "editing": True},
    )


@login_required
def routine_delete(request, pk):
    routine = get_object_or_404(FlexibleRoutine, pk=pk, user=request.user)
    if request.method == "POST":
        title = routine.title
        routine.delete()
        messages.success(request, f"{title} and its generated sessions were removed.")
        return redirect("planner:study_planner")
    return render(
        request,
        "planner/confirm_delete.html",
        {"object": routine, "cancel_url": reverse("planner:study_planner")},
    )


@login_required
def study_planner(request):
    if request.method == "POST":
        result = generate_study_plan(request.user)
        messages.success(request, result["message"])
        if result["unscheduled"]:
            messages.warning(request, "Some items could not fit into the available time. Adjust the schedule or duration.")
        return redirect("planner:study_planner")

    tasks = list(AcademicTask.objects.filter(user=request.user))
    sessions = list(StudySession.objects.filter(completed=False, task__user=request.user).select_related("task"))
    routine_sessions = list(
        RoutineSession.objects.filter(completed=False, routine__user=request.user).select_related("routine")
    )
    today = timezone.localdate()
    calendar_days = []

    for offset in range(14):
        day = today + timedelta(days=offset)
        items = []

        for event in events_on(day, request.user):
            athletic_types = {Event.PRACTICE, Event.GAME, Event.WORKOUT, Event.MEETING}
            items.append(
                {
                    "kind": "athletic" if event.event_type in athletic_types else "class",
                    "time": event.start_time,
                    "end_time": event.end_time,
                    "label": event.get_event_type_display(),
                    "title": event.title,
                    "detail": event.location,
                    "object": event,
                }
            )

        for session in [session for session in sessions if session.date == day]:
            items.append(
                {
                    "kind": "study",
                    "time": session.start_time,
                    "end_time": session.end_time,
                    "label": f"Study · {session.task.course}",
                    "title": session.task.title,
                    "detail": f"{session.duration_minutes} focused minutes",
                    "object": session,
                }
            )

        for session in [session for session in routine_sessions if session.date == day]:
            items.append(
                {
                    "kind": "routine",
                    "time": session.start_time,
                    "end_time": session.end_time,
                    "label": "Flexible routine",
                    "title": session.routine.title,
                    "detail": f"{session.duration_minutes} minutes · placed in open time",
                    "object": session,
                }
            )

        for task in tasks:
            due_at = timezone.localtime(task.due_date)
            if not task.completed and due_at.date() == day:
                items.append(
                    {
                        "kind": "deadline",
                        "time": due_at.time(),
                        "end_time": None,
                        "label": f"Due · {task.course}",
                        "title": task.title,
                        "detail": task.get_task_type_display(),
                        "object": task,
                    }
                )

        items.sort(key=lambda item: item["time"])
        calendar_days.append({"date": day, "is_today": day == today, "items": items})
    return render(
        request,
        "planner/study_planner.html",
        {
            "sessions": sessions,
            "routine_sessions": routine_sessions,
            "planned_blocks": len(sessions) + len(routine_sessions),
            "calendar_days": calendar_days,
            "routines": FlexibleRoutine.objects.filter(user=request.user),
            "active_tasks": [task for task in tasks if not task.completed],
            "insights": planner_insights(tasks, sessions),
        },
    )


@login_required
def session_toggle(request, pk):
    session = get_object_or_404(StudySession, pk=pk, task__user=request.user)
    if request.method == "POST":
        session.completed = not session.completed
        session.save(update_fields=["completed"])
        messages.success(request, "Study session updated.")
    return redirect(request.POST.get("next", "planner:study_planner"))


@login_required
def routine_session_toggle(request, pk):
    session = get_object_or_404(RoutineSession, pk=pk, routine__user=request.user)
    if request.method == "POST":
        session.completed = not session.completed
        session.save(update_fields=["completed"])
        messages.success(request, "Routine session updated.")
    return redirect(request.POST.get("next", "planner:study_planner"))


# ---------------------------------------------------------------------------
# Coach tools
# ---------------------------------------------------------------------------


def coach_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_verified_coach:
            return redirect("planner:coach_dashboard")
        return view(request, *args, **kwargs)

    return login_required(wrapper)


def _coach_teams(user):
    """The coach's teams, with their game-day data and coach-made events attached."""
    sync_if_stale(Team.coached_by(user).exclude(schedule_url=""))
    teams = list(Team.coached_by(user).prefetch_related("athletes", "assignments", "staff__user"))
    for team in teams:
        team.hub = game_hub(team) if team.schedule_url else None
        team.team_events = [a for a in team.assignments.all() if not a.external_id]
    return teams


def _coach_page(view):
    """Coach-only page: athletes go to their dashboard, unverified coaches see the pending notice."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = request.user.profile
        if profile.role != Profile.COACH:
            return redirect("planner:dashboard")
        if not profile.is_verified_coach:
            return render(request, "planner/coach_pending.html")
        return view(request, *args, **kwargs)

    return login_required(wrapper)


@_coach_page
def coach_dashboard(request):
    teams = _coach_teams(request.user)
    return render(request, "planner/coach_dashboard.html", {"teams": teams, "today": timezone.localdate()})


COACH_SECTIONS = {
    "schedule": ("Team schedule", "Season games, scores and the practices you've assigned.", "planner/_coach_schedule.html"),
    "roster": ("Roster", "Every athlete on your team. Search by name or email.", "planner/_coach_roster.html"),
    "staff": ("Coaching staff", "Your team's coaches and their roles.", "planner/_coach_staff.html"),
}


def _coach_section(request, section):
    title, intro, template = COACH_SECTIONS[section]
    return render(
        request,
        "planner/coach_section.html",
        {
            "teams": _coach_teams(request.user),
            "page_title": title,
            "intro": intro,
            "eyebrow": "Coach tools",
            "section_template": template,
            "section": section,
            **(calendar_links(request) if section == "schedule" else {}),
        },
    )


@_coach_page
def coach_schedule(request):
    return _coach_section(request, "schedule")


@_coach_page
def coach_roster(request):
    return _coach_section(request, "roster")


@_coach_page
def coach_staff(request):
    return _coach_section(request, "staff")


@coach_required
def team_sync(request, team_pk):
    team = get_object_or_404(Team.coached_by(request.user), pk=team_pk)
    if request.method == "POST":
        try:
            counts = sync_team(team)
        except ScheduleError as exc:
            messages.error(request, f"Couldn't update the schedule: {exc}")
        else:
            messages.success(
                request,
                f"Schedule updated: {counts['added']} new, {counts['updated']} changed, {counts['removed']} removed.",
            )
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("planner:coach_schedule")


@coach_required
def team_create(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        team = form.save(commit=False)
        team.coach = request.user
        team.save()
        StaffMember.objects.create(team=team, user=request.user, title="Head Coach")
        messages.success(request, f"{team.name} created. Share the code {team.join_code} with your athletes.")
        return redirect("planner:coach_dashboard")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "team", "title": "Create a team"})


@coach_required
def assignment_create(request, team_pk):
    team = get_object_or_404(Team.coached_by(request.user), pk=team_pk)
    form = AssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.team = team
        assignment.save()
        assignment.push_to_team()
        messages.success(request, f"{assignment.title} was sent to {team.athletes.count()} athlete(s).")
        return redirect("planner:coach_schedule")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "event", "title": f"Assign to {team.name}"},
    )


@coach_required
def assignment_update(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, team__in=Team.coached_by(request.user))
    form = AssignmentForm(request.POST or None, instance=assignment)
    if request.method == "POST" and form.is_valid():
        form.save()
        assignment.sync_events()
        messages.success(request, "Updated for all athletes on the team.")
        return redirect("planner:coach_schedule")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "event", "title": "Edit assignment", "editing": True},
    )


@coach_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, team__in=Team.coached_by(request.user))
    if request.method == "POST":
        title = assignment.title
        assignment.delete()  # removes the copies from athletes' schedules too
        messages.success(request, f"{title} was removed from every athlete's schedule.")
        return redirect("planner:coach_schedule")
    return render(
        request,
        "planner/confirm_delete.html",
        {"object": assignment, "cancel_url": reverse("planner:coach_dashboard")},
    )


@login_required
def team_join(request):
    if request.user.profile.role == Profile.COACH:
        return redirect("planner:coach_dashboard")
    form = JoinTeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        team = form.team
        team.athletes.add(request.user)
        for assignment in team.assignments.all():
            assignment.push_to(request.user)
        messages.success(request, f"You joined {team.name}. Your coach's plans are now on your schedule.")
        return redirect("planner:schedule")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "team", "title": "Join your team"})