from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from models import Employee, TimeEntry
from services import (
    accounting_period_for,
    active_timer,
    add_favorite,
    add_manual_entry,
    clear_week,
    copy_previous_week,
    create_accounting_period,
    create_project,
    create_task,
    deactivate_employee,
    deactivate_project,
    delete_entry,
    delete_project,
    delete_week_row,
    duration_between,
    entry_date_bounds,
    entries_between,
    expected_hours_for_week,
    fiscal_week_start,
    get_employee,
    get_timesheet,
    list_accounting_periods,
    list_favorites,
    list_projects,
    list_tasks,
    observed_company_holidays,
    project_entry_count,
    recall_timesheet,
    reactivate_employee,
    reactivate_project,
    remove_favorite,
    set_daily_task_hours,
    set_accounting_period_status,
    seed_published_fiscal_calendar,
    start_timer,
    stop_timer,
    submit_timesheet,
    submission_deadline,
    suggest_expense_type,
    update_employee,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_start_and_stop_timer(session: Session) -> None:
    project = create_project(session, "Hackathon", "Demo Client")
    started = datetime(2026, 8, 27, 9, 0)
    stopped = datetime(2026, 8, 27, 10, 30)

    entry = start_timer(session, project.id, "Build MVP", started_at=started)
    assert active_timer(session).id == entry.id

    finished = stop_timer(session, ended_at=stopped)
    assert finished.duration_seconds == 5400
    assert active_timer(session) is None


def test_favorite_can_be_added_and_removed(session: Session) -> None:
    employee = get_employee(session)
    project = create_project(session, "Favorite project")
    task = create_task(session, project.id, "Favorite task")

    add_favorite(session, employee.id, project.id, task.id)
    assert [(item.project_id, item.task_id) for item in list_favorites(session, employee.id)] == [
        (project.id, task.id)
    ]

    assert remove_favorite(session, employee.id, project.id, task.id) is True
    assert list_favorites(session, employee.id) == []
    assert remove_favorite(session, employee.id, project.id, task.id) is False


def test_only_one_timer_can_run(session: Session) -> None:
    project = create_project(session, "Hackathon")
    start_timer(session, project.id)

    with pytest.raises(ValueError, match="Stop the active timer"):
        start_timer(session, project.id)


def test_manual_entry_and_date_filter(session: Session) -> None:
    project = create_project(session, "Research")
    entry = add_manual_entry(
        session,
        project.id,
        date(2026, 8, 27),
        time(13, 15),
        45,
        "Compare frameworks",
    )

    assert entry.duration_seconds == 2700
    assert entries_between(session, date(2026, 8, 27), date(2026, 8, 27)) == [entry]
    assert entry_date_bounds(session) == (date(2026, 8, 27), date(2026, 8, 27))


def test_project_with_entries_is_archived_not_hard_deleted(session: Session) -> None:
    project = create_project(session, "Disposable")
    add_manual_entry(
        session,
        project.id,
        date(2026, 8, 27),
        time(9),
        30,
    )
    assert project_entry_count(session, project.id) == 1

    delete_project(session, project.id)
    assert project_entry_count(session, project.id) == 1
    archived = list_projects(session, active_only=False)[0]
    assert archived.active is False
    assert archived.status == "Inactive"


def test_project_without_entries_is_deactivated_not_hard_deleted(
    session: Session,
) -> None:
    project = create_project(session, "Unused project")

    deactivate_project(session, project.id)

    preserved = session.get(type(project), project.id)
    assert preserved is not None
    assert preserved.active is False
    assert preserved.status == "Inactive"

    reactivate_project(session, project.id)
    restored = session.get(type(project), project.id)
    assert restored.active is True
    assert restored.status == "Active"


def test_partner_deactivation_preserves_existing_entries(session: Session) -> None:
    partner = get_employee(session)
    session.add(Employee(name="Remaining partner", partner_id="EMP-REMAIN"))
    session.commit()
    project = create_project(session, "Historical project")
    entry = add_manual_entry(
        session,
        project.id,
        date(2026, 8, 27),
        time(9),
        60,
        employee_id=partner.id,
    )

    deactivate_employee(session, partner.id)

    preserved_partner = session.get(Employee, partner.id)
    assert preserved_partner is not None
    assert preserved_partner.active is False
    assert session.get(TimeEntry, entry.id) is not None

    reactivate_employee(session, partner.id)
    restored_partner = session.get(Employee, partner.id)
    assert restored_partner.active is True
    assert session.get(TimeEntry, entry.id) is not None


def test_project_with_running_timer_cannot_be_deleted(session: Session) -> None:
    project = create_project(session, "Running")
    start_timer(session, project.id)

    with pytest.raises(ValueError, match="Stop this project's active timer"):
        delete_project(session, project.id, delete_entries=True)


@pytest.mark.parametrize(
    ("name", "client", "message"),
    [
        ("", "", "required"),
        ("x" * 101, "", "100 characters"),
        ("Project", "x" * 101, "100 characters"),
    ],
)
def test_project_validation(
    session: Session, name: str, client: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_project(session, name, client)


def test_inactive_project_cannot_start_timer(session: Session) -> None:
    project = create_project(session, "Archived")
    project.active = False
    session.add(project)
    session.commit()

    with pytest.raises(ValueError, match="inactive"):
        start_timer(session, project.id)


def test_database_enforces_one_active_timer(session: Session) -> None:
    first = create_project(session, "First")
    second = create_project(session, "Second")
    employee = get_employee(session)
    session.add_all(
        [
            TimeEntry(
                employee_id=employee.id,
                project_id=first.id,
                started_at=datetime(2026, 1, 1),
            ),
            TimeEntry(
                employee_id=employee.id,
                project_id=second.id,
                started_at=datetime(2026, 1, 2),
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_partner_timesheets_entries_and_timers_are_isolated(session: Session) -> None:
    first_employee = Employee(name="First partner", partner_id="EMP-A")
    second_employee = Employee(name="Second partner", partner_id="EMP-B")
    session.add_all([first_employee, second_employee])
    session.commit()
    session.refresh(first_employee)
    session.refresh(second_employee)
    project = create_project(session, "Shared project")
    task = list_tasks(session, project.id)[0]
    day = date(2026, 8, 27)

    set_daily_task_hours(
        session, project.id, task.id, day, 2, employee_id=first_employee.id
    )
    set_daily_task_hours(
        session, project.id, task.id, day, 3, employee_id=second_employee.id
    )

    first_entries = entries_between(
        session, day, day, employee_id=first_employee.id
    )
    second_entries = entries_between(
        session, day, day, employee_id=second_employee.id
    )
    assert [entry.duration_seconds for entry in first_entries] == [7200]
    assert [entry.duration_seconds for entry in second_entries] == [10800]
    assert get_timesheet(session, day, first_employee.id).id != get_timesheet(
        session, day, second_employee.id
    ).id

    start_timer(session, project.id, employee_id=first_employee.id)
    start_timer(session, project.id, employee_id=second_employee.id)
    assert active_timer(session, first_employee.id).employee_id == first_employee.id
    assert active_timer(session, second_employee.id).employee_id == second_employee.id


def test_foreign_keys_are_enforced(session: Session) -> None:
    session.add(TimeEntry(project_id=999, started_at=datetime(2026, 1, 1)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_entry_spanning_midnight_is_clipped_to_each_day(session: Session) -> None:
    project = create_project(session, "Overnight")
    entry = add_manual_entry(
        session, project.id, date(2026, 8, 27), time(23, 30), 120
    )

    assert entry in entries_between(session, date(2026, 8, 28), date(2026, 8, 28))
    assert duration_between(entry, date(2026, 8, 27), date(2026, 8, 27)) == 1800
    assert duration_between(entry, date(2026, 8, 28), date(2026, 8, 28)) == 5400
    assert entry_date_bounds(session) == (date(2026, 8, 27), date(2026, 8, 28))


def test_manual_duration_stays_exact_across_dst(session: Session) -> None:
    project = create_project(session, "DST")
    entry = add_manual_entry(
        session, project.id, date(2026, 3, 8), time(1, 30), 120
    )
    assert entry.duration_seconds == 7200


def test_reversed_date_range_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="start date"):
        entries_between(session, date(2026, 2, 2), date(2026, 2, 1))


def test_delete_missing_entry_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_entry(session, 999)


def test_project_gets_general_task_and_accepts_more_tasks(session: Session) -> None:
    project = create_project(session, "Client delivery")
    assert [task.name for task in list_tasks(session, project.id)] == ["General"]
    create_task(session, project.id, "Development")
    assert [task.name for task in list_tasks(session, project.id)] == [
        "Development",
        "General",
    ]


def test_task_classification_and_non_project_rule(session: Session) -> None:
    project = create_project(session, "New platform", work_type="Project")
    capital_task = create_task(session, project.id, "Build application", "CapEx")
    assert capital_task.expense_type == "CapEx"

    support = create_project(session, "Meetings", work_type="Non-project")
    support_task = create_task(session, support.id, "Team meeting", "CapEx")
    assert support_task.expense_type == "OpEx"
    assert suggest_expense_type("Develop new system")[0] == "CapEx"
    assert suggest_expense_type("Training", "Non-project")[0] == "OpEx"


def test_locked_accounting_period_blocks_edits(session: Session) -> None:
    project = create_project(session, "Close test")
    task = list_tasks(session, project.id)[0]
    period = create_accounting_period(
        session, "FY26 P01", date(2026, 8, 1), date(2026, 8, 31)
    )
    set_accounting_period_status(session, period.id, "Correction", date(2026, 9, 2))
    assert period.status == "Correction"
    assert get_timesheet(session, date(2026, 8, 24)).status == "In Correction"
    set_accounting_period_status(session, period.id, "Locked")
    assert get_timesheet(session, date(2026, 8, 24)).status == "Locked"

    with pytest.raises(ValueError, match="locked"):
        set_daily_task_hours(
            session, project.id, task.id, date(2026, 8, 24), 1
        )
    with pytest.raises(ValueError, match="Open → Correction → Locked"):
        set_accounting_period_status(session, period.id, "Open")


def test_accounting_periods_cannot_overlap(session: Session) -> None:
    create_accounting_period(
        session, "FY26 P01", date(2026, 8, 1), date(2026, 8, 31)
    )
    with pytest.raises(ValueError, match="overlap"):
        create_accounting_period(
            session, "Overlap", date(2026, 8, 31), date(2026, 9, 15)
        )


def test_employee_profile_and_weekly_timesheet_workflow(session: Session) -> None:
    employee = update_employee(session, "Morgan", "Engineering", "Alex", 40)
    assert get_employee(session).id == employee.id
    assert employee.expected_weekly_hours == Decimal("40.00")

    project = create_project(session, "Hackathon")
    task = create_task(session, project.id, "Build prototype")
    monday = date(2026, 8, 24)
    set_daily_task_hours(session, project.id, task.id, monday, 7.5, "Core build")
    entries = entries_between(session, monday, monday)
    assert len(entries) == 1
    assert entries[0].duration_seconds == 27_000
    assert entries[0].task_id == task.id

    timesheet = submit_timesheet(session, monday)
    assert timesheet.status == "Submitted"
    with pytest.raises(ValueError, match="submitted"):
        set_daily_task_hours(session, project.id, task.id, monday, 8)
    with pytest.raises(ValueError, match="submitted"):
        delete_entry(session, entries[0].id)

    assert recall_timesheet(session, monday).status == "In Progress"
    set_daily_task_hours(session, project.id, task.id, monday, 8)
    assert get_timesheet(session, monday).status == "In Progress"


def test_copy_previous_week_skips_existing_cells(session: Session) -> None:
    project = create_project(session, "Recurring")
    task = list_tasks(session, project.id)[0]
    prior_monday = date(2026, 8, 17)
    current_monday = date(2026, 8, 24)
    set_daily_task_hours(session, project.id, task.id, prior_monday, 4)

    assert copy_previous_week(session, current_monday) == 1
    assert copy_previous_week(session, current_monday) == 0
    copied = entries_between(session, current_monday, current_monday)
    assert len(copied) == 1
    assert copied[0].duration_seconds == 14_400


def test_same_task_supports_multiple_note_rows_and_clear_week(
    session: Session,
) -> None:
    project = create_project(session, "Multiple workstreams")
    task = list_tasks(session, project.id)[0]
    monday = date(2026, 8, 24)

    set_daily_task_hours(
        session,
        project.id,
        task.id,
        monday,
        2,
        "Prototype",
        match_description="Prototype",
    )
    set_daily_task_hours(
        session,
        project.id,
        task.id,
        monday,
        1.5,
        "Team meeting",
        match_description="Team meeting",
    )
    entries = entries_between(session, monday, monday)
    assert {(entry.description, entry.duration_seconds) for entry in entries} == {
        ("Prototype", 7200),
        ("Team meeting", 5400),
    }

    assert clear_week(session, monday) == 2
    assert entries_between(session, monday, monday + timedelta(days=6)) == []


def test_submitted_week_cannot_be_cleared(session: Session) -> None:
    project = create_project(session, "Locked")
    task = list_tasks(session, project.id)[0]
    monday = date(2026, 8, 24)
    set_daily_task_hours(session, project.id, task.id, monday, 1)
    submit_timesheet(session, monday)

    with pytest.raises(ValueError, match="submitted"):
        clear_week(session, monday)


def test_delete_week_row_only_removes_matching_notes(session: Session) -> None:
    project = create_project(session, "Shared project")
    task = list_tasks(session, project.id)[0]
    monday = date(2026, 8, 24)
    for notes in ("Build", "Meeting"):
        set_daily_task_hours(
            session,
            project.id,
            task.id,
            monday,
            2,
            notes,
            match_description=notes,
        )

    assert delete_week_row(session, monday, project.id, task.id, "Meeting") == 1
    remaining = entries_between(session, monday, monday + timedelta(days=6))
    assert [(entry.description, entry.duration_seconds) for entry in remaining] == [
        ("Build", 7200)
    ]


def test_fiscal_week_runs_wednesday_through_tuesday() -> None:
    assert fiscal_week_start(date(2026, 8, 26)) == date(2026, 8, 26)
    assert fiscal_week_start(date(2026, 8, 31)) == date(2026, 8, 26)
    assert fiscal_week_start(date(2026, 9, 1)) == date(2026, 8, 26)


def test_holiday_observance_and_shifted_submission_deadline() -> None:
    holidays = observed_company_holidays(2026)
    assert holidays[date(2026, 7, 3)] == "Independence Day"
    assert holidays[date(2026, 9, 7)] == "Labor Day"
    assert submission_deadline(date(2026, 8, 26)) == date(2026, 9, 4)


def test_holiday_reduces_expected_weekly_hours(session: Session) -> None:
    employee = update_employee(session, "Morgan", "IT", "Alex", 40)
    assert expected_hours_for_week(employee, date(2026, 12, 23)) == Decimal("32.00")


def test_manager_oversight_exception_is_stored_on_entry(session: Session) -> None:
    project = create_project(session, "Capital delivery")
    oversight = create_task(session, project.id, "Manager Oversight", "OpEx")

    ordinary = add_manual_entry(
        session,
        project.id,
        date(2026, 8, 27),
        time(9),
        15,
        task_id=oversight.id,
    )
    hands_on = add_manual_entry(
        session,
        project.id,
        date(2026, 8, 27),
        time(10),
        15,
        task_id=oversight.id,
        manager_hands_on=True,
    )

    assert ordinary.resolved_expense_type == "OpEx"
    assert ordinary.manager_hands_on is False
    assert hands_on.resolved_expense_type == "CapEx"
    assert hands_on.manager_hands_on is True


def test_weekly_manager_oversight_can_switch_between_opex_and_capex(
    session: Session,
) -> None:
    project = create_project(session, "Capital delivery")
    oversight = create_task(session, project.id, "Manager Oversight", "OpEx")
    workday = date(2026, 8, 27)

    set_daily_task_hours(
        session,
        project.id,
        oversight.id,
        workday,
        8,
        manager_hands_on=True,
    )
    capital_entry = entries_between(session, workday, workday)[0]
    assert capital_entry.manager_hands_on is True
    assert capital_entry.resolved_expense_type == "CapEx"

    set_daily_task_hours(
        session,
        project.id,
        oversight.id,
        workday,
        8,
        manager_hands_on=False,
    )
    operating_entry = entries_between(session, workday, workday)[0]
    assert operating_entry.manager_hands_on is False
    assert operating_entry.resolved_expense_type == "OpEx"


def test_roster_and_project_registry_fields_are_preserved(session: Session) -> None:
    employee = update_employee(
        session,
        "Taylor",
        "IT",
        "Morgan",
        20,
        email="taylor@example.com",
        job_title="Analyst",
        engagement_type="Part-time",
    )
    project = create_project(
        session,
        "ERP",
        "Finance",
        identifier="P-100",
        project_type="Implementation",
        project_manager="Jordan",
        fiscal_year="FY27",
        cost_type="Mixed",
    )

    assert (employee.email, employee.job_title, employee.engagement_type) == (
        "taylor@example.com",
        "Analyst",
        "Part-time",
    )
    assert (project.identifier, project.project_manager, project.fiscal_year) == (
        "P-100",
        "Jordan",
        "FY27",
    )


def test_published_fiscal_calendars_can_be_loaded_idempotently(
    session: Session,
) -> None:
    assert seed_published_fiscal_calendar(session, "FY26") == 12
    assert seed_published_fiscal_calendar(session, "FY26") == 0
    periods = list_accounting_periods(session)
    assert len(periods) == 12
    assert (periods[0].start_date, periods[-1].end_date) == (
        date(2025, 10, 1),
        date(2026, 9, 29),
    )
    assert sum(period.week_count or 0 for period in periods) == 52
    context = accounting_period_for(session, date(2026, 1, 1))
    assert (context.fiscal_year, context.quarter, context.period_number) == (
        "FY26",
        1,
        3,
    )


def test_foundation_lifecycle_and_configured_daily_limit(session: Session) -> None:
    project = create_project(session, "Foundation lifecycle")
    task = list_tasks(session, project.id)[0]
    day = date(2026, 8, 27)

    assert get_timesheet(session, day).status == "Not Started"
    with pytest.raises(ValueError, match="Add time"):
        submit_timesheet(session, day)
    with pytest.raises(ValueError, match="between 0 and 16"):
        set_daily_task_hours(session, project.id, task.id, day, 16.25)
    with pytest.raises(ValueError, match="between 0 and 16"):
        set_daily_task_hours(session, project.id, task.id, day, -0.25)
    with pytest.raises(ValueError, match="quarter-hour increments"):
        set_daily_task_hours(session, project.id, task.id, day, 1.1)
    with pytest.raises(ValueError, match="between 0 and 16"):
        set_daily_task_hours(session, project.id, task.id, day, float("nan"))

    set_daily_task_hours(session, project.id, task.id, day, 2.25)
    assert get_timesheet(session, day).status == "In Progress"
    assert submit_timesheet(session, day).status == "Submitted"
