from django.urls import path

from . import app_views, views


app_name = "planner"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("calendar/<str:token>.ics", views.calendar_feed, name="calendar_feed"),
    path("calendar/reset/", views.calendar_reset, name="calendar_reset"),
    path("schedule/", views.schedule, name="schedule"),
    path("events/add/", views.event_create, name="event_create"),
    path("events/<int:pk>/edit/", views.event_update, name="event_update"),
    path("events/<int:pk>/delete/", views.event_delete, name="event_delete"),
    path("tasks/", views.task_list, name="tasks"),
    path("tasks/add/", views.task_create, name="task_create"),
    path("tasks/<int:pk>/edit/", views.task_update, name="task_update"),
    path("tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),
    path("tasks/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("courses/<str:course>/delete/", views.course_delete, name="course_delete"),
    path("routines/add/", views.routine_create, name="routine_create"),
    path("routines/<int:pk>/edit/", views.routine_update, name="routine_update"),
    path("routines/<int:pk>/delete/", views.routine_delete, name="routine_delete"),
    path("planner/", views.study_planner, name="study_planner"),
    path("planner/session/<int:pk>/toggle/", views.session_toggle, name="session_toggle"),
    path("planner/routine-session/<int:pk>/toggle/", views.routine_session_toggle, name="routine_session_toggle"),
    path("coach/", views.coach_dashboard, name="coach_dashboard"),
    path("coach/schedule/", views.coach_schedule, name="coach_schedule"),
    path("coach/roster/", views.coach_roster, name="coach_roster"),
    path("coach/staff/", views.coach_staff, name="coach_staff"),
    path("coach/teams/new/", views.team_create, name="team_create"),
    path("coach/teams/<int:team_pk>/assign/", views.assignment_create, name="assignment_create"),
    path("coach/teams/<int:team_pk>/sync/", views.team_sync, name="team_sync"),
    path("coach/assignments/<int:pk>/edit/", views.assignment_update, name="assignment_update"),
    path("coach/assignments/<int:pk>/delete/", views.assignment_delete, name="assignment_delete"),
    path("team/join/", views.team_join, name="team_join"),
    # Installed phone app only
    path("app/more/", app_views.more, name="app_more"),
    path("app/status.json", app_views.status, name="app_status"),
    path("app/offline-data.json", app_views.offline_data, name="app_offline_data"),
    path("app/push/subscribe/", app_views.push_subscribe, name="push_subscribe"),
    path("app/push/unsubscribe/", app_views.push_unsubscribe, name="push_unsubscribe"),
    path("app/push/test/", app_views.push_test, name="push_test"),
]
