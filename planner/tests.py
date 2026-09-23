from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AcademicTask, Event, FlexibleRoutine, RoutineSession, StudySession
from .services import generate_study_plan


class PlannerModelTests(TestCase):
    def test_weekly_event_occurrence(self):
        monday = timezone.localdate()
        while monday.weekday() != 0:
            monday += timedelta(days=1)
        event = Event.objects.create(
            title="Football practice",
            event_type=Event.PRACTICE,
            date=monday,
            start_time=time(16, 0),
            end_time=time(18, 0),
            repeat_weekly=True,
            weekdays="0,2,4",
        )
        self.assertTrue(event.occurs_on(monday + timedelta(days=7)))
        self.assertTrue(event.occurs_on(monday + timedelta(days=9)))
        self.assertFalse(event.occurs_on(monday + timedelta(days=1)))

    def test_anchor_date_is_not_shown_when_weekday_is_unselected(self):
        monday = timezone.localdate()
        while monday.weekday() != 0:
            monday += timedelta(days=1)
        event = Event.objects.create(
            title="Tuesday Thursday class",
            event_type=Event.CLASS,
            date=monday,
            start_time=time(10, 0),
            end_time=time(11, 0),
            repeat_weekly=True,
            weekdays="1,3",
        )
        self.assertFalse(event.occurs_on(monday))
        self.assertTrue(event.occurs_on(monday + timedelta(days=1)))


