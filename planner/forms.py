from django import forms

from .models import AcademicTask, Event, FlexibleRoutine


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class EventForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        choices=Event.WEEKDAYS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Repeat on",
    )

    class Meta:
        model = Event
        fields = [
            "event_type",
            "title",
            "date",
            "start_time",
            "end_time",
            "location",
            "repeat_weekly",
            "repeat_until",
            "notes",
        ]
        widgets = {
            "date": DateInput(),
            "start_time": TimeInput(format="%H:%M"),
            "end_time": TimeInput(format="%H:%M"),
            "repeat_until": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "date": "First date",
            "repeat_weekly": "Repeat every week",
            "repeat_until": "Repeat until (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs["placeholder"] = "Example: CSC 305 or Football practice"
        self.fields["location"].widget.attrs["placeholder"] = "Example: Fuller Hall"
        self.fields["notes"].widget.attrs["placeholder"] = "Anything else you want to remember"
        if self.instance.pk and not self.is_bound:
            self.initial["weekdays"] = [str(day) for day in sorted(self.instance.weekday_numbers)]

    def clean(self):
        cleaned_data = super().clean()
        selected_days = cleaned_data.get("weekdays", [])
        if cleaned_data.get("repeat_weekly") and not selected_days and cleaned_data.get("date"):
            selected_days = [str(cleaned_data["date"].weekday())]
        cleaned_data["weekdays"] = selected_days
        return cleaned_data

    def save(self, commit=True):
        event = super().save(commit=False)
        event.weekdays = ",".join(self.cleaned_data.get("weekdays", []))
        if commit:
            event.save()
            self.save_m2m()
        return event


class AcademicTaskForm(forms.ModelForm):
    class Meta:
        model = AcademicTask
        fields = [
            "task_type",
            "title",
            "course",
            "due_date",
            "estimated_minutes",
            "priority",
            "notes",
        ]
        widgets = {
            "due_date": DateTimeInput(format="%Y-%m-%dT%H:%M"),
            "estimated_minutes": forms.NumberInput(attrs={"min": 15, "step": 15}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"estimated_minutes": "Estimated work time (minutes)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs["placeholder"] = "Example: Merge sort assignment"
        self.fields["course"].widget.attrs["placeholder"] = "Example: CSC 305"
        self.fields["notes"].widget.attrs["placeholder"] = "Requirements, chapters, or reminders"

    def clean_estimated_minutes(self):
        minutes = self.cleaned_data["estimated_minutes"]
        if minutes < 15:
            raise forms.ValidationError("Enter at least 15 minutes.")
        if minutes > 1440:
            raise forms.ValidationError("Break work longer than 24 hours into smaller tasks.")
        return minutes


class FlexibleRoutineForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        choices=FlexibleRoutine.WEEKDAYS,
        widget=forms.CheckboxSelectMultiple,
        label="Days to schedule",
    )

    class Meta:
        model = FlexibleRoutine
        fields = [
            "title",
            "duration_minutes",
            "window_start",
            "window_end",
            "weekdays",
            "active",
            "notes",
        ]
        widgets = {
            "duration_minutes": forms.NumberInput(attrs={"min": 5, "max": 180, "step": 5}),
            "window_start": TimeInput(format="%H:%M"),
            "window_end": TimeInput(format="%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "duration_minutes": "Time needed each day (minutes)",
            "window_start": "Available from (optional)",
            "window_end": "Available until (optional)",
            "active": "Include this routine when generating plans",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs["placeholder"] = "Example: Bible study"
        self.fields["notes"].widget.attrs["placeholder"] = "Optional reminder or goal"
        self.fields["window_start"].help_text = "Leave both availability fields blank if any open time works."
        self.fields["window_end"].help_text = "Example: breakfast is available until 1:30 PM."
        if self.instance.pk and not self.is_bound:
            self.initial["weekdays"] = [str(day) for day in sorted(self.instance.weekday_numbers)]
        elif not self.is_bound:
            self.initial["weekdays"] = [str(day) for day in range(7)]

    def clean(self):
        cleaned_data = super().clean()
        selected_days = cleaned_data.get("weekdays", [])
        cleaned_data["weekdays"] = ",".join(selected_days)
        return cleaned_data

    def save(self, commit=True):
        routine = super().save(commit=False)
        routine.weekdays = self.cleaned_data["weekdays"]
        if commit:
            routine.save()
            self.save_m2m()
        return routine
