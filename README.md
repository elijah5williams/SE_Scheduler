# Athlete Academic Assistant

An AI-assisted academic planning website built with Django for college student-athletes. It combines classes, practices, games, assignments, exams, and automatically generated study sessions in one schedule.

## Features

- Dashboard with today's commitments, their known start/end times, and upcoming academic work
- Add, edit, and delete classes, practices, games, workouts, meetings, and other events
- Weekly repeating events on one or multiple selected weekdays
- A dedicated schedule-management section with clear edit and delete controls
- Course cleanup that removes dropped-class assignments and generated study sessions together
- Add and manage assignments, exams, projects, readings, and other tasks
- Seven-day combined academic and athletic schedule
- Smart study planner that prioritizes deadlines and finds open time around commitments
- Two-week calendar planner that groups each day’s classes, athletics, study blocks, and deadlines
- Flexible routines that are automatically placed into open time (for example, 20 minutes of Bible study each day)
- Optional availability windows for flexible items (for example, schedule a 25-minute breakfast between 11:00 AM and 1:30 PM)
- Mark assignments and study sessions complete
- Responsive design for laptop and mobile screens
- Django admin panel
- Automated tests

## Run the project in VS Code

1. Open the `SE_scheduler` folder in VS Code.
2. Open **Terminal > New Terminal**.
3. Create a virtual environment:

   Windows:

   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```

   macOS/Linux:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install the requirements:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Set up the database:

   ```bash
   python manage.py migrate
   ```

6. Start the website:

   ```bash
   python manage.py runserver
   ```

7. Open `http://127.0.0.1:8000/` in a browser.

## Load presentation-ready demo data

To replace the current planner data with a realistic student-athlete week, run:

```bash
python manage.py load_demo
```

Then refresh the website. This is useful when demonstrating the project in class. The command intentionally replaces existing schedule and assignment data, so only use it when you want the demo setup.

## Create accounts for Assumption athletes and coaches

Instead of everyone signing up one by one, you can create every athlete and coach account from a roster spreadsheet. Each person is placed on a team named after their sport, such as **Assumption Football** or **Assumption Women's Soccer**.

1. Copy `rosters/assumption_roster_template.csv` and fill in one row per person:

   | first_name | last_name | email | role | sport | title |
   |---|---|---|---|---|---|
   | Jane | Doe | jdoe@assumption.edu | athlete | Football | |
   | John | Smith | jsmith@assumption.edu | coach | Football | Head Coach |
   | Ana | Ruiz | aruiz@assumption.edu | coach | Football | Defensive Coordinator |

   - `role` is `athlete` or `coach` (`head coach` and `assistant coach` also work).
   - `sport` becomes the team name, with "Assumption" added in front.
   - `title` is optional and only used for coaches. Every coach joins the team's coaching staff with that title. The coach titled "Head Coach" (or else the first coach listed) is the head coach.
   - Someone on two teams gets one row per team.
   - Emails must be `@assumption.edu`. Pass `--allow-other-domains` to skip this check.

2. Check the file without saving anything:

   ```bash
   python manage.py import_roster rosters/my_roster.csv --dry-run
   ```

3. Import it, emailing everyone a link to set their password:

   ```bash
   python manage.py import_roster rosters/my_roster.csv --send-invites
   ```

   For a class demo, skip the emails and give every account the same password instead:

   ```bash
   python manage.py import_roster rosters/my_roster.csv --password greyhounds
   ```

   Everyone can then log in with their username (the part of their email before the `@`, such as `jane.doe`) and that password. Running it again with `--password` resets everyone on the roster to the new password.

Accounts are created already verified, because the roster replaces the email and admin checks. Every coach on the roster can see the team on their coach dashboard and assign practices, workouts and games. Athletes are added to the team and receive any plans the coach has already assigned. You can run the command again with an updated roster: existing people and teams are reused, not duplicated. Teams can be reviewed or edited under **Teams** in the Django admin.

Keep real rosters out of git, because they contain student information. `rosters/*.csv` is ignored, except for the template.

## Every Assumption team from the athletics website

One command builds every team listed on assumptiongreyhounds.com. Each team gets its athletes, its coaches with their titles, and its live schedule:

```bash
python3 manage.py sync_athletics --password greyhounds
```

- **Emails:** accounts use first.last@assumption.edu. Someone on two teams, such as cross country and track, gets one account on both.
- **Password:** `--password` applies to new accounts only. People who already exist keep their password.
- **Re-running:** run it again any time to pick up roster changes. To update just some sports, name them, e.g. `python3 manage.py sync_athletics football mens-basketball`.
- **On Render:** the deploy runs this automatically.

## Live game schedule, scores and season record

A team's games can come straight from its page on the athletics website. Link the team once:

