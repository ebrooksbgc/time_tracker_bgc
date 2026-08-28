from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import os

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models import (
    AccountingPeriod,
    Employee,
    FavoriteAssignment,
    Project,
    ProjectAssignment,
    Task,
    TimeEntry,
    Timesheet,
)
from time_utils import local_day_bounds, local_to_utc, utc_now, utc_to_local


MAX_DAILY_HOURS = Decimal(os.getenv("TIME_TRACKER_MAX_DAILY_HOURS", "16"))
EDITABLE_TIMESHEET_STATUSES = {
    "Not Started",
    "In Progress",
    "In Correction",
    "Open",
}
SUBMITTABLE_TIMESHEET_STATUSES = {"Not Started", "In Progress", "Open"}


def create_project(
    session: Session,
    name: str,
    client: str = "",
    work_type: str = "Project",
    *,
    identifier: str = "",
    project_type: str = "",
    project_manager: str = "",
    fiscal_year: str = "",
    cost_type: str = "Mixed",
) -> Project:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Project name is required.")
    if len(cleaned_name) > 100:
        raise ValueError("Project name must be 100 characters or fewer.")
    cleaned_client = client.strip()
    if len(cleaned_client) > 100:
        raise ValueError("Business area must be 100 characters or fewer.")
    if work_type not in {"Project", "Non-project"}:
        raise ValueError("Work type must be Project or Non-project.")
    if cost_type not in {"Capital", "Operating", "Mixed"}:
        raise ValueError("Cost type must be Capital, Operating, or Mixed.")
    project = Project(
        name=cleaned_name,
        client=cleaned_client,
        work_type=work_type,
        identifier=identifier.strip()[:50],
        project_type=project_type.strip()[:50],
        project_manager=project_manager.strip()[:100],
        fiscal_year=fiscal_year.strip()[:20],
        cost_type="Operating" if work_type == "Non-project" else cost_type,
    )
    session.add(project)
    session.flush()
    session.add(Task(project_id=project.id, name="General", expense_type="OpEx"))
    session.commit()
    session.refresh(project)
    return project


def list_projects(session: Session, active_only: bool = True) -> list[Project]:
    statement = select(Project)
    if active_only:
        statement = statement.where(Project.active.is_(True))
    statement = statement.order_by(Project.name)
    return list(session.exec(statement).all())


def list_assignable_projects(session: Session, employee_id: int) -> list[Project]:
    """Return active assigned projects plus all active non-project categories."""
    assigned_ids = select(ProjectAssignment.project_id).where(
        ProjectAssignment.employee_id == employee_id,
        ProjectAssignment.active.is_(True),
    )
    return list(
        session.exec(
            select(Project)
            .where(
                Project.active.is_(True),
                (Project.work_type == "Non-project")
                | (Project.identifier == "")
                | (Project.id.in_(assigned_ids)),
            )
            .order_by(Project.work_type, Project.name)
        ).all()
    )


def assign_project(
    session: Session,
    employee_id: int,
    project_id: int,
    assigned_by: str = "Administrator",
) -> ProjectAssignment:
    get_employee_by_id(session, employee_id)
    project = session.get(Project, project_id)
    if project is None or project.work_type != "Project":
        raise ValueError("Only a defined project can be assigned to a partner.")
    assignment = session.exec(
        select(ProjectAssignment).where(
            ProjectAssignment.employee_id == employee_id,
            ProjectAssignment.project_id == project_id,
        )
    ).first()
    if assignment is None:
        assignment = ProjectAssignment(
            employee_id=employee_id,
            project_id=project_id,
        )
    assignment.active = True
    assignment.assigned_by = assigned_by.strip()[:100] or "Administrator"
    assignment.assigned_at = utc_now()
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def list_project_assignments(
    session: Session, employee_id: int
) -> list[ProjectAssignment]:
    return list(
        session.exec(
            select(ProjectAssignment)
            .where(ProjectAssignment.employee_id == employee_id)
            .order_by(ProjectAssignment.assigned_at.desc())
        ).all()
    )


