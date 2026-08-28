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

## Set up the app on Windows

These instructions are written for someone who does not normally work with
Python or developer tools. Setup usually takes a few minutes and only needs to
be completed once.

### 1. Install Python

1. Download Python from <https://www.python.org/downloads/windows/>. Use Python
   3.11 or newer.
2. Open the downloaded installer.
3. On the first installer screen, select **Add python.exe to PATH**, and then
   choose **Install Now**.
4. Finish the installation before continuing.

You do not need to install a separate database. The app uses SQLite, which is
included with Python.

### 2. Download and open the project folder

1. Open the project's GitHub page:
   <https://github.com/ebrooksbgc/time_tracker_bgc>.
2. Select the green **Code** button, and then select **Download ZIP**.
3. Open your Downloads folder, right-click the downloaded ZIP file, and select
   **Extract All**.
4. Open the extracted `time_tracker_bgc` folder. Confirm that you can see
   `app.py` and `requirements.txt` in it.
5. Click the File Explorer address bar, type `powershell`, and press **Enter**.
   A blue PowerShell window will open in the correct folder.

Keep the project in this folder after setup. The app saves its local data there.

### 3. Install the app

Copy each command below into the PowerShell window and press **Enter** after
each one. Let each command finish before starting the next command.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The installation may take a few minutes. Lines of text appearing in the window
are normal.

### 4. Start the app

In the same PowerShell window, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Your browser should open the Time Tracker automatically. If it does not, open
<http://localhost:8501> yourself. Keep the PowerShell window open while using
the app. Closing it stops the app.

On first launch, the application creates a local `time_tracker.db` file in the
project folder. This file contains the information saved in your local copy of
the app.

### 5. Import the example partners and projects

1. In the web app, select **Setup** from the main navigation.
2. Under **Reference data**, click **Import official hackathon workbook**.
3. Wait for the import summary to appear. It will report the partners,
   projects, tasks, assignments, and fiscal periods that were added.
4. Select an example partner from **Work as partner** and begin using the app.

The button imports data from `IT Hackathon Workbook.xlsx`, which is already in
the project folder. You do not need to open or upload the workbook yourself.

## Start the app again later

1. Open the extracted `time_tracker_bgc` folder in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**.
3. Run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The app will use the same local database, so previously saved work will still
be available. To stop the app, close the PowerShell window or press **Ctrl+C**
in that window.

## Common setup problems

- **`py` is not recognized:** Restart the computer after installing Python. If
  the problem continues, reinstall Python and select **Add python.exe to PATH**.
- **PowerShell says that `requirements.txt` or `app.py` cannot be found:** The
  PowerShell window is open in the wrong folder. Return to the folder containing
  `app.py`, type `powershell` in its File Explorer address bar, and try again.
- **The browser does not open:** Keep PowerShell running and open
  <http://localhost:8501> in a browser.
- **The page says it cannot connect:** Start the app with the command in
  **Start the app again later** and leave the PowerShell window open.
- **The workbook cannot be found:** Confirm that
  `IT Hackathon Workbook.xlsx` is still in the same folder as `app.py`.

## macOS or Linux setup

Open a terminal and run:

```bash
git clone https://github.com/ebrooksbgc/time_tracker_bgc.git
cd time_tracker_bgc
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Open <http://localhost:8501> if the browser does not open automatically. Then
follow **Import the example partners and projects** above.

## Using the app

1. Select a partner from **Work as partner**.
2. Use **My week** to add project/task rows and enter time in quarter-hour
   increments.
3. Save work in progress, then submit the week when it is complete.
4. Use **Timer** for live capture or **Setup** to manage employees, projects,
   tasks, and assignments.
5. Review summaries in **Insights** and prior entries in **History**.

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
