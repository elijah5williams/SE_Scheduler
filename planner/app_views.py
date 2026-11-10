"""Pages and data used only by the installed phone app.

- /app/more/              the "More" tab: extra pages, notifications and app settings
- /app/status.json        the number shown on the app icon (things left to do today)
- /app/offline-data.json  the next two weeks of the user's schedule, saved on the phone
                          so it can be checked with no signal
- /app/push/...           turning phone notifications on and off
"""

import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import push
from .models import AcademicTask, Event, Profile, PushSubscription, RoutineSession, StudySession, Team
from .services import events_on

OFFLINE_DAYS = 14
ATHLETIC_TYPES = {Event.PRACTICE, Event.GAME, Event.WORKOUT, Event.MEETING}


def _time(value):
    return value.strftime("%H:%M") if value else ""


def schedule_items(user, day, tasks=None, sessions=None, routine_sessions=None):
    """Everything on one day for this user, in time order, as plain data."""
    items = []
    for event in events_on(day, user):
        items.append({
            "kind": "athletic" if event.event_type in ATHLETIC_TYPES else "class",
            "label": event.get_event_type_display(),
            "title": event.title,
            "start": _time(event.start_time),
            "end": _time(event.end_time),
            "location": event.location,
        })
    for session in sessions if sessions is not None else StudySession.objects.filter(date=day, task__user=user).select_related("task"):
        if session.date == day:
            items.append({
                "kind": "study", "label": f"Study · {session.task.course}", "title": session.task.title,
                "start": _time(session.start_time), "end": _time(session.end_time), "location": "",
                "done": session.completed,
            })
    for session in routine_sessions if routine_sessions is not None else RoutineSession.objects.filter(date=day, routine__user=user).select_related("routine"):
        if session.date == day:
            items.append({
                "kind": "routine", "label": "Routine", "title": session.routine.title,
                "start": _time(session.start_time), "end": _time(session.end_time), "location": "",
                "done": session.completed,
            })
    for task in tasks if tasks is not None else AcademicTask.objects.filter(user=user, completed=False):
        due = timezone.localtime(task.due_date)
        if not task.completed and due.date() == day:
            items.append({
                "kind": "deadline", "label": f"Due · {task.course}", "title": task.title,
                "start": _time(due.time()), "end": "", "location": "",
            })
    items.sort(key=lambda item: item["start"])
    return items


def things_left_today(user):
    today = timezone.localdate()
    now = timezone.localtime()
    count = AcademicTask.objects.filter(user=user, completed=False, due_date__date=today, due_date__gte=now).count()
    count += StudySession.objects.filter(task__user=user, date=today, completed=False).count()
    count += RoutineSession.objects.filter(routine__user=user, date=today, completed=False).count()
    return count


@login_required
def more(request):
    profile = request.user.profile
    is_coach = profile.role == Profile.COACH
    from .views import calendar_links

    return render(request, "planner/app_more.html", {
        "is_coach": is_coach,
        "coach_teams": list(Team.coached_by(request.user)) if is_coach and profile.is_verified_coach else [],
        "push_enabled": push.enabled(),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        **calendar_links(request),
    })


@login_required
def status(request):
    response = JsonResponse({"badge": things_left_today(request.user)})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def offline_data(request):
    user = request.user
    today = timezone.localdate()
    end = today + timedelta(days=OFFLINE_DAYS - 1)
    tasks = list(AcademicTask.objects.filter(user=user, completed=False))
    sessions = list(StudySession.objects.filter(task__user=user, date__range=(today, end)).select_related("task"))
    routine_sessions = list(
        RoutineSession.objects.filter(routine__user=user, date__range=(today, end)).select_related("routine")
    )
    days = []
    for offset in range(OFFLINE_DAYS):
        day = today + timedelta(days=offset)
        days.append({
            "date": day.isoformat(),
            "items": schedule_items(user, day, tasks, sessions, routine_sessions),
        })
    response = JsonResponse({
        "user": user.get_full_name() or user.username,
        "saved_at": timezone.localtime().isoformat(),
        "days": days,
    })
    response["Cache-Control"] = "private, no-cache"
    return response


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}


@login_required
@require_POST
def push_subscribe(request):
    if not push.enabled():
        return JsonResponse({"ok": False, "error": "Notifications aren't set up on this server."}, status=503)
    data = _json_body(request)
    endpoint = str(data.get("endpoint", ""))[:1000]
    keys = data.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh", ""))[:200], str(keys.get("auth", ""))[:100]
    if not (push.is_allowed_endpoint(endpoint) and p256dh and auth):
        return JsonResponse({"ok": False, "error": "That isn't a valid notification subscription."}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
        },
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_unsubscribe(request):
    endpoint = str(_json_body(request).get("endpoint", ""))
    if endpoint:
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_test(request):
    sent = push.notify_users(
        [request.user],
        "Notifications are on",
        "You'll hear about practice changes, new team events, game time changes and final scores.",
        url="/app/more/",
        tag="test",
    )
    return JsonResponse({"ok": bool(sent)})
