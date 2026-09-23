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
