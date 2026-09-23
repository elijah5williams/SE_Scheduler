from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import AcademicTask, Event, FlexibleRoutine, RoutineSession, StudySession


DAY_START = time(8, 0)
DAY_END = time(22, 0)
SESSION_MAX_MINUTES = 90
MIN_SESSION_MINUTES = 30
BUFFER_MINUTES = 15


def aware(day, clock_time):
    return timezone.make_aware(datetime.combine(day, clock_time))


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda item: item[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def events_on(day):
    possible = Event.objects.filter(date__lte=day)
    return [event for event in possible if event.occurs_on(day)]


def busy_intervals(day):
    intervals = []
    buffer = timedelta(minutes=BUFFER_MINUTES)
    for event in events_on(day):
        intervals.append((event.starts_at(day) - buffer, event.ends_at(day) + buffer))
    # Include completed and newly generated sessions so two tasks never receive
    # overlapping study blocks during the same planning run.
    for session in StudySession.objects.filter(date=day):
        intervals.append((aware(day, session.start_time), aware(day, session.end_time)))
    for session in RoutineSession.objects.filter(date=day):
        intervals.append((aware(day, session.start_time), aware(day, session.end_time)))
    return merge_intervals(intervals)


def available_intervals(day, not_before=None, not_after=None):
    window_start = aware(day, DAY_START)
    window_end = aware(day, DAY_END)
    if not_before:
        window_start = max(window_start, not_before)
    if not_after:
        window_end = min(window_end, not_after)
    if window_end <= window_start:
        return []

    open_slots = []
    cursor = window_start
    for busy_start, busy_end in busy_intervals(day):
        busy_start = max(busy_start, window_start)
        busy_end = min(busy_end, window_end)
        if busy_end <= window_start or busy_start >= window_end:
            continue
        if busy_start > cursor:
            open_slots.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if cursor < window_end:
        open_slots.append((cursor, window_end))
    return open_slots


def task_sort_key(task):
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    return (task.due_date, priority_rank.get(task.priority, 1), -task.estimated_minutes)


def schedule_routines(routines, today, planning_end, now):
    created_sessions = []
    unscheduled_routines = []
    day = today

    while day <= planning_end:
        for routine in routines:
            if not routine.occurs_on(day):
                continue
            if RoutineSession.objects.filter(routine=routine, date=day, completed=True).exists():
                continue

            earliest = now + timedelta(minutes=15) if day == today else None
            if routine.window_start:
                window_start = aware(day, routine.window_start)
                earliest = max(earliest, window_start) if earliest else window_start
            latest = aware(day, routine.window_end) if routine.window_end else None
            slots = available_intervals(day, earliest, latest)
            scheduled = False

            for slot_start, slot_end in slots:
                available_minutes = int((slot_end - slot_start).total_seconds() // 60)
                if available_minutes < routine.duration_minutes:
                    continue
                session_end = slot_start + timedelta(minutes=routine.duration_minutes)
                session = RoutineSession.objects.create(
                    routine=routine,
                    date=day,
                    start_time=slot_start.time().replace(tzinfo=None),
                    end_time=session_end.time().replace(tzinfo=None),
                    generated=True,
                )
                created_sessions.append(session)
                scheduled = True
                break

            if not scheduled:
                unscheduled_routines.append((routine, day))
        day += timedelta(days=1)

    return created_sessions, unscheduled_routines


@transaction.atomic
def generate_study_plan():
    now = timezone.localtime()
    today = now.date()
    tasks = list(AcademicTask.objects.filter(completed=False).order_by("due_date"))
    routines = list(FlexibleRoutine.objects.filter(active=True))
    windowed_routines = [routine for routine in routines if routine.window_start and routine.window_end]
    open_routines = [routine for routine in routines if routine not in windowed_routines]
    planning_end = today + timedelta(days=13)

    StudySession.objects.filter(generated=True, completed=False, date__gte=today).delete()
    RoutineSession.objects.filter(generated=True, completed=False, date__gte=today).delete()

    latest_due = max((task.due_date for task in tasks), default=None)
    horizon_end = min(latest_due.date(), planning_end) if latest_due else planning_end
    task_minutes = {}
    for task in tasks:
        completed_minutes = sum(
            session.duration_minutes for session in task.study_sessions.filter(completed=True)
        )
        task_minutes[task.id] = max(0, task.estimated_minutes - completed_minutes)

    created_sessions = []
    created_routine_sessions, unscheduled_routines = schedule_routines(
        windowed_routines, today, planning_end, now
    )
    unscheduled_tasks = []

    for task in sorted(tasks, key=task_sort_key):
        minutes_left = task_minutes[task.id]
        if minutes_left == 0:
            continue
        if task.due_date <= now:
            unscheduled_tasks.append((task, minutes_left))
            continue

        final_day = min(task.due_date.date(), horizon_end)
        day = today

        while day <= final_day and minutes_left > 0:
            earliest = now + timedelta(minutes=15) if day == today else None
            deadline = task.due_date if day == task.due_date.date() else None
            slots = available_intervals(day, earliest, deadline)

            for slot_start, slot_end in slots:
                available_minutes = int((slot_end - slot_start).total_seconds() // 60)
                if available_minutes < MIN_SESSION_MINUTES:
                    continue

                session_minutes = min(SESSION_MAX_MINUTES, minutes_left, available_minutes)
                if session_minutes < MIN_SESSION_MINUTES and minutes_left >= MIN_SESSION_MINUTES:
                    continue

                session_end = slot_start + timedelta(minutes=session_minutes)
                session = StudySession.objects.create(
                    task=task,
                    date=day,
                    start_time=slot_start.time().replace(tzinfo=None),
                    end_time=session_end.time().replace(tzinfo=None),
                    generated=True,
                )
                created_sessions.append(session)
                minutes_left -= session_minutes
                if minutes_left <= 0:
                    break
            day += timedelta(days=1)

        if minutes_left > 0:
            unscheduled_tasks.append((task, minutes_left))

    open_sessions, open_unscheduled = schedule_routines(open_routines, today, planning_end, now)
    created_routine_sessions.extend(open_sessions)
    unscheduled_routines.extend(open_unscheduled)

    total_created = len(created_sessions) + len(created_routine_sessions)
    if total_created:
        parts = []
        if created_sessions:
            parts.append(f"{len(created_sessions)} study block{'s' if len(created_sessions) != 1 else ''}")
        if created_routine_sessions:
            parts.append(
                f"{len(created_routine_sessions)} flexible routine session"
                f"{'s' if len(created_routine_sessions) != 1 else ''}"
            )
        message = "Your plan is ready with " + " and ".join(parts) + "."
    elif not tasks and not routines:
        message = "Add academic work or a flexible routine before generating a plan."
    else:
        message = "No open blocks were available for the items in your plan."

    return {
        "created": total_created,
        "study_created": len(created_sessions),
        "routine_created": len(created_routine_sessions),
        "unscheduled": unscheduled_tasks + unscheduled_routines,
        "message": message,
    }


def planner_insights(tasks, sessions):
    insights = []
    now = timezone.now()
    active_tasks = [task for task in tasks if not task.completed]
    overdue = [task for task in active_tasks if task.due_date < now]
    high_priority = [task for task in active_tasks if task.priority == "high"]

    if overdue:
        insights.append(f"{len(overdue)} overdue item{'s need' if len(overdue) != 1 else ' needs'} immediate attention.")
    if high_priority:
        next_high = min(high_priority, key=lambda task: task.due_date)
        insights.append(f"Start with {next_high.course}: {next_high.title}; it is your nearest high-priority deadline.")
    if sessions:
        total_minutes = sum(session.duration_minutes for session in sessions)
        insights.append(f"Your current plan protects {total_minutes // 60}h {total_minutes % 60}m of focused study time.")
    if not active_tasks:
        insights.append("You are caught up. Add your next assignment or exam to keep the planner useful.")
    elif not sessions:
        insights.append("Generate a plan to fit focused work around your classes and athletic schedule.")
    return insights[:3]
