from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("planner", "0003_flexibleroutine_routinesession"),
    ]

    operations = [
        migrations.AddField(
            model_name="flexibleroutine",
            name="window_end",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="flexibleroutine",
            name="window_start",
            field=models.TimeField(blank=True, null=True),
        ),
    ]
