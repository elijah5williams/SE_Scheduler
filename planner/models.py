from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Event(models.Model):
    CLASS = "class"
    PRACTICE = "practice"
    GAME = "game"
    WORKOUT = "workout"
    MEETING = "meeting"
    OTHER = "other"

    EVENT_TYPES = [
        (CLASS, "Class"),
        (PRACTICE, "Practice"),
        (GAME, "Game"),
        (WORKOUT, "Workout"),
        (MEETING, "Team meeting"),
        (OTHER, "Other"),
    ]
    WEEKDAYS = [
        ("0", "Monday"),
        ("1", "Tuesday"),
        ("2", "Wednesday"),
        ("3", "Thursday"),
        ("4", "Friday"),
        ("5", "Saturday"),
        ("6", "Sunday"),
    ]

    title = models.CharField(max_length=120)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    repeat_weekly = models.BooleanField(default=False)
    weekdays = models.CharField(max_length=20, blank=True)
    repeat_until = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return self.title

    def clean(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be later than start time."})
        if self.repeat_weekly and self.repeat_until and self.repeat_until < self.date:
            raise ValidationError({"repeat_until": "Repeat-until date cannot be before the first date."})

    def occurs_on(self, day):
        if not self.repeat_weekly:
            return day == self.date
        if day < self.date:
            return False
        if self.repeat_until and day > self.repeat_until:
            return False
        selected_days = self.weekday_numbers or {self.date.weekday()}
        return day.weekday() in selected_days

    @property
    def weekday_numbers(self):
        raw_days = self.weekdays
        if isinstance(raw_days, (list, tuple)):
            values = raw_days
        else:
            values = raw_days.split(",") if raw_days else []
        return {int(value) for value in values if str(value).isdigit()}

    @property
    def repeat_summary(self):
        if not self.repeat_weekly:
            return "One time"
        short_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = sorted(self.weekday_numbers or {self.date.weekday()})
        return "Every " + ", ".join(short_names[day] for day in days)

    def starts_at(self, day=None):
        event_day = day or self.date
        return timezone.make_aware(datetime.combine(event_day, self.start_time))

    def ends_at(self, day=None):
        event_day = day or self.date
        return timezone.make_aware(datetime.combine(event_day, self.end_time))


class AcademicTask(models.Model):
    ASSIGNMENT = "assignment"
    EXAM = "exam"
    PROJECT = "project"
    READING = "reading"
    OTHER = "other"

    TASK_TYPES = [
        (ASSIGNMENT, "Assignment"),
        (EXAM, "Exam"),
        (PROJECT, "Project"),
        (READING, "Reading"),
        (OTHER, "Other"),
    ]
    PRIORITIES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]

    title = models.CharField(max_length=140)
    course = models.CharField(max_length=80)
    task_type = models.CharField(max_length=20, choices=TASK_TYPES, default=ASSIGNMENT)
    due_date = models.DateTimeField()
    estimated_minutes = models.PositiveIntegerField(default=60)
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="medium")
    notes = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completed", "due_date"]

    def __str__(self):
        return f"{self.course}: {self.title}"

    @property
    def is_overdue(self):
        return not self.completed and self.due_date < timezone.now()


class FlexibleRoutine(models.Model):
    WEEKDAYS = Event.WEEKDAYS

    title = models.CharField(max_length=120)
    duration_minutes = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(5), MaxValueValidator(180)],
    )
    window_start = models.TimeField(blank=True, null=True)
    window_end = models.TimeField(blank=True, null=True)
    weekdays = models.CharField(max_length=20, default="0,1,2,3,4,5,6")
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def clean(self):
        if bool(self.window_start) != bool(self.window_end):
            raise ValidationError("Enter both the available-from and available-until times.")
        if self.window_start and self.window_end:
            if self.window_end <= self.window_start:
                raise ValidationError({"window_end": "Available-until time must be later than available-from time."})
            window_minutes = int(
                (
                    datetime.combine(timezone.localdate(), self.window_end)
                    - datetime.combine(timezone.localdate(), self.window_start)
                ).total_seconds()
                // 60
            )
            if self.duration_minutes and self.duration_minutes > window_minutes:
                raise ValidationError(
                    {"duration_minutes": "The time needed must fit inside the available time window."}
                )

    @property
    def weekday_numbers(self):
        raw_days = self.weekdays
        if isinstance(raw_days, (list, tuple)):
            values = raw_days
        else:
            values = raw_days.split(",") if raw_days else []
        return {int(value) for value in values if str(value).isdigit()}

    def occurs_on(self, day):
        return self.active and day.weekday() in self.weekday_numbers

    @property
    def schedule_summary(self):
        selected = self.weekday_numbers
        if selected == set(range(7)):
            return "Every day"
        if selected == set(range(5)):
            return "Weekdays"
        short_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return ", ".join(short_names[day] for day in sorted(selected))

    @property
    def window_summary(self):
        if not self.window_start or not self.window_end:
            return "Any open time"
        start = self.window_start.strftime("%I:%M %p").lstrip("0")
        end = self.window_end.strftime("%I:%M %p").lstrip("0")
        return f"Between {start} and {end}"


class StudySession(models.Model):
    task = models.ForeignKey(AcademicTask, on_delete=models.CASCADE, related_name="study_sessions")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    completed = models.BooleanField(default=False)
    generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"Study {self.task.title} on {self.date}"

    @property
    def duration_minutes(self):
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        return int((end - start).total_seconds() // 60)


class RoutineSession(models.Model):
    routine = models.ForeignKey(FlexibleRoutine, on_delete=models.CASCADE, related_name="sessions")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    completed = models.BooleanField(default=False)
    generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            models.UniqueConstraint(fields=["routine", "date"], name="one_routine_session_per_day")
        ]

    def __str__(self):
        return f"{self.routine.title} on {self.date}"

    @property
    def duration_minutes(self):
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        return int((end - start).total_seconds() // 60)
