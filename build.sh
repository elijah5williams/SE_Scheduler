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

# Roster: upload football.csv as a Render "Secret File" so student info never goes on GitHub.
if [ -f /etc/secrets/football.csv ]; then
  python manage.py import_roster /etc/secrets/football.csv --password "${ROSTER_PASSWORD:-greyhounds}"
  python manage.py sync_schedule "Assumption Football" https://assumptiongreyhounds.com/sports/football/schedule || echo "Schedule sync failed; it will retry when someone opens the site."
fi
