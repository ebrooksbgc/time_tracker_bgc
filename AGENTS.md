# Time Tracker agent guidance

This repository is a Python 3 Streamlit application backed by SQLModel and
SQLite. For any work that changes the UI, Streamlit execution model, widget
state, forms, caching, navigation, or app startup, read and follow
`.agents/skills/developing-with-streamlit/SKILL.md` before editing. Follow its
reference-routing instructions and load the relevant official reference files.

## Repository map

- `app.py`: Streamlit presentation layer and page orchestration.
- `services.py`: business rules and application operations.
- `models.py`: SQLModel table definitions.
- `database.py`: engine, sessions, initialization, and migrations.
- `time_utils.py`: timezone and reporting-boundary helpers.
- `tests/`: pytest coverage; tests must not use the repository database.

## Working rules

- Keep business logic out of `app.py`; add it to `services.py` and cover it
  with unit tests.
- Preserve Streamlit's top-to-bottom rerun model. Store only UI workflow state
  in `st.session_state`; persist domain state through the service/database
  layer.
- Give every repeated or dynamic widget an explicit, stable, unique key.
- Cache only safe resources or immutable/read-only data. Never cache a mutable
  SQLModel session or user-specific result globally.
- Use `Decimal` or integer quarter-hours for time and money calculations rather
  than relying on binary floating-point equality.
- Keep timestamps in UTC internally and convert through `time_utils.py` at the
  display/reporting boundary.
- Do not modify or delete `time_tracker.db` during development or tests.
- Preserve unrelated user changes in the worktree.

## Verification

Run the narrowest relevant test first, then the full suite before handoff:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

For UI changes, also start the app and check that it reaches a healthy state:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```