class StudyPlannerTests(TestCase):
    def test_planner_creates_session_around_event(self):
        today = timezone.localdate()
        Event.objects.create(
            title="Practice",
            event_type=Event.PRACTICE,
            date=today,
            start_time=time(16, 0),
            end_time=time(18, 0),
        )
        due = timezone.now() + timedelta(days=2)
        task = AcademicTask.objects.create(
            title="Data structures homework",
            course="CSC 305",
            due_date=due,
            estimated_minutes=120,
            priority="high",
        )
        result = generate_study_plan()
        sessions = StudySession.objects.filter(task=task)
        self.assertGreater(result["created"], 0)
        self.assertTrue(sessions.exists())
        for session in sessions.filter(date=today):
            self.assertFalse(session.start_time < time(18, 15) and session.end_time > time(15, 45))

    def test_completed_sessions_are_preserved_when_regenerating(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        task = AcademicTask.objects.create(
            title="Exam review",
            course="MGT 100",
            due_date=timezone.now() + timedelta(days=3),
            estimated_minutes=60,
        )
        session = StudySession.objects.create(
            task=task,
            date=tomorrow,
            start_time=time(10, 0),
            end_time=time(11, 0),
            completed=True,
        )
        generate_study_plan()
        self.assertTrue(StudySession.objects.filter(pk=session.pk).exists())

    def test_generated_sessions_do_not_overlap(self):
        due = timezone.now() + timedelta(days=2)
        for number in range(2):
            AcademicTask.objects.create(
                title=f"Assignment {number}",
                course="CSC 305",
                due_date=due,
                estimated_minutes=90,
            )
        generate_study_plan()
        sessions = list(StudySession.objects.order_by("date", "start_time"))
        for first, second in zip(sessions, sessions[1:]):
            if first.date == second.date:
                self.assertLessEqual(first.end_time, second.start_time)

    def test_daily_flexible_routine_is_placed_in_open_time(self):
        today = timezone.localdate()
        Event.objects.create(
            title="Morning class",
            event_type=Event.CLASS,
            date=today,
            start_time=time(8, 0),
            end_time=time(10, 0),
            repeat_weekly=True,
            weekdays="0,1,2,3,4,5,6",
        )
        routine = FlexibleRoutine.objects.create(
            title="Bible study",
            duration_minutes=20,
            weekdays="0,1,2,3,4,5,6",
        )
        result = generate_study_plan()
        future_sessions = RoutineSession.objects.filter(
            routine=routine,
            date__gt=today,
            date__lte=today + timedelta(days=13),
        )
        self.assertEqual(result["routine_created"], RoutineSession.objects.count())
        self.assertEqual(future_sessions.count(), 13)
        for session in future_sessions:
            self.assertGreaterEqual(session.start_time, time(10, 15))

    def test_flexible_routine_can_generate_without_academic_tasks(self):
        FlexibleRoutine.objects.create(
            title="Stretching",
            duration_minutes=10,
            weekdays="0,1,2,3,4,5,6",
        )
        result = generate_study_plan()
        self.assertGreater(result["created"], 0)
        self.assertEqual(result["study_created"], 0)
        self.assertGreater(result["routine_created"], 0)

    def test_windowed_routine_is_scheduled_inside_its_availability(self):
        today = timezone.localdate()
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        if saturday == today:
            saturday += timedelta(days=7)
        Event.objects.create(
            title="Team activity",
            event_type=Event.MEETING,
            date=saturday,
            start_time=time(11, 0),
            end_time=time(11, 45),
        )
        routine = FlexibleRoutine.objects.create(
            title="Weekend breakfast",
            duration_minutes=25,
            weekdays="5,6",
            window_start=time(11, 0),
            window_end=time(13, 30),
        )

        generate_study_plan()

        session = RoutineSession.objects.get(routine=routine, date=saturday)
        self.assertGreaterEqual(session.start_time, time(11, 0))
        self.assertLessEqual(session.end_time, time(13, 30))
        self.assertGreaterEqual(session.start_time, time(12, 0))

    def test_windowed_routine_is_reserved_before_study_blocks(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        weekday = str(tomorrow.weekday())
        routine = FlexibleRoutine.objects.create(
            title="Lunch",
            duration_minutes=30,
            weekdays=weekday,
            window_start=time(11, 0),
            window_end=time(12, 0),
        )
        task = AcademicTask.objects.create(
            title="Large project",
            course="CSC 305",
            due_date=timezone.now() + timedelta(days=2),
            estimated_minutes=600,
            priority="high",
        )

        generate_study_plan()

        routine_session = RoutineSession.objects.get(routine=routine, date=tomorrow)
        for session in StudySession.objects.filter(task=task, date=tomorrow):
            self.assertTrue(
                session.end_time <= routine_session.start_time
                or session.start_time >= routine_session.end_time
            )


class PageTests(TestCase):
    def test_main_pages_load(self):
        for route in ["dashboard", "schedule", "tasks", "study_planner", "event_create", "task_create", "routine_create"]:
            response = self.client.get(reverse(f"planner:{route}"))
            self.assertEqual(response.status_code, 200)

    def test_study_planner_groups_items_inside_calendar_days(self):
        day = timezone.localdate() + timedelta(days=1)
        task = AcademicTask.objects.create(
            title="Linked list practice",
            course="CSC 305",
            due_date=timezone.now() + timedelta(days=3),
            estimated_minutes=120,
        )
        for start_hour in [10, 14]:
            StudySession.objects.create(
                task=task,
                date=day,
                start_time=time(start_hour, 0),
                end_time=time(start_hour + 1, 0),
            )
        response = self.client.get(reverse("planner:study_planner"))
        calendar_day = next(item for item in response.context["calendar_days"] if item["date"] == day)
        study_items = [item for item in calendar_day["items"] if item["kind"] == "study"]
        self.assertEqual(len(response.context["calendar_days"]), 14)
        self.assertEqual(len(study_items), 2)
        self.assertContains(response, "Daily game plan")

    def test_routine_appears_inside_calendar_day(self):
        day = timezone.localdate() + timedelta(days=1)
        routine = FlexibleRoutine.objects.create(
            title="Bible study",
            duration_minutes=20,
            weekdays="0,1,2,3,4,5,6",
        )
        RoutineSession.objects.create(
            routine=routine,
            date=day,
            start_time=time(12, 0),
            end_time=time(12, 20),
        )
        response = self.client.get(reverse("planner:study_planner"))
        calendar_day = next(item for item in response.context["calendar_days"] if item["date"] == day)
        routine_items = [item for item in calendar_day["items"] if item["kind"] == "routine"]
        self.assertEqual(len(routine_items), 1)
        self.assertContains(response, "Bible study")

    def test_add_daily_flexible_routine(self):
        response = self.client.post(
            reverse("planner:routine_create"),
            {
                "title": "Bible study",
                "duration_minutes": 20,
                "weekdays": ["0", "1", "2", "3", "4", "5", "6"],
                "active": "on",
                "notes": "Daily reading",
            },
        )
        self.assertRedirects(response, reverse("planner:study_planner"))
        routine = FlexibleRoutine.objects.get(title="Bible study")
        self.assertEqual(routine.duration_minutes, 20)
        self.assertEqual(routine.weekdays, "0,1,2,3,4,5,6")

    def test_add_windowed_flexible_item(self):
        response = self.client.post(
            reverse("planner:routine_create"),
            {
                "title": "Weekend breakfast",
                "duration_minutes": 25,
                "window_start": "11:00",
                "window_end": "13:30",
                "weekdays": ["5", "6"],
                "active": "on",
                "notes": "Cafe hours",
            },
        )
        self.assertRedirects(response, reverse("planner:study_planner"))
        routine = FlexibleRoutine.objects.get(title="Weekend breakfast")
        self.assertEqual(routine.window_start, time(11, 0))
        self.assertEqual(routine.window_end, time(13, 30))

    def test_dashboard_shows_known_end_times(self):
        event = Event.objects.create(
            title="CSC 305",
            event_type=Event.CLASS,
            date=timezone.localdate(),
            start_time=time(10, 0),
            end_time=time(11, 15),
        )
        response = self.client.get(reverse("planner:dashboard"))
        self.assertContains(response, "10:00 AM–11:15 AM")
        self.assertContains(response, event.title)

    def test_add_task(self):
        due = timezone.localtime() + timedelta(days=2)
        response = self.client.post(
            reverse("planner:task_create"),
            {
                "task_type": "assignment",
                "title": "Homework 1",
                "course": "CSC 305",
                "due_date": due.strftime("%Y-%m-%dT%H:%M"),
                "estimated_minutes": 60,
                "priority": "medium",
                "notes": "",
            },
        )
        self.assertRedirects(response, reverse("planner:tasks"))
        self.assertEqual(AcademicTask.objects.count(), 1)

    def test_schedule_exposes_event_management(self):
        event = Event.objects.create(
            title="CSC 305",
            event_type=Event.CLASS,
            date=timezone.localdate(),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        response = self.client.get(reverse("planner:schedule"))
        self.assertContains(response, reverse("planner:event_update", args=[event.pk]))
        self.assertContains(response, reverse("planner:event_delete", args=[event.pk]))

    def test_edit_event_supports_multiple_weekdays(self):
        event = Event.objects.create(
            title="CSC 305",
            event_type=Event.CLASS,
            date=timezone.localdate(),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        response = self.client.post(
            reverse("planner:event_update", args=[event.pk]),
            {
                "event_type": "class",
                "title": "CSC 305",
                "date": timezone.localdate().isoformat(),
                "start_time": "10:30",
                "end_time": "11:45",
                "location": "Fuller Hall",
                "repeat_weekly": "on",
                "weekdays": ["1", "3"],
                "repeat_until": "",
                "notes": "",
            },
        )
        self.assertRedirects(response, reverse("planner:schedule"))
        event.refresh_from_db()
        self.assertEqual(event.weekdays, "1,3")

    def test_delete_event(self):
        event = Event.objects.create(
            title="Old class",
            event_type=Event.CLASS,
            date=timezone.localdate(),
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        response = self.client.post(reverse("planner:event_delete", args=[event.pk]))
        self.assertRedirects(response, reverse("planner:schedule"))
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())

    def test_delete_class_can_remove_selected_course_work(self):
        event = Event.objects.create(
            title="Intro to Management",
            event_type=Event.CLASS,
            date=timezone.localdate(),
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        task = AcademicTask.objects.create(
            title="Reflection",
            course="MGT 100",
            due_date=timezone.now() + timedelta(days=2),
        )
        StudySession.objects.create(
            task=task,
            date=timezone.localdate() + timedelta(days=1),
            start_time=time(12, 0),
            end_time=time(13, 0),
        )
        response = self.client.post(
            reverse("planner:event_delete", args=[event.pk]),
            {"related_courses": ["MGT 100"]},
        )
        self.assertRedirects(response, reverse("planner:schedule"))
        self.assertFalse(AcademicTask.objects.filter(course="MGT 100").exists())
        self.assertFalse(StudySession.objects.exists())

    def test_remove_entire_course_after_class_event_is_gone(self):
        task = AcademicTask.objects.create(
            title="Reflection",
            course="MGT 100",
            due_date=timezone.now() + timedelta(days=2),
        )
        StudySession.objects.create(
            task=task,
            date=timezone.localdate() + timedelta(days=1),
            start_time=time(12, 0),
            end_time=time(13, 0),
        )
        response = self.client.post(reverse("planner:course_delete", args=["MGT 100"]))
        self.assertRedirects(response, reverse("planner:schedule"))
        self.assertFalse(AcademicTask.objects.filter(course="MGT 100").exists())
        self.assertFalse(StudySession.objects.exists())
