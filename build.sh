#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Admin login for /admin, from the DJANGO_SUPERUSER_* environment variables (skipped if not set or already exists).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --no-input || true
fi

# Every Assumption team, roster, coaching staff and schedule, read from assumptiongreyhounds.com.
# New accounts get ROSTER_PASSWORD; people who already exist keep their password.
python manage.py sync_athletics --password "${ROSTER_PASSWORD:-greyhounds}" || echo "Athletics sync failed; schedules still refresh when people open the site."

# Optional extra roster from a Render "Secret File" (e.g. corrections), kept off GitHub.
if [ -f /etc/secrets/football.csv ]; then
  python manage.py import_roster /etc/secrets/football.csv --password "${ROSTER_PASSWORD:-greyhounds}"
fi