def add_favorite(
    session: Session, employee_id: int, project_id: int, task_id: int
) -> FavoriteAssignment:
    task = session.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise ValueError("Favorite task not found.")
    favorite = session.exec(
        select(FavoriteAssignment).where(
            FavoriteAssignment.employee_id == employee_id,
            FavoriteAssignment.project_id == project_id,
            FavoriteAssignment.task_id == task_id,
        )
    ).first()
    if favorite is None:
        favorite = FavoriteAssignment(
            employee_id=employee_id, project_id=project_id, task_id=task_id
        )
        session.add(favorite)
        session.commit()
        session.refresh(favorite)
    return favorite


def remove_favorite(
    session: Session, employee_id: int, project_id: int, task_id: int
) -> bool:
    favorite = session.exec(
        select(FavoriteAssignment).where(
            FavoriteAssignment.employee_id == employee_id,
            FavoriteAssignment.project_id == project_id,
            FavoriteAssignment.task_id == task_id,
        )
    ).first()
    if favorite is None:
        return False
    session.delete(favorite)
    session.commit()
    return True


def list_favorites(session: Session, employee_id: int) -> list[FavoriteAssignment]:
    return list(
        session.exec(
            select(FavoriteAssignment).where(
                FavoriteAssignment.employee_id == employee_id
            )
        ).all()
    )


def _require_project_assignment(
    session: Session, employee_id: int, project: Project
) -> None:
    if project.work_type == "Non-project" or not project.identifier:
        return
    assigned = session.exec(
        select(ProjectAssignment.id).where(
            ProjectAssignment.employee_id == employee_id,
            ProjectAssignment.project_id == project.id,
            ProjectAssignment.active.is_(True),
        )
    ).first()
    if assigned is None:
        raise ValueError("This project is not assigned to the selected partner.")


def get_employee(session: Session) -> Employee:
    employee = session.exec(select(Employee).order_by(Employee.id)).first()
    if employee is None:
        employee = Employee()
        session.add(employee)
        session.commit()
        session.refresh(employee)
    return employee


def update_employee(
    session: Session,
    name: str,
    department: str,
    manager: str,
    expected_weekly_hours: Decimal | float,
    *,
    email: str = "",
    job_title: str = "",
    engagement_type: str = "Full-time",
    employee_id: int | None = None,
) -> Employee:
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Employee name is required.")
    expected = Decimal(str(expected_weekly_hours)).quantize(Decimal("0.01"))
    if expected < 0 or expected > 168:
        raise ValueError("Expected weekly hours must be between 0 and 168.")
    if engagement_type not in {"Full-time", "Part-time", "Contractor"}:
        raise ValueError("Engagement type is invalid.")
    employee.name = cleaned_name[:100]
    employee.department = department.strip()[:100]
    employee.manager = manager.strip()[:100]
    employee.expected_weekly_hours = expected
    employee.email = email.strip()[:254]
    employee.job_title = job_title.strip()[:100]
    employee.engagement_type = engagement_type
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def list_employees(session: Session, active_only: bool = False) -> list[Employee]:
    statement = select(Employee)
    if active_only:
        statement = statement.where(Employee.active.is_(True))
    return list(session.exec(statement.order_by(Employee.name)).all())


def deactivate_employee(session: Session, employee_id: int) -> None:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise ValueError("Partner not found.")
    if active_timer(session, employee_id):
        raise ValueError("Stop this partner's active timer before deactivating them.")
    if employee.active and len(list_employees(session, active_only=True)) <= 1:
        raise ValueError("At least one active partner must remain.")
    employee.active = False
    session.add(employee)
    session.commit()


def reactivate_employee(session: Session, employee_id: int) -> None:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise ValueError("Partner not found.")
    employee.active = True
    session.add(employee)
    session.commit()


def get_employee_by_id(session: Session, employee_id: int) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise ValueError("The selected partner does not exist.")
    return employee


def fiscal_week_start(day: date) -> date:
    """Return the Wednesday that starts the fiscal week containing ``day``."""
    return day - timedelta(days=(day.weekday() - 2) % 7)


def fiscal_week_end(day: date) -> date:
    return fiscal_week_start(day) + timedelta(days=6)


def monday_for(day: date) -> date:
    """Backward-compatible calendar-week helper; new code uses fiscal_week_start."""
    return day - timedelta(days=day.weekday())


