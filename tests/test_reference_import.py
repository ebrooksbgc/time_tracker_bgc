from pathlib import Path

from sqlalchemy import event, func
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import AccountingPeriod, Employee, Project, ProjectAssignment, Task
from reference_import import import_reference_workbook


WORKBOOK = Path(__file__).resolve().parents[1] / "IT Hackathon Workbook.xlsx"


def test_reference_workbook_import_is_complete_and_idempotent() -> None:
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
        first = import_reference_workbook(session, WORKBOOK)
        assert first.employees_created == 132
        assert first.projects_created == 25
        assert first.tasks_created == 251
        assert first.periods_created == 24
        assert first.assignments_created > 0
        assert any("duplicate EMP0125" in warning for warning in first.warnings)
        assert any("duplicate EMP0126" in warning for warning in first.warnings)
        assert any("duplicate EMP0128" in warning for warning in first.warnings)

        assert session.exec(select(func.count()).select_from(Employee)).one() == 132
        assert session.exec(select(func.count()).select_from(Project)).one() == 25
        assert session.exec(select(func.count()).select_from(Task)).one() == 251
        assert (
            session.exec(select(func.count()).select_from(AccountingPeriod)).one()
            == 24
        )

        second = import_reference_workbook(session, WORKBOOK)
        assert second.employees_created == 0
        assert second.projects_created == 0
        assert second.tasks_created == 0
        assert second.periods_created == 0
        assert session.exec(select(func.count()).select_from(Employee)).one() == 132
        assert session.exec(select(func.count()).select_from(Project)).one() == 25
        assert session.exec(select(func.count()).select_from(Task)).one() == 251

        inactive_projects = session.exec(
            select(Project).where(Project.active.is_(False))
        ).all()
        assert len(inactive_projects) == 4
        manager_oversight = session.exec(
            select(Task).where(Task.name == "Manager Oversight")
        ).all()
        assert len(manager_oversight) == 22
        assert {task.expense_type for task in manager_oversight} == {"OpEx"}

        aria = session.exec(select(Employee).where(Employee.partner_id == "EMP0078")).one()
        ana = session.exec(select(Employee).where(Employee.partner_id == "EMP0059")).one()
        project_11 = session.exec(select(Project).where(Project.identifier == "11")).one()
        project_24 = session.exec(select(Project).where(Project.identifier == "24")).one()
        assert session.exec(
            select(ProjectAssignment).where(
                ProjectAssignment.employee_id == aria.id,
                ProjectAssignment.project_id == project_11.id,
                ProjectAssignment.active.is_(True),
            )
        ).first()
        assert session.exec(
            select(ProjectAssignment).where(
                ProjectAssignment.employee_id == ana.id,
                ProjectAssignment.project_id == project_24.id,
                ProjectAssignment.active.is_(True),
            )
        ).first() is None
