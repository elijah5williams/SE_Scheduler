from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from planner.models import AcademicTask, Event, FlexibleRoutine, RoutineSession, StudySession
from planner.services import generate_study_plan


class Command(BaseCommand):
    help = "Replace current planner data with a presentation-ready demo week."

    def handle(self, *args, **options):
        StudySession.objects.all().delete()
        RoutineSession.objects.all().delete()
        FlexibleRoutine.objects.all().delete()
        AcademicTask.objects.all().delete()
        Event.objects.all().delete()

        today = timezone.localdate()
        now = timezone.localtime()

        events = [
            ("CSC 305 — Data Structures", "class", 1, time(10, 30), time(11, 45), "Fuller Hall", "1,3"),
            ("Information Security", "class", 0, time(14, 30), time(15, 20), "Kennedy Hall", "0,2,4"),
            ("Football Practice", "practice", 0, time(16, 0), time(18, 0), "Multi-Sport Stadium", "0,1,2,3,4"),
            ("Strength Training", "workout", 2, time(7, 0), time(8, 0), "Plourde Center", ""),
            ("Team Meeting", "meeting", 3, time(18, 30), time(19, 15), "Football offices", ""),
            ("Game Day", "game", 5, time(12, 0), time(16, 0), "Multi-Sport Stadium", ""),
        ]
        for title, event_type, offset, start, end, location, weekdays in events:
            Event.objects.create(
                title=title,
                event_type=event_type,
                date=today + timedelta(days=offset),
                start_time=start,
                end_time=end,
                location=location,
                repeat_weekly=event_type in {"class", "practice"},
                weekdays=weekdays,
            )

        tasks = [
            ("Merge Sort Analysis", "CSC 305", "assignment", 2, 150, "high"),
            ("Security Policy Reflection", "SEC 200", "assignment", 4, 90, "medium"),
            ("Trees and Graphs Exam", "CSC 305", "exam", 7, 240, "high"),
            ("Chapter 3 Reading", "SEC 200", "reading", 5, 60, "low"),
        ]
        for title, course, task_type, days, minutes, priority in tasks:
            AcademicTask.objects.create(
                title=title,
                course=course,
                task_type=task_type,
                due_date=now + timedelta(days=days),
                estimated_minutes=minutes,
                priority=priority,
            )

        FlexibleRoutine.objects.create(
            title="Bible study",
            duration_minutes=20,
            weekdays="0,1,2,3,4,5,6",
            notes="Daily reading and reflection",
        )
        FlexibleRoutine.objects.create(
            title="Weekend breakfast",
            duration_minutes=25,
            weekdays="5,6",
            window_start=time(11, 0),
            window_end=time(13, 30),
            notes="Cafe breakfast hours",
        )

        result = generate_study_plan()
        self.stdout.write(self.style.SUCCESS(f"Demo ready. {result['message']}"))