def _observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def observed_company_holidays(year: int) -> dict[date, str]:
    """Compute the six company holidays and their observed dates for a year."""
    memorial = date(year, 5, monthrange(year, 5)[1])
    memorial -= timedelta(days=memorial.weekday())
    labor = date(year, 9, 1) + timedelta(days=(7 - date(year, 9, 1).weekday()) % 7)
    thanksgiving = date(year, 11, 1) + timedelta(
        days=(3 - date(year, 11, 1).weekday()) % 7 + 21
    )
    holidays = {
        _observed_fixed_holiday(date(year, 1, 1)): "New Year's Day",
        memorial: "Memorial Day",
        _observed_fixed_holiday(date(year, 7, 4)): "Independence Day",
        labor: "Labor Day",
        thanksgiving: "Thanksgiving",
        _observed_fixed_holiday(date(year, 12, 25)): "Christmas",
    }
    return holidays


def submission_deadline(week: date) -> date:
    """Return the Monday deadline, shifted to Friday for an observed holiday."""
    deadline = fiscal_week_start(week) + timedelta(days=12)
    holidays = observed_company_holidays(deadline.year)
    return deadline - timedelta(days=3) if deadline in holidays else deadline


def holiday_dates_in_week(week: date) -> dict[date, str]:
    start = fiscal_week_start(week)
    end = start + timedelta(days=6)
    holidays: dict[date, str] = {}
    for year in {start.year, end.year}:
        holidays.update(
            {
                day: name
                for day, name in observed_company_holidays(year).items()
                if start <= day <= end
            }
        )
    return holidays


def expected_hours_for_week(employee: Employee, week: date) -> Decimal:
    """Adjust standard hours for observed holidays in the fiscal work week."""
    standard = Decimal(employee.expected_weekly_hours)
    if standard <= 0:
        return Decimal("0.00")
    daily = standard / Decimal("5")
    return max(Decimal("0.00"), standard - daily * len(holiday_dates_in_week(week)))


def list_tasks(
    session: Session, project_id: int | None = None, active_only: bool = True
) -> list[Task]:
    statement = select(Task)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    if active_only:
        statement = statement.where(Task.active.is_(True))
    return list(session.exec(statement.order_by(Task.name)).all())


