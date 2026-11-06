from django.core.management.base import BaseCommand, CommandError

from planner.athletics import discover_sports, sync_sport
from planner.roster import password_hash
from planner.schedule_sync import ScheduleError


class Command(BaseCommand):
    help = (
        "Create every Assumption team from assumptiongreyhounds.com: athlete and coach accounts "
        "(first.last@assumption.edu), coaching staff titles, and each team's live schedule."
    )

    def add_arguments(self, parser):
        parser.add_argument("sports", nargs="*", help="Only these sports, by website slug (e.g. mens-basketball).")
        parser.add_argument(
            "--password",
            help="Password for NEW accounts so they can log in right away. Existing accounts keep theirs.",
        )
        parser.add_argument("--no-schedules", action="store_true", help="Only rosters, skip schedules.")

    def handle(self, *args, sports, password=None, no_schedules=False, **options):
        slugs = sports or discover_sports()
        hashed = password_hash(password)
        totals = {"teams": 0, "people": 0, "new": 0, "games": 0}
        for slug in slugs:
            try:
                s = sync_sport(slug, hashed_password=hashed, with_schedule=not no_schedules)
            except ScheduleError as exc:
                if "404" in str(exc):
                    self.stdout.write(f"{slug}: no roster page yet, skipped")
                else:
                    self.stdout.write(self.style.WARNING(f"{slug}: could not read roster ({exc})"))
                continue
            if s["skipped"] == "no roster posted":
                self.stdout.write(f"{s['sport']}: no roster posted yet, skipped")
                continue
            totals["teams"] += 1
            totals["people"] += s["athletes"] + s["coaches"]
            totals["new"] += s["users_created"]
            totals["games"] += s["games"]
            note = f" ({s['skipped']})" if s["skipped"] else ""
            self.stdout.write(
                f"{s['sport']}: {s['athletes']} athletes, {s['coaches']} coaches, {s['games']} events{note}"
            )
        if not totals["teams"]:
            raise CommandError("No teams were imported. Is assumptiongreyhounds.com reachable?")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {totals['teams']} teams, {totals['people']} roster spots, "
                f"{totals['new']} new accounts, {totals['games']} scheduled events."
            )
        )
