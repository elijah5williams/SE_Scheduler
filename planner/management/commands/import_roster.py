"""Bulk-create athlete and coach accounts from a roster CSV.

Each row puts one person on one team named "Assumption <Sport>".
The command can be run again safely: people and teams that already exist are
reused, not duplicated.

CSV columns (header row required):
    first_name, last_name, email, role, sport[, title]

    role   "athlete" or "coach" (also accepts "student", "head coach", "assistant coach")
    sport  e.g. "Football", "Women's Soccer" -> team "Assumption Football", "Assumption Women's Soccer"
    title  optional, coaches only, e.g. "Head Coach", "Defensive Coordinator".
           The coach titled Head Coach (or else the first coach listed) becomes the team's head coach.
"""
import csv
import secrets

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import Profile
from planner.roster import SCHOOL_DOMAIN, import_person, password_hash, team_name_for


ROLE_ALIASES = {
    "athlete": Profile.STUDENT,
    "student": Profile.STUDENT,
    "student-athlete": Profile.STUDENT,
    "coach": Profile.COACH,
    "head coach": Profile.COACH,
    "assistant coach": Profile.COACH,
}
REQUIRED_COLUMNS = {"first_name", "last_name", "email", "role", "sport"}


class Command(BaseCommand):
    help = "Create athlete and coach accounts from a roster CSV and group them into Assumption teams."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the roster CSV file.")
        parser.add_argument(
            "--send-invites",
            action="store_true",
            help="Email each new account a link to set their password.",
        )
        parser.add_argument(
            "--password",
            help="Give every account on the roster this password, so they can log in right away "
            "(handy for demos). Existing accounts on the roster are reset to it too.",
        )
        parser.add_argument(
            "--allow-other-domains",
            action="store_true",
            help=f"Accept emails that are not @{SCHOOL_DOMAIN}.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check the file and report what would happen without saving anything.",
        )

    def handle(self, *args, csv_path, send_invites, allow_other_domains, dry_run, password=None, **options):
        if password is not None and not password.strip():
            raise CommandError("--password cannot be blank.")
        if password and send_invites:
            raise CommandError("Use either --password or --send-invites, not both.")
        self.password = password
        self.hashed_password = password_hash(password)
        rows = self._read_rows(csv_path, allow_other_domains)

        stats = {"users_created": 0, "users_existing": 0, "teams_created": 0}
        new_users = []
        try:
            with transaction.atomic():
                for row in rows:
                    self._import_row(row, stats, new_users)
                if dry_run:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("Dry run: nothing was saved."))

        if send_invites and not dry_run:
            self._send_invites(new_users)

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(rows)} row(s) processed: {stats['users_created']} account(s) created, "
                f"{stats['users_existing']} already existed, {stats['teams_created']} team(s) created."
            )
        )
        if self.password and not dry_run:
            self.stdout.write(
                "Everyone on the roster can now log in with their username "
                "(the part of their email before the @) and the password you chose."
            )
        elif new_users and not send_invites and not dry_run:
            self.stdout.write(
                "New accounts have no password yet. Re-run with --send-invites, or have people use "
                "'Forgot password' on the login page with their school email."
            )

    def _read_rows(self, csv_path, allow_other_domains):
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                headers = {h.strip().lower() for h in (reader.fieldnames or [])}
                missing = REQUIRED_COLUMNS - headers
                if missing:
                    raise CommandError(f"Missing column(s): {', '.join(sorted(missing))}")
                raw_rows = [
                    {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                    for row in reader
                ]
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_path}")

        rows, errors, seen = [], [], set()
        for line, row in enumerate(raw_rows, start=2):
            if not any(row.values()):
                continue
            email = row["email"].lower()
            role = ROLE_ALIASES.get(row["role"].lower())
            if not all(row[c] for c in REQUIRED_COLUMNS):
                errors.append(f"line {line}: every column needs a value")
            elif "@" not in email:
                errors.append(f"line {line}: '{row['email']}' is not an email address")
            elif not allow_other_domains and email.rsplit("@", 1)[1] != SCHOOL_DOMAIN:
                errors.append(f"line {line}: {email} is not an @{SCHOOL_DOMAIN} address")
            elif role is None:
                errors.append(f"line {line}: role must be athlete or coach, not '{row['role']}'")
            elif (email, team_name_for(row["sport"])) in seen:
                errors.append(f"line {line}: {email} is listed twice for {row['sport']}")
            else:
                seen.add((email, team_name_for(row["sport"])))
                title = row.get("title", "")
                if not title and row["role"].lower() in {"head coach", "assistant coach"}:
                    title = row["role"].title()
                rows.append({**row, "email": email, "role": role, "title": title, "order": line})

        if errors:
            raise CommandError("Fix these rows and try again:\n  " + "\n  ".join(errors))
        return rows

    def _import_row(self, row, stats, new_users):
        import_person(row, stats, hashed_password=self.hashed_password, reset_password=True, new_users=new_users)

    def _send_invites(self, users):
        for user in users:
            # PasswordResetForm skips accounts with unusable passwords, so give each a random one first.
            user.set_password(secrets.token_urlsafe(24))
            user.save(update_fields=["password"])
            form = PasswordResetForm({"email": user.email})
            if form.is_valid():
                form.save(
                    domain_override=getattr(settings, "SITE_DOMAIN", "127.0.0.1:8000"),
                    use_https=False,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                )
        self.stdout.write(f"Sent {len(users)} set-your-password email(s).")


class _DryRun(Exception):
    pass
