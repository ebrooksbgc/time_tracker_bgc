import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from models import Employee, Project, Task, TimeEntry
from time_utils import local_to_utc


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE = APP_DIR / "time_tracker.db"
DATABASE_URL = os.getenv(
    "TIME_TRACKER_DATABASE_URL",
    f"sqlite:///{DEFAULT_DATABASE}",
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _migrate_legacy_local_datetimes() -> None:
    """Convert databases created before UTC storage to UTC exactly once."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_metadata "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(100) NOT NULL)"
            )
        )
        migrated = connection.execute(
            text("SELECT value FROM app_metadata WHERE key = 'utc_datetimes'")
        ).scalar_one_or_none()
        if migrated:
            return

        for table_name, columns in {
            "project": ("created_at",),
            "timeentry": ("started_at", "ended_at", "created_at"),
        }.items():
            rows = connection.execute(
                text(f"SELECT id, {', '.join(columns)} FROM {table_name}")
            ).mappings()
            for row in rows:
                values = {
                    column: local_to_utc(
                        datetime.fromisoformat(row[column])
                        if isinstance(row[column], str)
                        else row[column]
                    )
                    if row[column]
                    else None
                    for column in columns
                }
                assignments = ", ".join(f"{column} = :{column}" for column in columns)
                connection.execute(
                    text(f"UPDATE {table_name} SET {assignments} WHERE id = :id"),
                    {"id": row["id"], **values},
                )
        connection.execute(
            text(
                "INSERT INTO app_metadata (key, value) "
                "VALUES ('utc_datetimes', '1')"
            )
        )


def _add_missing_columns() -> None:
    """Apply the small additive migrations needed by the hackathon app."""
    with engine.begin() as connection:
        entry_columns = {item["name"] for item in inspect(connection).get_columns("timeentry")}
        if "task_id" not in entry_columns:
            connection.execute(text("ALTER TABLE timeentry ADD COLUMN task_id INTEGER"))
            connection.execute(
                text("CREATE INDEX ix_timeentry_task_id ON timeentry (task_id)")
            )
        if "resolved_expense_type" not in entry_columns:
            connection.execute(
                text("ALTER TABLE timeentry ADD COLUMN resolved_expense_type VARCHAR(10) NOT NULL DEFAULT 'OpEx'")
            )
            connection.execute(
                text("CREATE INDEX ix_timeentry_resolved_expense_type ON timeentry (resolved_expense_type)")
            )
            connection.execute(
                text(
                    "UPDATE timeentry SET resolved_expense_type = COALESCE("
                    "(SELECT expense_type FROM task WHERE task.id = timeentry.task_id), 'OpEx')"
                )
            )
        if "manager_hands_on" not in entry_columns:
            connection.execute(
                text("ALTER TABLE timeentry ADD COLUMN manager_hands_on BOOLEAN NOT NULL DEFAULT 0")
            )
        if "employee_id" not in entry_columns:
            connection.execute(text("ALTER TABLE timeentry ADD COLUMN employee_id INTEGER"))
            default_employee_id = connection.execute(
                text("SELECT id FROM employee ORDER BY id LIMIT 1")
            ).scalar_one_or_none()
            if default_employee_id is not None:
                connection.execute(
                    text("UPDATE timeentry SET employee_id = :employee_id"),
                    {"employee_id": default_employee_id},
                )
            connection.execute(
                text("CREATE INDEX ix_timeentry_employee_id ON timeentry (employee_id)")
            )
            connection.execute(
                text("DROP INDEX IF EXISTS uq_timeentry_single_active_timer")
            )
        project_columns = {
            item["name"] for item in inspect(connection).get_columns("project")
        }
        if "work_type" not in project_columns:
            connection.execute(
                text("ALTER TABLE project ADD COLUMN work_type VARCHAR(20) NOT NULL DEFAULT 'Project'")
            )
            connection.execute(text("CREATE INDEX ix_project_work_type ON project (work_type)"))
        for column, definition in {
            "identifier": "VARCHAR(50) NOT NULL DEFAULT ''",
            "project_type": "VARCHAR(50) NOT NULL DEFAULT ''",
            "status": "VARCHAR(20) NOT NULL DEFAULT 'Active'",
            "project_manager": "VARCHAR(100) NOT NULL DEFAULT ''",
            "fiscal_year": "VARCHAR(20) NOT NULL DEFAULT ''",
            "cost_type": "VARCHAR(20) NOT NULL DEFAULT 'Mixed'",
            "notes": "VARCHAR(500) NOT NULL DEFAULT ''",
        }.items():
            if column not in project_columns:
                connection.execute(text(f"ALTER TABLE project ADD COLUMN {column} {definition}"))
        employee_columns = {
            item["name"] for item in inspect(connection).get_columns("employee")
        }
        for column, definition in {
            "email": "VARCHAR(254) NOT NULL DEFAULT ''",
            "job_title": "VARCHAR(100) NOT NULL DEFAULT ''",
            "engagement_type": "VARCHAR(20) NOT NULL DEFAULT 'Full-time'",
            "active": "BOOLEAN NOT NULL DEFAULT 1",
            "partner_id": "VARCHAR(50) NOT NULL DEFAULT ''",
        }.items():
            if column not in employee_columns:
                connection.execute(text(f"ALTER TABLE employee ADD COLUMN {column} {definition}"))
        period_columns = {
            item["name"] for item in inspect(connection).get_columns("accountingperiod")
        }
        for column, definition in {
            "fiscal_year": "VARCHAR(20) NOT NULL DEFAULT ''",
            "quarter": "INTEGER",
            "period_number": "INTEGER",
            "week_count": "INTEGER",
        }.items():
            if column not in period_columns:
                connection.execute(
                    text(f"ALTER TABLE accountingperiod ADD COLUMN {column} {definition}")
                )
        task_columns = {item["name"] for item in inspect(connection).get_columns("task")}
        if "expense_type" not in task_columns:
            connection.execute(
                text("ALTER TABLE task ADD COLUMN expense_type VARCHAR(10) NOT NULL DEFAULT 'OpEx'")
            )
            connection.execute(text("CREATE INDEX ix_task_expense_type ON task (expense_type)"))
        if "description" not in task_columns:
            connection.execute(
                text("ALTER TABLE task ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT ''")
            )


def _seed_defaults() -> None:
    with Session(engine) as session:
        if session.exec(select(Employee.id)).first() is None:
            session.add(Employee())
        projects = list(session.exec(select(Project.id)).all())
        for project_id in projects:
            has_task = session.exec(
                select(Task.id).where(Task.project_id == project_id)
            ).first()
            if has_task is None:
                session.add(Task(project_id=project_id, name="General"))
        session.flush()
        for entry in session.exec(
            select(TimeEntry).where(TimeEntry.task_id.is_(None))
        ).all():
            entry.task_id = session.exec(
                select(Task.id)
                .where(Task.project_id == entry.project_id)
                .order_by(Task.id)
            ).first()
            session.add(entry)
        session.commit()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    with engine.begin() as connection:
        if DATABASE_URL.startswith("sqlite"):
            existing_indexes = set(
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'index' AND tbl_name = 'timeentry'"
                    )
                ).scalars()
            )
        else:
            existing_indexes = {
                item["name"] for item in inspect(connection).get_indexes("timeentry")
            }
        for table in (TimeEntry, Employee, Project):
            if DATABASE_URL.startswith("sqlite"):
                table_indexes = set(
                    connection.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'index' AND tbl_name = :table"
                        ),
                        {"table": table.__tablename__},
                    ).scalars()
                )
            else:
                table_indexes = {
                    item["name"]
                    for item in inspect(connection).get_indexes(table.__tablename__)
                }
            for index in table.__table__.indexes:
                if index.name not in table_indexes:
                    index.create(connection)
    _migrate_legacy_local_datetimes()
    _seed_defaults()


def open_session() -> Session:
    return Session(engine)
