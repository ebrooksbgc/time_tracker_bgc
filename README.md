# Time Tracker

A Streamlit employee-timesheet application built with Python, SQLModel, and
SQLite for the BGC AI Hackathon Time Tracking Build Challenge. It combines
weekly time entry, timer-based capture, financial classification, reporting,
and fiscal-period controls in one local application.

The primary **My week** view includes:

- Business area → project → task rows with quarter-hour entry
- Explicit project and non-project coding
- Task-code-driven CapEx/OpEx classification; non-project time is always OpEx
- Monday–Sunday entry, daily totals, and weekly completion
- Expected-hours and missing-day guidance
- Project/task notes for distinct workstreams
- Explicit row creation from project/task dropdowns
- Multiple rows for the same project/task when notes differ
- Copy-previous-week, clear-week, save, submit, and recall actions
- Submitted-week editing protection

The supporting views include a stopwatch, employee and project/task setup,
weekly completion and work-distribution insights, CapEx/OpEx and project/support
reporting, a transparent classification helper, fiscal-period correction and
locking, date-aware history, safe deletion, and CSV export. Timer entries feed
the same weekly timesheet. Timestamps are
stored in UTC and displayed in the configured local timezone; entries that
cross midnight are split correctly in reports.

## Requirements

- Python 3.11 or newer
- A supported desktop browser

SQLite is included with Python, so no separate database service is required for
local use.

## Quick start

### Windows PowerShell

```powershell
git clone git@github.com:ebrooksbgc/time_tracker_bgc.git
cd time_tracker
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### macOS or Linux

```bash
git clone git@github.com:ebrooksbgc/time_tracker_bgc.git
cd time_tracker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the URL printed by Streamlit, normally <http://localhost:8501>.

On first launch, the application creates a local `time_tracker.db` file and
seeds the minimum data needed to use the app. The database is intentionally
excluded from Git.

To load the example data, open **Setup** in the web app and click
**Import official hackathon workbook**. This imports the example partners,
projects, and other reference data from the included workbook.

## Using the app

1. Select a partner from **Work as partner**.
2. Use **My week** to add project/task rows and enter time in quarter-hour
   increments.
3. Save work in progress, then submit the week when it is complete.
4. Use **Timer** for live capture or **Setup** to manage employees, projects,
   tasks, and assignments.
5. Review summaries in **Insights** and prior entries in **History**.

The **Import official hackathon workbook** action uses
`IT Hackathon Workbook.xlsx`, which is included as a runtime asset in this
repository.

## Tests

Tests use isolated temporary databases and do not modify `time_tracker.db`.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### macOS or Linux

```bash
python -m pytest
```

The suite covers the Streamlit shell, employee and classified task setup, weekly
save/copy/submit/recall behavior, editing locks, service validation,
timer/database constraints, foreign keys, date-range clipping,
daylight-saving transitions, financial classification, accounting-period
transitions, and destructive operations.

## Hackathon classification rules

- Every task code has a `CapEx` or `OpEx` classification.
- Every hour inherits the classification of the selected task code.
- Non-project categories are forced to `OpEx`, even if a caller requests `CapEx`.
- The setup helper can suggest a classification from task wording, but a person
  remains responsible for the final project-task classification.

## Fiscal period close

Create periods from the provided FY26/FY27 calendar in **Period close**. Periods
follow `Open → Correction → Locked`. A correction period requires a deadline;
after that deadline, edits are rejected. Locked periods cannot be reopened or
edited.

## Configuration

The default display timezone is `America/Chicago`. Override it before launch
with any IANA timezone name:

```powershell
$env:TIME_TRACKER_TIMEZONE = "America/New_York"
python -m streamlit run app.py
```

On macOS or Linux:

```bash
export TIME_TRACKER_TIMEZONE='America/New_York'
python -m streamlit run app.py
```

Existing databases are migrated from local wall-clock timestamps to UTC once.
Keep `TIME_TRACKER_TIMEZONE` set to the timezone in which the old entries were
recorded during that first upgraded launch.

## Structure

| Path | Purpose |
| --- | --- |
| `app.py` | Streamlit presentation and page orchestration |
| `services.py` | Timesheet, timer, reporting, and validation rules |
| `models.py` | SQLModel database tables and constraints |
| `database.py` | Engine, sessions, initialization, and migrations |
| `time_utils.py` | UTC/local-time conversion and report boundaries |
| `reference_import.py` | Official workbook import logic |
| `timesheet_grid.py` | Interactive weekly entry grid component |
| `tests/` | Automated tests using isolated databases |
| `.streamlit/config.toml` | Shared light and dark theme settings |

## Using PostgreSQL later

The application reads its database URL from `TIME_TRACKER_DATABASE_URL`. After
installing a PostgreSQL driver, point it at a PostgreSQL database before launch:

```powershell
$env:TIME_TRACKER_DATABASE_URL = "postgresql+psycopg://user:password@localhost/time_tracker"
python -m streamlit run app.py
```

Install a compatible PostgreSQL driver separately before using that URL. For a
hackathon demo, SQLite requires no service setup and keeps all data in one local
file.

## Data and security notes

- Local SQLite databases, `.env` files, Streamlit secrets, caches, and virtual
  environments are excluded by `.gitignore`.
- Do not commit real employee timesheets, credentials, or production database
  exports.
- Timestamps are stored in UTC and converted only at display/reporting
  boundaries.

## License

No license has been specified. Add one before publishing if others should be
allowed to reuse or redistribute the project.
