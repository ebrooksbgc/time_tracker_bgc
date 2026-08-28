from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, text
from sqlmodel import Field, SQLModel

from time_utils import utc_now


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=100)
    client: str = Field(default="", max_length=100)
    work_type: str = Field(default="Project", max_length=20, index=True)
    identifier: str = Field(default="", max_length=50, index=True)
    project_type: str = Field(default="", max_length=50)
    status: str = Field(default="Active", max_length=20, index=True)
    project_manager: str = Field(default="", max_length=100)
    fiscal_year: str = Field(default="", max_length=20, index=True)
    cost_type: str = Field(default="Mixed", max_length=20, index=True)
    notes: str = Field(default="", max_length=500)
    hourly_rate: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        sa_type=Numeric(10, 2),
    )
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str = Field(min_length=1, max_length=100)
    expense_type: str = Field(default="OpEx", max_length=10, index=True)
    description: str = Field(default="", max_length=500)
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class Employee(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(default="Hackathon employee", max_length=100)
    department: str = Field(default="AI hackathon", max_length=100)
    manager: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=254, index=True)
    job_title: str = Field(default="", max_length=100)
    engagement_type: str = Field(default="Full-time", max_length=20, index=True)
    active: bool = Field(default=True, index=True)
    partner_id: str = Field(default="", max_length=50, index=True)
    expected_weekly_hours: Decimal = Field(
        default=Decimal("40.00"), ge=0, sa_type=Numeric(5, 2)
    )


class Timesheet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    week_start: date = Field(index=True)
    status: str = Field(default="Not Started", max_length=20, index=True)
    submitted_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)


class AccountingPeriod(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    start_date: date = Field(index=True)
    end_date: date = Field(index=True)
    fiscal_year: str = Field(default="", max_length=20, index=True)
    quarter: int | None = Field(default=None, ge=1, le=4, index=True)
    period_number: int | None = Field(default=None, ge=1, le=12, index=True)
    week_count: int | None = Field(default=None, ge=1, le=6)
    status: str = Field(default="Open", max_length=20, index=True)
    correction_deadline: date | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectAssignment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    active: bool = Field(default=True, index=True)
    assigned_by: str = Field(default="Administrator", max_length=100)
    assigned_at: datetime = Field(default_factory=utc_now)


class FavoriteAssignment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TimeEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    employee_id: int | None = Field(default=None, foreign_key="employee.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    task_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    description: str = Field(default="", max_length=300)
    started_at: datetime = Field(index=True)
    ended_at: datetime | None = Field(default=None, index=True)
    # Retained for backward-compatible database reads; the employee UI does not
    # expose billing and all new entries store False.
    billable: bool = Field(default=False)
    resolved_expense_type: str = Field(default="OpEx", max_length=10, index=True)
    manager_hands_on: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def duration_seconds(self) -> int:
        end = self.ended_at or utc_now()
        return max(0, int((end - self.started_at).total_seconds()))


Index(
    "uq_timeentry_single_active_timer",
    TimeEntry.employee_id,
    unique=True,
    sqlite_where=text("ended_at IS NULL AND employee_id IS NOT NULL"),
    postgresql_where=text("ended_at IS NULL AND employee_id IS NOT NULL"),
)
Index(
    "uq_project_assignment_employee_project",
    ProjectAssignment.employee_id,
    ProjectAssignment.project_id,
    unique=True,
)
Index(
    "uq_favorite_assignment_employee_project_task",
    FavoriteAssignment.employee_id,
    FavoriteAssignment.project_id,
    FavoriteAssignment.task_id,
    unique=True,
)
Index(
    "uq_employee_partner_id",
    Employee.partner_id,
    unique=True,
    sqlite_where=text("partner_id <> ''"),
    postgresql_where=text("partner_id <> ''"),
)
Index(
    "uq_project_identifier",
    Project.identifier,
    unique=True,
    sqlite_where=text("identifier <> ''"),
    postgresql_where=text("identifier <> ''"),
)
Index(
    "uq_accounting_period_dates",
    AccountingPeriod.start_date,
    AccountingPeriod.end_date,
    unique=True,
)
Index(
    "uq_timesheet_employee_week",
    Timesheet.employee_id,
    Timesheet.week_start,
    unique=True,
)
