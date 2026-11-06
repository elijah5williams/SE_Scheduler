from django.core.management.base import BaseCommand, CommandError

from planner.models import Team
from planner.schedule_sync import ScheduleError, sync_team


class Command(BaseCommand):
    help = (
        "Pull games from a team's athletics-website schedule onto every athlete's schedule. "
        "With no arguments, syncs every team that has a schedule link."
    )

    def add_arguments(self, parser):
        parser.add_argument("team", nargs="?", help='Team name, e.g. "Assumption Football".')
        parser.add_argument("url", nargs="?", help="Schedule page to save for the team (only needed the first time).")

    def handle(self, *args, team=None, url=None, **options):
        if team:
            try:
                teams = [Team.objects.get(name__iexact=team)]
            except Team.DoesNotExist:
                raise CommandError(f"No team named '{team}'. Import the roster first.")
            if url:
                teams[0].schedule_url = url
                teams[0].save(update_fields=["schedule_url"])
        else:
            teams = list(Team.objects.exclude(schedule_url=""))
            if not teams:
                raise CommandError('No team has a schedule link yet. Run: sync_schedule "Assumption Football" <url>')

        for t in teams:
            try:
                counts = sync_team(t)
            except ScheduleError as exc:
                raise CommandError(f"{t.name}: {exc}")
            self.stdout.write(
                self.style.SUCCESS(
                    f"{t.name}: {counts['added']} added, {counts['updated']} updated, {counts['removed']} removed "
                    f"({t.assignments.exclude(external_id='').count()} games, {t.athletes.count()} athletes)."
                )
            )
