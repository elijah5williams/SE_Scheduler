from django.urls import path

from . import views


app_name = "planner"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
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
]
