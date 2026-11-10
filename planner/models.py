import re
import secrets
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.conf import settings


class Event(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        related_name="%(class)ss",
    )

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
    # Set when a coach's assignment (or a synced team game) put this on the athlete's schedule.
    assignment = models.ForeignKey(
        "Assignment", null=True, blank=True, on_delete=models.CASCADE, related_name="events"
    )
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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        related_name="%(class)ss",
    )


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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        related_name="%(class)ss",
    )
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

class Profile(models.Model):
    STUDENT = "student"
    TEACHER = "teacher"
    COACH = "coach"
    ROLE_CHOICES = [(STUDENT, "Student"), (TEACHER, "Teacher"), (COACH, "Coach")]

    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    VERIFICATION_CHOICES = [
        (UNVERIFIED, "Unverified"),
        (PENDING, "Pending review"),
        (VERIFIED, "Verified"),
        (REJECTED, "Rejected"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=STUDENT)  # what they picked
    school_email = models.EmailField(unique=True, null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    verification_status = models.CharField(
        max_length=12, choices=VERIFICATION_CHOICES, default=UNVERIFIED
    )
    verified_role = models.CharField(max_length=10, choices=ROLE_CHOICES, blank=True)  # what the check confirmed
    verified_at = models.DateTimeField(null=True, blank=True)
    calendar_token = models.CharField(max_length=40, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.role}, {self.verification_status})"

    @property
    def is_verified_student(self):
        return self.verification_status == self.VERIFIED and self.verified_role == self.STUDENT

    @property
    def is_verified_teacher(self):
        return self.verification_status == self.VERIFIED and self.verified_role == self.TEACHER
    @property
    def is_verified_coach(self):
        return self.verification_status == self.VERIFIED and self.verified_role == self.COACH

    def _main_team(self):
        if self.role == self.COACH:
            role = self.user.staff_roles.select_related("team").order_by("team__name").first()
            if role:
                return role.team, role.title
            team = self.user.coached_teams.order_by("name").first()
            return team, "Head Coach" if team else None
        if self.role == self.STUDENT:
            team = self.user.teams.order_by("name").first()
            if team:
                sport = team.name.removeprefix("Assumption ").strip() or team.name
                return team, f"{sport} Player"
        return None, None

    @property
    def display_title(self):
        """What the sidebar calls this person: "Head Coach", "Football Player", "Teacher", ..."""
        _, title = self._main_team()
        if title:
            return title
        return {self.COACH: "Coach", self.TEACHER: "Teacher"}.get(self.role, "Athlete")

    def get_calendar_token(self, reset=False):
        """Private token for this user's calendar feed URL. Created on first use."""
        if reset or not self.calendar_token:
            self.calendar_token = secrets.token_urlsafe(24)
            self.save(update_fields=["calendar_token"])
        return self.calendar_token

    @property
    def display_team(self):
        team, _ = self._main_team()
        return team.name if team else ""

def make_join_code():
    return secrets.token_hex(4).upper()  # 8 characters: about 4 billion possible codes


class Team(models.Model):
    # Nullable so a school's teams can exist before a coach account is attached.
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coached_teams",
    )
    name = models.CharField(max_length=80)
    join_code = models.CharField(max_length=8, unique=True, default=make_join_code)
    athletes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="teams")
    schedule_url = models.URLField(
        blank=True, help_text="Athletics website schedule page, e.g. https://assumptiongreyhounds.com/sports/football/schedule"
    )
    schedule_synced_at = models.DateTimeField(null=True, blank=True)
    # Season record from the schedule page, as [label, value] pairs: [["Overall", "6-2"], ["PCT", ".750"], ...]
    season_record = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def logo_url(self):
        """The school's logo, served by the same athletics site as the schedule."""
        if not self.schedule_url:
            return ""
        from urllib.parse import urljoin

        return urljoin(self.schedule_url, "/images/logos/site/site.png")

    @property
    def school_name(self):
        return self.name.split(" ", 1)[0]

    @classmethod
    def coached_by(cls, user):
        """Teams this user leads, as head coach or as a member of the coaching staff."""
        return cls.objects.filter(models.Q(coach=user) | models.Q(staff__user=user)).distinct()


class StaffMember(models.Model):
    """A coach on a team's staff, with their title (Head Coach, Defensive Coordinator, ...)."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="staff")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_roles")
    title = models.CharField(max_length=80, default="Assistant Coach")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="one_staff_role_per_team")]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}, {self.title} ({self.team.name})"


class Assignment(models.Model):
    TYPES = [
        (Event.WORKOUT, "Workout"),
        (Event.PRACTICE, "Training"),
        (Event.GAME, "Game"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="assignments")
    event_type = models.CharField(max_length=20, choices=TYPES, default=Event.PRACTICE)
    title = models.CharField(max_length=120)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    repeat_weekly = models.BooleanField(default=False)
    repeat_until = models.DateField(blank=True, null=True)
    # Filled in for games pulled from the team's schedule page; blank for ones a coach typed in.
    external_id = models.CharField(max_length=40, blank=True, db_index=True)
    result = models.CharField(max_length=40, blank=True)
    opponent = models.CharField(max_length=120, blank=True)
    opponent_logo = models.URLField(blank=True)
    is_home = models.BooleanField(null=True, blank=True)  # None = neutral site
    time_tba = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.title} ({self.team.name})"

    @property
    def is_synced(self):
        return bool(self.external_id)

    @property
    def outcome(self):
        """"W", "L" or "T" for a scored game; "" for meets, cancellations and unplayed games."""
        return self.result[:1] if re.match(r"^[WLT], ", self.result or "") else ""

    @property
    def score(self):
        """The score for W/L/T results ("34-27"), otherwise the result as posted ("6th (176)")."""
        return self.result[3:] if self.outcome else self.result

    @property
    def is_cancelled(self):
        return (self.result or "").lower().startswith(("cancel", "postpone"))

    @property
    def matchup_word(self):
        return "at" if self.is_home is False else "vs."

    def clean(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be later than start time."})
        if self.repeat_weekly and self.repeat_until and self.repeat_until < self.date:
            raise ValidationError({"repeat_until": "Repeat-until date cannot be before the first date."})

    def _event_fields(self):
        return {
            "title": self.title,
            "event_type": self.event_type,
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "location": self.location,
            "notes": "\n".join(part for part in [f"Final: {self.result}" if self.result else "", self.notes] if part),
            "repeat_weekly": self.repeat_weekly,
            "weekdays": "",
            "repeat_until": self.repeat_until,
        }

    def push_to(self, athlete):
        Event.objects.get_or_create(assignment=self, user=athlete, defaults=self._event_fields())

    def push_to_team(self):
        for athlete in self.team.athletes.all():
            self.push_to(athlete)

    def sync_events(self):
        self.events.update(**self._event_fields())

class AthleticsPhoto(models.Model):
    """Recent news photos from the athletics website, shown on the login page."""

    image_url = models.URLField(max_length=500)
    title = models.CharField(max_length=300)
    link = models.URLField(max_length=500)
    position = models.PositiveSmallIntegerField(default=0)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.title


class AthleteBio(models.Model):
    """Roster details from the athletics website, used for the player spotlight."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="bios")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="athlete_bios")
    photo_url = models.URLField(max_length=500, blank=True)
    number = models.CharField(max_length=10, blank=True)
    position = models.CharField(max_length=40, blank=True)
    height = models.CharField(max_length=20, blank=True)
    year = models.CharField(max_length=20, blank=True)
    hometown = models.CharField(max_length=120, blank=True)
    bio_url = models.URLField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="one_bio_per_team")]

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.team.name})"