```bash
python3 manage.py sync_schedule "Assumption Football" https://assumptiongreyhounds.com/sports/football/schedule
```

That puts every game on every athlete's schedule. After that the app keeps itself current. When someone opens their dashboard, schedule or coach dashboard, it re-checks the website if it hasn't in the last hour, or the last 10 minutes on game day. Final scores, time or venue changes and cancelled games then reach every athlete. Coaches can also press **Sync schedule** on their dashboard, or you can run `python3 manage.py sync_schedule` to refresh every linked team.

The dashboards show a game-day panel with a live countdown to the next game, both teams' logos, the latest scores and the season record (Overall, Conf, Streak, Home, Away and so on). Games from the website show "From website" on the coach dashboard instead of Edit and Delete, because the next sync would overwrite any changes.

## Put the site online (Render)

The repo includes `render.yaml`, which sets up the website and a free Postgres database on [Render](https://render.com). Every push to `main` redeploys the site.

1. Sign in to Render with GitHub, then choose **New + → Blueprint** and pick this repository.
2. Render asks for these values. Fill them in, then click **Apply**:
   - `ROSTER_PASSWORD`: the password every roster account gets, e.g. `greyhounds`
   - `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`: your login for `/admin`
3. To load the roster without putting student information on GitHub, open the **se-scheduler** service, go to **Environment → Secret Files**, add a file named `football.csv` and paste in the roster. Then click **Manual Deploy → Deploy latest commit**. Each deploy imports the roster and links the football schedule.
4. Your site is at the `https://se-scheduler-….onrender.com` address shown at the top of the service page.

### Sending real email

Sign-up verification and "Forgot password?" links need a real email service. Without one, emails only print to the server log. With a free [Brevo](https://www.brevo.com) account:

1. In Brevo, go to **SMTP & API** and create an SMTP key. Under **Senders**, add and verify the address you'll send from.
2. In Render, open **se-scheduler → Environment** and set:
   - `EMAIL_HOST` = `smtp-relay.brevo.com`
   - `EMAIL_HOST_USER` = your Brevo SMTP login
   - `EMAIL_HOST_PASSWORD` = the SMTP key
   - `DEFAULT_FROM_EMAIL` = `Athlete Academic Assistant <the-sender-you-verified@example.com>`
3. Save. Render redeploys, and emails start sending.

### Backing up the live database

Render's free Postgres database can expire, so check its expiry date on the **se-scheduler-db** page in Render. Teams, rosters, coaching staff, schedules and login photos are rebuilt from the athletics website on every deploy. Only what people add themselves needs a backup: classes, assignments, study plans, routines, coach-assigned practices and changed passwords.

To make a backup from your laptop:

1. In Render, open **se-scheduler-db → Info** and copy the **External Database URL**.
2. In your project folder, run this, pasting the URL in place of `PASTE_URL_HERE`:

   ```bash
   DATABASE_URL="PASTE_URL_HERE" python3 manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry --indent 2 -o backup.json
   ```

   `backup.json` holds real people's data. Keep it on your computer and don't commit it; `.gitignore` already skips it.

To restore into a new, empty database (for example after recreating it on Render):

```bash
DATABASE_URL="NEW_URL_HERE" python3 manage.py migrate
```

```bash
DATABASE_URL="NEW_URL_HERE" python3 manage.py loaddata backup.json
```

On the free plan the site sleeps after a while without visitors, so the first visit afterwards takes about 30 seconds.

## Run the tests

```bash
python manage.py test
```

## How the smart planner works

The planner uses built-in scheduling intelligence, so it works without a paid API key. It ranks incomplete work by deadline and priority, checks the student's class and athletic commitments, finds open blocks between 8:00 AM and 10:00 PM, and creates study sessions of up to 90 minutes. Regenerating a plan replaces only unfinished generated sessions; completed sessions remain in the history.

## Main project files

- `planner/models.py` — database structure
- `planner/views.py` — page behavior
- `planner/services.py` — study-planning logic
- `planner/forms.py` — event and assignment forms
- `planner/templates/` — page layouts
- `planner/static/` — design and browser behavior

## Install it as a phone app

The site is an installable web app, so athletes can put it on their home screen like any other app. It opens full screen with its own icon, and shows a friendly page when there's no connection.

- **iPhone (Safari):** open the site, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open the site, tap **⋮**, then **Install app** (or accept the install banner).
- **Laptop (Chrome/Edge):** click the install icon in the address bar.

Installing needs HTTPS, which Render provides. The app files are in `planner/pwa.py` (manifest, service worker, offline page) and `planner/static/planner/icons/`. Schedule pages are never saved on the phone, because they hold private data. After you change `planner/templates/planner/sw.js` or the offline page, bump `CACHE_VERSION` in `planner/pwa.py` so phones pick up the new version.
