from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    StudySession,
    Team,
)
from .services import events_on, generate_study_plan, planner_insights


@login_required
def dashboard(request):
    if request.user.profile.role == Profile.COACH:
        return redirect("planner:coach_dashboard")
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
    }
    return render(request, "planner/dashboard.html", context)


@login_required
def schedule(request):
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
        {"days": days, "today": today, "all_events": Event.objects.filter(user=request.user)},
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


@login_required
def coach_dashboard(request):
    profile = request.user.profile
    if profile.role != Profile.COACH:
        return redirect("planner:dashboard")
    if not profile.is_verified_coach:
        return render(request, "planner/coach_pending.html")
    teams = Team.objects.filter(coach=request.user).prefetch_related("athletes", "assignments")
    return render(request, "planner/coach_dashboard.html", {"teams": teams, "today": timezone.localdate()})


@coach_required
def team_create(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        team = form.save(commit=False)
        team.coach = request.user
        team.save()
        messages.success(request, f"{team.name} created. Share the code {team.join_code} with your athletes.")
        return redirect("planner:coach_dashboard")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "team", "title": "Create a team"})


@coach_required
def assignment_create(request, team_pk):
    team = get_object_or_404(Team, pk=team_pk, coach=request.user)
    form = AssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.team = team
        assignment.save()
        assignment.push_to_team()
        messages.success(request, f"{assignment.title} was sent to {team.athletes.count()} athlete(s).")
        return redirect("planner:coach_dashboard")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "event", "title": f"Assign to {team.name}"},
    )


@coach_required
def assignment_update(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, team__coach=request.user)
    form = AssignmentForm(request.POST or None, instance=assignment)
    if request.method == "POST" and form.is_valid():
        form.save()
        assignment.sync_events()
        messages.success(request, "Updated for all athletes on the team.")
        return redirect("planner:coach_dashboard")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "event", "title": "Edit assignment", "editing": True},
    )


@coach_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, team__coach=request.user)
    if request.method == "POST":
        title = assignment.title
        assignment.delete()  # removes the copies from athletes' schedules too
        messages.success(request, f"{title} was removed from every athlete's schedule.")
        return redirect("planner:coach_dashboard")
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