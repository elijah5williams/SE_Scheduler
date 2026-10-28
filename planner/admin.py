from django.contrib import admin

from .models import AcademicTask, Event, FlexibleRoutine, RoutineSession, StudySession, Profile


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "date", "start_time", "repeat_weekly")
    list_filter = ("event_type", "repeat_weekly")
    search_fields = ("title", "location")


@admin.register(AcademicTask)
class AcademicTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "task_type", "due_date", "priority", "completed")
    list_filter = ("task_type", "priority", "completed")
    search_fields = ("title", "course")


@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ("task", "date", "start_time", "end_time", "completed")
    list_filter = ("completed", "generated")


@admin.register(FlexibleRoutine)
class FlexibleRoutineAdmin(admin.ModelAdmin):
    list_display = ("title", "duration_minutes", "window_start", "window_end", "active")
    list_filter = ("active",)
    search_fields = ("title",)


@admin.register(RoutineSession)
class RoutineSessionAdmin(admin.ModelAdmin):
    list_display = ("routine", "date", "start_time", "end_time", "completed")
    list_filter = ("completed", "generated")

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "school_email", "email_verified", "verification_status", "verified_role")
    list_filter = ("role", "verification_status")
    search_fields = ("user__username", "school_email")