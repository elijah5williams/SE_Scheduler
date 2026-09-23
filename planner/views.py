from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import AcademicTaskForm, EventForm, FlexibleRoutineForm
from .models import AcademicTask, Event, FlexibleRoutine, RoutineSession, StudySession
from .services import events_on, generate_study_plan, planner_insights


def dashboard(request):
    today = timezone.localdate()
    next_week = today + timedelta(days=7)
    today_events = sorted(events_on(today), key=lambda event: event.start_time)
    today_sessions = StudySession.objects.filter(date=today).select_related("task")
    today_routines = RoutineSession.objects.filter(date=today).select_related("routine")
    upcoming_tasks = AcademicTask.objects.filter(completed=False).order_by("due_date")[:6]
    completed_count = AcademicTask.objects.filter(completed=True).count()
    total_count = AcademicTask.objects.count()
    progress = round((completed_count / total_count) * 100) if total_count else 0
    week_sessions = StudySession.objects.filter(date__range=(today, next_week), completed=False).count()
    week_sessions += RoutineSession.objects.filter(date__range=(today, next_week), completed=False).count()
    context = {
        "today": today,
        "today_events": today_events,
        "today_sessions": today_sessions,
        "today_routines": today_routines,
        "upcoming_tasks": upcoming_tasks,
        "active_tasks": AcademicTask.objects.filter(completed=False).count(),
        "week_sessions": week_sessions,
        "completed_count": completed_count,
        "progress": progress,
    }
    return render(request, "planner/dashboard.html", context)


def schedule(request):
    today = timezone.localdate()
    days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        items = []
        for event in events_on(day):
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
        for session in StudySession.objects.filter(date=day).select_related("task"):
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
        for session in RoutineSession.objects.filter(date=day).select_related("routine"):
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
        {"days": days, "today": today, "all_events": Event.objects.all()},
    )


def event_create(request):
    form = EventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.save()
        messages.success(request, f"{event.title} was added to your schedule.")
        return redirect("planner:schedule")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "event", "title": "Add a commitment"})


def event_update(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Schedule updated.")
        return redirect("planner:schedule")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "event", "title": "Edit commitment", "editing": True})


def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    course_codes = list(
        AcademicTask.objects.order_by("course").values_list("course", flat=True).distinct()
    )
    if request.method == "POST":
        title = event.title
        related_courses = request.POST.getlist("related_courses")
        removed_work = AcademicTask.objects.filter(course__in=related_courses).count()
        if related_courses:
            AcademicTask.objects.filter(course__in=related_courses).delete()
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


def task_list(request):
    tasks = AcademicTask.objects.all()
    courses = AcademicTask.objects.order_by("course").values_list("course", flat=True).distinct()
    return render(request, "planner/tasks.html", {"tasks": tasks, "courses": courses})


def task_create(request):
    form = AcademicTaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        task = form.save()
        messages.success(request, f"{task.title} was added.")
        return redirect("planner:tasks")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "task", "title": "Add academic work"})


def task_update(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk)
    form = AcademicTaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Academic work updated.")
        return redirect("planner:tasks")
    return render(request, "planner/form_page.html", {"form": form, "form_type": "task", "title": "Edit academic work", "editing": True})


def task_toggle(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk)
    if request.method == "POST":
        task.completed = not task.completed
        task.save(update_fields=["completed"])
        status = "completed" if task.completed else "active"
        messages.success(request, f"{task.title} marked {status}.")
    return redirect(request.POST.get("next", "planner:tasks"))


def task_delete(request, pk):
    task = get_object_or_404(AcademicTask, pk=pk)
    if request.method == "POST":
        title = task.title
        task.delete()
        messages.success(request, f"{title} was removed.")
        return redirect("planner:tasks")
    return render(request, "planner/confirm_delete.html", {"object": task, "cancel_url": reverse("planner:tasks")})


def course_delete(request, course):
    tasks = AcademicTask.objects.filter(course__iexact=course)
    if not tasks.exists():
        messages.info(request, f"No academic work remains for {course}.")
        return redirect("planner:tasks")
    if request.method == "POST":
        item_count = tasks.count()
        tasks.delete()
        Event.objects.filter(title__icontains=course).delete()
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


def routine_create(request):
    form = FlexibleRoutineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        routine = form.save()
        messages.success(request, f"{routine.title} was added. Generate a new plan to schedule it.")
        return redirect("planner:study_planner")
    return render(
        request,
        "planner/form_page.html",
        {"form": form, "form_type": "routine", "title": "Add a flexible routine"},
    )


def routine_update(request, pk):
    routine = get_object_or_404(FlexibleRoutine, pk=pk)
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


def routine_delete(request, pk):
    routine = get_object_or_404(FlexibleRoutine, pk=pk)
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


def study_planner(request):
    if request.method == "POST":
        result = generate_study_plan()
        messages.success(request, result["message"])
        if result["unscheduled"]:
            messages.warning(request, "Some items could not fit into the available time. Adjust the schedule or duration.")
        return redirect("planner:study_planner")

    tasks = list(AcademicTask.objects.all())
    sessions = list(StudySession.objects.filter(completed=False).select_related("task"))
    routine_sessions = list(RoutineSession.objects.filter(completed=False).select_related("routine"))
    today = timezone.localdate()
    calendar_days = []

    for offset in range(14):
        day = today + timedelta(days=offset)
        items = []

        for event in events_on(day):
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
            "routines": FlexibleRoutine.objects.all(),
            "active_tasks": [task for task in tasks if not task.completed],
            "insights": planner_insights(tasks, sessions),
        },
    )


def session_toggle(request, pk):
    session = get_object_or_404(StudySession, pk=pk)
    if request.method == "POST":
        session.completed = not session.completed
        session.save(update_fields=["completed"])
        messages.success(request, "Study session updated.")
    return redirect(request.POST.get("next", "planner:study_planner"))


def routine_session_toggle(request, pk):
    session = get_object_or_404(RoutineSession, pk=pk)
    if request.method == "POST":
        session.completed = not session.completed
        session.save(update_fields=["completed"])
        messages.success(request, "Routine session updated.")
    return redirect(request.POST.get("next", "planner:study_planner"))