def create_task(
    session: Session, project_id: int, name: str, expense_type: str = "OpEx"
) -> Task:
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("The selected project does not exist.")
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Task name is required.")
    if len(cleaned_name) > 100:
        raise ValueError("Task name must be 100 characters or fewer.")
    if expense_type not in {"CapEx", "OpEx"}:
        raise ValueError("Expense type must be CapEx or OpEx.")
    if project.work_type == "Non-project":
        expense_type = "OpEx"
    existing = session.exec(
        select(Task).where(
            Task.project_id == project_id,
            func.lower(Task.name) == cleaned_name.lower(),
        )
    ).first()
    if existing:
        return existing
    task = Task(
        project_id=project_id, name=cleaned_name, expense_type=expense_type
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def get_timesheet(
    session: Session, week_start: date, employee_id: int | None = None
) -> Timesheet:
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    start = fiscal_week_start(week_start)
    timesheet = session.exec(
        select(Timesheet).where(
            Timesheet.employee_id == employee.id,
            Timesheet.week_start == start,
        )
    ).first()
    if timesheet is None:
        period = accounting_period_for(session, start)
        initial_status = {
            "Correction": "In Correction",
            "Locked": "Locked",
        }.get(period.status if period else "", "Not Started")
        timesheet = Timesheet(
            employee_id=employee.id,
            week_start=start,
            status=initial_status,
        )
        session.add(timesheet)
        session.commit()
        session.refresh(timesheet)
    return timesheet


def submit_timesheet(
    session: Session, week_start: date, employee_id: int | None = None
) -> Timesheet:
    timesheet = get_timesheet(session, week_start, employee_id)
    if active_timer(session, employee_id):
        raise ValueError("Stop the active timer before submitting the week.")
    week_start = fiscal_week_start(week_start)
    if not entries_between(
        session, week_start, week_start + timedelta(days=6), timesheet.employee_id
    ):
        raise ValueError("Add time before submitting this timesheet.")
    if timesheet.status not in SUBMITTABLE_TIMESHEET_STATUSES:
        raise ValueError(f"A {timesheet.status} timesheet cannot be submitted.")
    timesheet.status = "Submitted"
    timesheet.submitted_at = utc_now()
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.commit()
    session.refresh(timesheet)
    return timesheet


def recall_timesheet(
    session: Session, week_start: date, employee_id: int | None = None
) -> Timesheet:
    timesheet = get_timesheet(session, week_start, employee_id)
    week_start = fiscal_week_start(week_start)
    timesheet.status = (
        "In Progress"
        if entries_between(
            session, week_start, week_start + timedelta(days=6), timesheet.employee_id
        )
        else "Not Started"
    )
    timesheet.submitted_at = None
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.commit()
    session.refresh(timesheet)
    return timesheet


def _require_open_timesheet(
    session: Session, day: date, employee_id: int | None = None
) -> None:
    period = accounting_period_for(session, day)
    if period and period.status == "Locked":
        raise ValueError(f"Accounting period {period.name} is locked.")
    if (
        get_timesheet(session, fiscal_week_start(day), employee_id).status
        not in EDITABLE_TIMESHEET_STATUSES
    ):
        raise ValueError("This timesheet is submitted. Recall it before editing.")
    if (
        period
        and period.status == "Correction"
        and period.correction_deadline
        and date.today() > period.correction_deadline
    ):
        raise ValueError(f"The correction window for {period.name} has ended.")


def suggest_expense_type(task_name: str, work_type: str = "Project") -> tuple[str, str]:
    """Return a transparent prototype suggestion for classification review."""
    if work_type == "Non-project":
        return "OpEx", "Non-project time is always operating expense."
    normalized = task_name.casefold()
    capital_terms = {
        "build", "develop", "development", "implement", "implementation",
        "upgrade", "enhancement", "configure", "configuration", "design",
    }
    matched = sorted(term for term in capital_terms if term in normalized)
    if matched:
        return "CapEx", f"Potential asset-creation language: {', '.join(matched)}."
    return "OpEx", "No asset-creation terms were detected; review before saving."


def accounting_period_for(session: Session, day: date) -> AccountingPeriod | None:
    return session.exec(
        select(AccountingPeriod).where(
            AccountingPeriod.start_date <= day,
            AccountingPeriod.end_date >= day,
        )
    ).first()


def list_accounting_periods(session: Session) -> list[AccountingPeriod]:
    return list(
        session.exec(select(AccountingPeriod).order_by(AccountingPeriod.start_date)).all()
    )


def create_accounting_period(
    session: Session,
    name: str,
    start_date: date,
    end_date: date,
    *,
    fiscal_year: str = "",
    quarter: int | None = None,
    period_number: int | None = None,
    week_count: int | None = None,
) -> AccountingPeriod:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Period name is required.")
    if start_date > end_date:
        raise ValueError("Period start must be on or before its end.")
    overlap = session.exec(
        select(AccountingPeriod).where(
            AccountingPeriod.start_date <= end_date,
            AccountingPeriod.end_date >= start_date,
        )
    ).first()
    if overlap:
        raise ValueError(f"Dates overlap accounting period {overlap.name}.")
    period = AccountingPeriod(
        name=cleaned_name[:100],
        start_date=start_date,
        end_date=end_date,
        fiscal_year=fiscal_year.strip()[:20],
        quarter=quarter,
        period_number=period_number,
        week_count=week_count,
    )
    session.add(period)
    session.commit()
    session.refresh(period)
    return period


PUBLISHED_FISCAL_CALENDARS = {
    "FY26": [
        (1, 1, "2025-10-01", "2025-10-28", 4),
        (1, 2, "2025-10-29", "2025-12-02", 5),
        (1, 3, "2025-12-03", "2026-01-06", 5),
        (2, 4, "2026-01-07", "2026-02-03", 4),
        (2, 5, "2026-02-04", "2026-03-10", 5),
        (2, 6, "2026-03-11", "2026-04-07", 4),
        (3, 7, "2026-04-08", "2026-05-05", 4),
        (3, 8, "2026-05-06", "2026-06-09", 5),
        (3, 9, "2026-06-10", "2026-07-07", 4),
        (4, 10, "2026-07-08", "2026-08-04", 4),
        (4, 11, "2026-08-05", "2026-09-01", 4),
        (4, 12, "2026-09-02", "2026-09-29", 4),
    ],
    "FY27": [
        (1, 1, "2026-09-30", "2026-10-27", 4),
        (1, 2, "2026-10-28", "2026-12-01", 5),
        (1, 3, "2026-12-02", "2027-01-05", 5),
        (2, 4, "2027-01-06", "2027-02-02", 4),
        (2, 5, "2027-02-03", "2027-03-09", 5),
        (2, 6, "2027-03-10", "2027-04-06", 4),
        (3, 7, "2027-04-07", "2027-05-04", 4),
        (3, 8, "2027-05-05", "2027-06-08", 5),
        (3, 9, "2027-06-09", "2027-07-06", 4),
        (4, 10, "2027-07-07", "2027-08-03", 4),
        (4, 11, "2027-08-04", "2027-08-31", 4),
        (4, 12, "2027-09-01", "2027-09-28", 4),
    ],
}


def seed_published_fiscal_calendar(session: Session, fiscal_year: str) -> int:
    definitions = PUBLISHED_FISCAL_CALENDARS.get(fiscal_year)
    if definitions is None:
        raise ValueError("Published calendar is available only for FY26 or FY27.")
    existing = {
        (period.start_date, period.end_date)
        for period in list_accounting_periods(session)
    }
    added = 0
    for quarter, number, start, end, weeks in definitions:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        if (start_date, end_date) in existing:
            continue
        create_accounting_period(
            session,
            f"{fiscal_year} period {number:02d}",
            start_date,
            end_date,
            fiscal_year=fiscal_year,
            quarter=quarter,
            period_number=number,
            week_count=weeks,
        )
        existing.add((start_date, end_date))
        added += 1
    return added


def set_accounting_period_status(
    session: Session,
    period_id: int,
    status: str,
    correction_deadline: date | None = None,
) -> AccountingPeriod:
    if status not in {"Open", "Correction", "Locked"}:
        raise ValueError("Period status must be Open, Correction, or Locked.")
    period = session.get(AccountingPeriod, period_id)
    if period is None:
        raise ValueError("Accounting period not found.")
    allowed_transitions = {
        "Open": {"Open", "Correction"},
        "Correction": {"Correction", "Locked"},
        "Locked": {"Locked"},
    }
    if status not in allowed_transitions[period.status]:
        raise ValueError(
            f"Accounting period must follow Open → Correction → Locked; "
            f"{period.name} is currently {period.status}."
        )
    if status == "Correction" and correction_deadline is None:
        raise ValueError("A correction deadline is required.")
    period.status = status
    period.correction_deadline = correction_deadline if status == "Correction" else None
    period.updated_at = utc_now()
    session.add(period)
    if status in {"Correction", "Locked"}:
        timesheet_status = "In Correction" if status == "Correction" else "Locked"
        affected = session.exec(
            select(Timesheet).where(
                Timesheet.week_start >= period.start_date,
                Timesheet.week_start <= period.end_date,
            )
        ).all()
        for timesheet in affected:
            timesheet.status = timesheet_status
            timesheet.updated_at = utc_now()
            session.add(timesheet)
    session.commit()
    session.refresh(period)
    return period


def active_timer(session: Session, employee_id: int | None = None) -> TimeEntry | None:
    statement = select(TimeEntry).where(TimeEntry.ended_at.is_(None))
    if employee_id is not None:
        statement = statement.where(TimeEntry.employee_id == employee_id)
    statement = statement.order_by(TimeEntry.started_at.desc())
    return session.exec(statement).first()


def resolved_expense_type(
    project: Project, task: Task | None, manager_hands_on: bool = False
) -> str:
    if project.work_type == "Non-project" or task is None:
        return "OpEx"
    if task.name.casefold() == "manager oversight":
        return "CapEx" if manager_hands_on else "OpEx"
    return task.expense_type


def start_timer(
    session: Session,
    project_id: int,
    description: str = "",
    started_at: datetime | None = None,
    task_id: int | None = None,
    manager_hands_on: bool = False,
    employee_id: int | None = None,
) -> TimeEntry:
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    if not employee.active:
        raise ValueError("The selected partner is inactive.")
    if active_timer(session, employee.id):
        raise ValueError("Stop the active timer before starting another one.")
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("The selected project does not exist.")
    if not project.active:
        raise ValueError("The selected project is inactive.")
    _require_project_assignment(session, employee.id, project)
    task = None
    if task_id is not None:
        task = session.get(Task, task_id)
        if task is None or task.project_id != project_id or not task.active:
            raise ValueError("The selected task is not available for this project.")
    elif not project.identifier:
        task = session.exec(
            select(Task).where(Task.project_id == project.id, Task.active.is_(True))
        ).first()
        task_id = task.id if task else None
    if task is None:
        raise ValueError("A defined task code or non-project category is required.")
    cleaned_description = description.strip()
    if len(cleaned_description) > 300:
        raise ValueError("Description must be 300 characters or fewer.")
    effective_start = local_to_utc(started_at) if started_at else utc_now()
    _require_open_timesheet(
        session, utc_to_local(effective_start).date(), employee.id
    )

    entry = TimeEntry(
        employee_id=employee.id,
        project_id=project_id,
        task_id=task_id,
        description=cleaned_description,
        started_at=effective_start,
        resolved_expense_type=resolved_expense_type(project, task, manager_hands_on),
        manager_hands_on=manager_hands_on,
    )
    timesheet = get_timesheet(
        session, utc_to_local(effective_start).date(), employee.id
    )
    timesheet.status = "In Progress"
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.add(entry)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("Stop the active timer before starting another one.") from error
    session.refresh(entry)
    return entry


def stop_timer(
    session: Session,
    ended_at: datetime | None = None,
    employee_id: int | None = None,
) -> TimeEntry:
    entry = active_timer(session, employee_id)
    if entry is None:
        raise ValueError("There is no active timer.")

    stop_time = local_to_utc(ended_at) if ended_at else utc_now()
    if stop_time < entry.started_at:
        raise ValueError("Stop time cannot be before start time.")
    entry.ended_at = stop_time
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def add_manual_entry(
    session: Session,
    project_id: int,
    entry_date: date,
    start_time: time,
    duration_minutes: int,
    description: str = "",
    task_id: int | None = None,
    manager_hands_on: bool = False,
    employee_id: int | None = None,
) -> TimeEntry:
    if duration_minutes <= 0:
        raise ValueError("Duration must be greater than zero.")
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("The selected project does not exist.")
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    if not employee.active:
        raise ValueError("The selected partner is inactive.")
    _require_project_assignment(session, employee.id, project)
    task = None
    if task_id is not None:
        task = session.get(Task, task_id)
        if task is None or task.project_id != project_id or not task.active:
            raise ValueError("The selected task is not available for this project.")
    elif not project.identifier:
        task = session.exec(
            select(Task).where(Task.project_id == project.id, Task.active.is_(True))
        ).first()
        task_id = task.id if task else None
    if task is None:
        raise ValueError("A defined task code or non-project category is required.")
    _require_open_timesheet(session, entry_date, employee.id)
    cleaned_description = description.strip()
    if len(cleaned_description) > 300:
        raise ValueError("Description must be 300 characters or fewer.")

    started_at = local_to_utc(datetime.combine(entry_date, start_time))
    ended_at = started_at + timedelta(minutes=duration_minutes)
    entry = TimeEntry(
        employee_id=employee.id,
        project_id=project_id,
        task_id=task_id,
        description=cleaned_description,
        started_at=started_at,
        ended_at=ended_at,
        resolved_expense_type=resolved_expense_type(project, task, manager_hands_on),
        manager_hands_on=manager_hands_on,
    )
    timesheet = get_timesheet(session, entry_date, employee.id)
    timesheet.status = "In Progress"
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def set_daily_task_hours(
    session: Session,
    project_id: int,
    task_id: int,
    day: date,
    hours: Decimal | float,
    description: str = "",
    match_description: str | None = None,
    manager_hands_on: bool = False,
    employee_id: int | None = None,
) -> None:
    """Replace one task/day cell while preserving entries outside that cell."""
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    if not employee.active:
        raise ValueError("The selected partner is inactive.")
    _require_open_timesheet(session, day, employee.id)
    task = session.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise ValueError("The selected task is not available for this project.")
    project = session.get(Project, project_id)
    if project is None or not project.active:
        raise ValueError("The selected project is inactive or unavailable.")
    _require_project_assignment(session, employee.id, project)
    requested = Decimal(str(hours))
    if not requested.is_finite() or requested < 0 or requested > MAX_DAILY_HOURS:
        raise ValueError(
            f"Daily task hours must be between 0 and {MAX_DAILY_HOURS:g}."
        )
    if requested * 4 != (requested * 4).to_integral_value():
        raise ValueError("Hours must use quarter-hour increments.")

    matching = [
        entry
        for entry in entries_between(session, day, day, employee.id)
        if entry.project_id == project_id
        and entry.task_id == task_id
        and (match_description is None or entry.description == match_description)
    ]
    other_seconds = sum(
        duration_between(entry, day, day)
        for entry in entries_between(session, day, day, employee.id)
        if entry not in matching
    )
    if Decimal(other_seconds) / Decimal(3600) + requested > MAX_DAILY_HOURS:
        raise ValueError(f"Total daily hours cannot exceed {MAX_DAILY_HOURS:g}.")
    if any(entry.ended_at is None for entry in matching):
        raise ValueError("Stop the running timer before editing this task's hours.")
    if any(
        utc_to_local(entry.started_at).date() != day
        or (
            utc_to_local(entry.ended_at).date() != day
            and utc_to_local(entry.ended_at).time() != datetime.min.time()
        )
        for entry in matching
    ):
        raise ValueError(
            "This cell contains an entry spanning multiple days. Edit it in History."
        )
    for entry in matching:
        session.delete(entry)
    session.flush()

    minutes = int(requested * 60)
    if minutes:
        started_at = local_to_utc(datetime.combine(day, datetime.min.time()))
        session.add(
            TimeEntry(
                employee_id=employee.id,
                project_id=project_id,
                task_id=task_id,
                description=description.strip()[:300],
                started_at=started_at,
                ended_at=started_at + timedelta(minutes=minutes),
                resolved_expense_type=resolved_expense_type(
                    project, task, manager_hands_on
                ),
                manager_hands_on=manager_hands_on,
            )
        )
    timesheet = get_timesheet(session, fiscal_week_start(day), employee.id)
    timesheet.status = "In Progress"
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.commit()


def clear_week(
    session: Session, week_start: date, employee_id: int | None = None
) -> int:
    week_start = fiscal_week_start(week_start)
    week_end = week_start + timedelta(days=6)
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    _require_open_timesheet(session, week_start, employee.id)
    entries = entries_between(session, week_start, week_end, employee.id)
    if any(entry.ended_at is None for entry in entries):
        raise ValueError("Stop the running timer before clearing this week.")
    range_start, range_end = local_day_bounds(week_start, week_end)
    if any(
        entry.started_at < range_start or entry.ended_at > range_end
        for entry in entries
    ):
        raise ValueError(
            "This week contains an entry spanning the week boundary. "
            "Edit that entry in History before clearing the week."
        )
    for entry in entries:
        session.delete(entry)
    timesheet = get_timesheet(session, week_start, employee.id)
    timesheet.status = "Not Started"
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.commit()
    return len(entries)


def delete_week_row(
    session: Session,
    week_start: date,
    project_id: int,
    task_id: int,
    description: str,
    employee_id: int | None = None,
) -> int:
    """Delete one project/task/notes row from an open weekly timesheet."""
    week_start = fiscal_week_start(week_start)
    week_end = week_start + timedelta(days=6)
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    _require_open_timesheet(session, week_start, employee.id)
    entries = [
        entry
        for entry in entries_between(session, week_start, week_end, employee.id)
        if entry.project_id == project_id
        and entry.task_id == task_id
        and entry.description == description
    ]
    if any(entry.ended_at is None for entry in entries):
        raise ValueError("Stop the running timer before deleting this row.")
    range_start, range_end = local_day_bounds(week_start, week_end)
    if any(
        entry.started_at < range_start or entry.ended_at > range_end
        for entry in entries
    ):
        raise ValueError(
            "This row contains an entry spanning the week boundary. "
            "Edit that entry in History before deleting the row."
        )
    for entry in entries:
        session.delete(entry)
    timesheet = get_timesheet(session, week_start, employee.id)
    timesheet.updated_at = utc_now()
    session.add(timesheet)
    session.commit()
    return len(entries)


def copy_previous_week(
    session: Session, destination_week: date, employee_id: int | None = None
) -> int:
    destination = fiscal_week_start(destination_week)
    employee = (
        get_employee_by_id(session, employee_id)
        if employee_id is not None
        else get_employee(session)
    )
    _require_open_timesheet(session, destination, employee.id)
    source = destination - timedelta(days=7)
    source_entries = entries_between(
        session, source, source + timedelta(days=6), employee.id
    )
    existing = entries_between(
        session, destination, destination + timedelta(days=6), employee.id
    )
    occupied = {
        (entry.project_id, entry.task_id, utc_to_local(entry.started_at).date())
        for entry in existing
    }
    copied = 0
    for entry in source_entries:
        if entry.ended_at is None:
            continue
        new_start = entry.started_at + timedelta(days=7)
        key = (entry.project_id, entry.task_id, utc_to_local(new_start).date())
        if key in occupied:
            continue
        session.add(
            TimeEntry(
                employee_id=employee.id,
                project_id=entry.project_id,
                task_id=entry.task_id,
                description=entry.description,
                started_at=new_start,
                ended_at=entry.ended_at + timedelta(days=7),
                resolved_expense_type=entry.resolved_expense_type,
                manager_hands_on=entry.manager_hands_on,
            )
        )
        occupied.add(key)
        copied += 1
    session.commit()
    return copied


def delete_entry(session: Session, entry_id: int) -> None:
    entry = session.get(TimeEntry, entry_id)
    if entry is None:
        raise ValueError("Time entry not found.")
    _require_open_timesheet(
        session, utc_to_local(entry.started_at).date(), entry.employee_id
    )
    session.delete(entry)
    session.commit()


def project_entry_count(session: Session, project_id: int) -> int:
    statement = (
        select(func.count())
        .select_from(TimeEntry)
        .where(TimeEntry.project_id == project_id)
    )
    return int(session.exec(statement).one())


def deactivate_project(session: Session, project_id: int) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found.")

    running = active_timer(session)
    if running and running.project_id == project_id:
        raise ValueError("Stop this project's active timer before deactivating it.")
    project.active = False
    project.status = "Inactive"
    session.add(project)
    session.commit()


def reactivate_project(session: Session, project_id: int) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found.")
    project.active = True
    project.status = "Active"
    session.add(project)
    session.commit()


def delete_project(
    session: Session,
    project_id: int,
    delete_entries: bool = False,
) -> None:
    """Backward-compatible wrapper; projects are never physically deleted."""
    deactivate_project(session, project_id)


def entries_between(
    session: Session,
    start_date: date,
    end_date: date,
    employee_id: int | None = None,
) -> list[TimeEntry]:
    if start_date > end_date:
        raise ValueError("The start date must be before the end date.")
    start, exclusive_end = local_day_bounds(start_date, end_date)
    statement = select(TimeEntry).where(
        TimeEntry.started_at < exclusive_end,
        (TimeEntry.ended_at.is_(None)) | (TimeEntry.ended_at >= start),
    )
    if employee_id is not None:
        statement = statement.where(TimeEntry.employee_id == employee_id)
    statement = statement.order_by(TimeEntry.started_at.desc())
    return list(session.exec(statement).all())


def entry_date_bounds(
    session: Session, employee_id: int | None = None
) -> tuple[date | None, date | None]:
    statement = select(
        func.min(TimeEntry.started_at),
        func.max(func.coalesce(TimeEntry.ended_at, TimeEntry.started_at)),
    )
    if employee_id is not None:
        statement = statement.where(TimeEntry.employee_id == employee_id)
    earliest, latest = session.exec(statement).one()
    return (
        utc_to_local(earliest).date() if earliest else None,
        utc_to_local(latest).date() if latest else None,
    )


def duration_between(entry: TimeEntry, start_date: date, end_date: date) -> int:
    """Return only the portion of an entry overlapping the local date range."""
    start, exclusive_end = local_day_bounds(start_date, end_date)
    entry_end = entry.ended_at or utc_now()
    overlap_start = max(entry.started_at, start)
    overlap_end = min(entry_end, exclusive_end)
    return max(0, int((overlap_end - overlap_start).total_seconds()))


def entry_count(session: Session) -> int:
    return int(session.exec(select(func.count()).select_from(TimeEntry)).one())
