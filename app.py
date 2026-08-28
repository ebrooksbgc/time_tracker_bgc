import hashlib
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database import create_db_and_tables, open_session
from models import Project, Task, TimeEntry
from reference_import import import_reference_workbook
from services import (
    EDITABLE_TIMESHEET_STATUSES,
    MAX_DAILY_HOURS,
    accounting_period_for,
    active_timer,
    add_favorite,
    assign_project,
    clear_week,
    copy_previous_week,
    create_accounting_period,
    create_project,
    create_task,
    deactivate_employee,
    deactivate_project,
    delete_week_row,
    delete_entry,
    duration_between,
    entry_date_bounds,
    entries_between,
    expected_hours_for_week,
    fiscal_week_start,
    get_employee,
    get_employee_by_id,
    get_timesheet,
    list_accounting_periods,
    list_assignable_projects,
    list_employees,
    list_favorites,
    list_project_assignments,
    list_projects,
    list_tasks,
    holiday_dates_in_week,
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
from time_utils import utc_to_local
from timesheet_grid import timesheet_grid


st.set_page_config(page_title="Time Tracker", page_icon="⏱️", layout="wide")
create_db_and_tables()


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def project_map(projects: list[Project]) -> dict[int, Project]:
    return {project.id: project for project in projects if project.id is not None}


def entries_frame(
    entries: list[TimeEntry],
    projects: dict[int, Project],
    tasks: dict[int, Task],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    rows = []
    for entry in entries:
        project = projects.get(entry.project_id)
        started_at = utc_to_local(entry.started_at)
        ended_at = utc_to_local(entry.ended_at) if entry.ended_at else None
        duration_seconds = duration_between(entry, start_date, end_date)
        hours = duration_seconds / 3600
        rows.append(
            {
                "ID": entry.id,
                "Date": started_at.date(),
                "Project": project.name if project else "Deleted project",
                "Task": tasks[entry.task_id].name if entry.task_id in tasks else "General",
                "Work type": project.work_type if project else "Unknown",
                "Classification": (
                    entry.resolved_expense_type or "OpEx"
                ),
                "Business area": project.client if project else "",
                "Description": entry.description,
                "Start": started_at.strftime("%H:%M"),
                "End": ended_at.strftime("%H:%M") if ended_at else "Running",
                "Hours": round(hours, 2),
            }
        )
    return pd.DataFrame(rows)


def change_week(days: int) -> None:
    st.session_state.week_of += timedelta(days=days)


def weekly_editor_frame(
    projects: list[Project],
    tasks: list[Task],
    entries: list[TimeEntry],
    week_start: date,
    extra_rows: list[dict],
) -> pd.DataFrame:
    projects_by_id = project_map(projects)
    tasks_by_id = {task.id: task for task in tasks}
    entry_groups: dict[tuple[int, int | None, str], list[TimeEntry]] = {}
    for entry in entries:
        key = (
            entry.project_id,
            entry.task_id,
            entry.description,
        )
        entry_groups.setdefault(key, []).append(entry)

    rows = []
    row_groups = [
        {
            "project_id": project_id,
            "task_id": task_id,
            "notes": notes,
            "entries": related,
        }
        for (project_id, task_id, notes), related in entry_groups.items()
    ]
    existing_keys = {
        (group["project_id"], group["task_id"], group["notes"])
        for group in row_groups
    }
    for extra in extra_rows:
        key = (
            extra["project_id"],
            extra["task_id"],
            extra["notes"],
        )
        if key not in existing_keys:
            row_groups.append({**extra, "entries": []})
            existing_keys.add(key)

    for group in row_groups:
        project = projects_by_id.get(group["project_id"])
        task = tasks_by_id.get(group["task_id"])
        if project is None or task is None:
            continue
        related = group["entries"]
        manager_hands_on = any(entry.manager_hands_on for entry in related)
        row = {
            "Project ID": project.id,
            "Task ID": task.id,
            "Project": (
                f"{project.client} · {project.name}"
                if project.client
                else project.name
            ),
            "Task": task.name,
            "Classification": (
                "CapEx"
                if task.name.casefold() == "manager oversight" and manager_hands_on
                else ("OpEx" if task.name.casefold() == "manager oversight" else task.expense_type)
            ),
            "Hands-on capital": manager_hands_on,
            "Notes": group["notes"],
            "Original Notes": group["notes"],
            "Delete row": ":material/close:",
        }
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            row[day.strftime("%a %m/%d")] = round(
                sum(duration_between(entry, day, day) for entry in related) / 3600,
                2,
            )
        row["Total"] = round(
            sum(row[(week_start + timedelta(days=i)).strftime("%a %m/%d")] for i in range(7)),
            2,
        )
        rows.append(row)
    return pd.DataFrame(rows)


@st.dialog("Clear this week?", icon=":material/delete_sweep:")
def confirm_clear_week(week_start: date, employee_id: int) -> None:
    st.warning(
        f"This permanently deletes all entries from {week_start:%B %d} "
        f"through {(week_start + timedelta(days=6)):%B %d}."
    )
    confirmation = st.checkbox("I understand these entries cannot be recovered")
    if st.button(
        "Clear week",
        type="primary",
        disabled=not confirmation,
        icon=":material/delete_sweep:",
    ):
        try:
            with open_session() as dialog_session:
                deleted = clear_week(dialog_session, week_start, employee_id)
            st.session_state.week_extra_rows.pop(
                f"{employee_id}_{week_start.isoformat()}", None
            )
            st.toast(f"Cleared {deleted} time entr{'y' if deleted == 1 else 'ies'}.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))


logo_column, title_column = st.columns([1, 4], vertical_alignment="center")
with logo_column:
    st.image("BGC Logo.png", width=180)
with title_column:
    st.title("Employee time tracker")
    st.caption("Brookshire Grocery Company · AI hackathon prototype")

st.session_state.setdefault("week_of", fiscal_week_start(date.today()))
st.session_state.setdefault("week_extra_rows", {})

with open_session() as session:
    all_projects = list_projects(session, active_only=False)
    projects = list_projects(session)
    projects_by_id = project_map(all_projects)
    all_tasks = list_tasks(session, active_only=False)
    active_tasks = [task for task in all_tasks if task.active]
    tasks_by_id = {task.id: task for task in all_tasks}
    all_employees = list_employees(session)
    active_employees = [item for item in all_employees if item.active]
    directory_employees = [item for item in active_employees if item.partner_id]
    selectable_employees = directory_employees or active_employees
    if not selectable_employees:
        selectable_employees = [get_employee(session)]
    employee_labels = {
        item.id: (
            f"{item.name} · {item.partner_id} · {item.department}"
            if item.partner_id
            else item.name
        )
        for item in selectable_employees
    }
    valid_employee_ids = set(employee_labels)
    if st.session_state.get("selected_employee_id") not in valid_employee_ids:
        st.session_state.selected_employee_id = selectable_employees[0].id
    with st.sidebar:
        st.subheader("Partner")
        selected_employee_id = st.selectbox(
            "Work as partner",
            options=list(employee_labels),
            format_func=employee_labels.get,
            key="selected_employee_id",
            help="Timesheets, timers, insights, and history are scoped to this partner.",
        )
    employee = get_employee_by_id(session, selected_employee_id)
    projects = list_assignable_projects(session, employee.id)
    favorites = list_favorites(session, employee.id)
    favorite_keys = {(item.project_id, item.task_id) for item in favorites}
    running = active_timer(session, employee.id)

    if running:
        running_project = projects_by_id.get(running.project_id)
        with st.container(border=True):
            left, middle, right = st.columns([2, 2, 1])
            left.subheader(f"Running: {running_project.name if running_project else 'Unknown'}")
            left.caption(running.description or "No description")
            if running.task_id and running.task_id in tasks_by_id:
                left.caption(f"Task: {tasks_by_id[running.task_id].name}")
            middle.metric("Elapsed", format_duration(running.duration_seconds))
            if right.button("Stop timer", type="primary", width="stretch"):
                stop_timer(session, employee_id=employee.id)
                st.rerun()

    main_view_labels = {
        "My week": ":material/calendar_view_week: My week",
        "Insights": ":material/insights: Insights",
        "Timer": ":material/timer: Timer",
        "Setup": ":material/tune: Setup",
        "History": ":material/history: History",
        "Period close": ":material/event_busy: Period close",
    }
    main_view = st.segmented_control(
        "View",
        options=list(main_view_labels),
        default="My week",
        required=True,
        format_func=main_view_labels.get,
        key="main_view",
        label_visibility="collapsed",
        width="stretch",
    )

    if main_view == "My week":
      with st.container():
        week_start = fiscal_week_start(st.session_state.week_of)
        week_end = week_start + timedelta(days=6)
        timesheet = get_timesheet(session, week_start, employee.id)
        timesheet_editable = timesheet.status in EDITABLE_TIMESHEET_STATUSES
        week_periods = {
            period.id: period
            for offset in range(7)
            if (period := accounting_period_for(
                session, week_start + timedelta(days=offset)
            ))
        }
        week_entries = entries_between(session, week_start, week_end, employee.id)
        weekly_tasks = [
            task
            for task in all_tasks
            if task.active or any(entry.task_id == task.id for entry in week_entries)
        ]
        total_seconds = sum(
            duration_between(entry, week_start, week_end) for entry in week_entries
        )
        total_hours = total_seconds / 3600
        expected_hours = float(expected_hours_for_week(employee, week_start))
        standard_hours = float(employee.expected_weekly_hours)
        week_holidays = holiday_dates_in_week(week_start)
        deadline = submission_deadline(week_start)
        completion = min(total_hours / expected_hours, 1.0) if expected_hours else 1.0
        if total_hours < expected_hours:
            hours_status = "Not met"
        elif total_hours > expected_hours:
            hours_status = "Exceeded"
        else:
            hours_status = "Met"
        remaining_hours = max(expected_hours - total_hours, 0.0)
        exceeded_hours = max(total_hours - expected_hours, 0.0)

        detail = employee.department
        if employee.manager:
            detail += f" · Manager: {employee.manager}"
        deadline_label = f"Submission deadline: {deadline:%A, %B %d}"
        days_with_time = sum(
            any(
                duration_between(
                    entry,
                    week_start + timedelta(days=offset),
                    week_start + timedelta(days=offset),
                )
                for entry in week_entries
            )
            for offset in range(7)
            if (week_start + timedelta(days=offset)).weekday() < 5
        )

        st.subheader(f"{employee.name} · {week_start:%b %d}–{week_end:%b %d, %Y}")
        with st.container(horizontal=True, vertical_alignment="center"):
            st.button(
                "Previous week",
                icon=":material/chevron_left:",
                on_click=change_week,
                args=(-7,),
            )
            st.date_input(
                "Week",
                key="week_of",
                label_visibility="collapsed",
                width=145,
            )
            st.button(
                "Current week",
                icon=":material/today:",
                on_click=lambda: st.session_state.update(
                    week_of=fiscal_week_start(date.today())
                ),
            )
            st.button(
                "Next week",
                icon=":material/chevron_right:",
                on_click=change_week,
                args=(7,),
            )
            with st.popover("Week details", icon=":material/info:"):
                st.caption("Fiscal week runs Wednesday through Tuesday")
                st.write(detail)
                st.write(deadline_label)
                if week_holidays:
                    st.write(
                        "Holiday adjustment: "
                        + ", ".join(
                            f"{name} ({day:%a %m/%d})"
                            for day, name in week_holidays.items()
                        )
                    )
                if week_periods:
                    st.write(
                        "Accounting period: "
                        + ", ".join(
                            f"{period.name} ({period.status})"
                            for period in week_periods.values()
                        )
                    )

        with st.container(horizontal=True):
            st.metric(
                "Hours worked",
                f"{total_hours:.2f}",
                border=True,
                help="Total hours entered for the selected fiscal week.",
            )
            st.metric(
                "Hours remaining",
                f"{remaining_hours:.2f}",
                border=True,
                help="Weekly target hours that have not yet been worked.",
            )
            st.metric(
                "Hours exceeded",
                f"{exceeded_hours:.2f}",
                border=True,
                help="Hours entered above the weekly target.",
            )
            st.metric(
                "Weekly target",
                f"{expected_hours:.2f}",
                border=True,
                help="Holiday-adjusted target for this week.",
            )
        st.progress(
            completion,
            text=(
                f"{total_hours:.2f} / {expected_hours:.2f} hours · "
                f"{hours_status} · {timesheet.status} · {days_with_time}/5 workdays"
            ),
        )
        if timesheet.status != "Submitted" and date.today() >= deadline:
            st.error(f"{deadline_label} · This timesheet is due or past due.")
        if week_periods and any(
            period.status == "Locked" for period in week_periods.values()
        ):
            st.warning("This week includes a locked accounting period and cannot be edited.")

        expected_daily = standard_hours / 5 if standard_hours else 0
        daily_summary = []
        incomplete_days = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            hours = sum(
                duration_between(entry, day, day) for entry in week_entries
            ) / 3600
            target = (
                expected_daily
                if day.weekday() < 5 and day not in week_holidays
                else 0
            )
            status = "Complete" if hours >= target else "Needs time"
            daily_summary.append(
                {
                    "Day": day.strftime("%A %m/%d"),
                    "Hours": round(hours, 2),
                    "Expected": round(target, 2),
                    "Status": (
                        status
                        if target
                        else (week_holidays.get(day, "Weekend"))
                    ),
                }
            )
            if target and hours < target and day <= date.today():
                incomplete_days.append(day.strftime("%A"))
        if incomplete_days and timesheet_editable:
            st.warning("Time is incomplete for " + ", ".join(incomplete_days) + ".")

        row_state_key = f"{employee.id}_{week_start.isoformat()}"
        extra_rows = st.session_state.week_extra_rows.setdefault(row_state_key, [])

        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(
                "Copy previous week",
                icon=":material/content_copy:",
                disabled=not timesheet_editable,
                key=f"copy_week_{row_state_key}",
            ):
                copied = copy_previous_week(session, week_start, employee.id)
                st.toast(f"Copied {copied} time entries.")
                st.rerun()
            if st.button(
                "Clear week",
                icon=":material/delete_sweep:",
                disabled=(
                    not timesheet_editable
                    or not (week_entries or extra_rows)
                ),
                key=f"clear_week_{row_state_key}",
            ):
                confirm_clear_week(week_start, employee.id)

        editor_source = weekly_editor_frame(
            all_projects, weekly_tasks, week_entries, week_start, extra_rows
        )
        day_columns = [
            (week_start + timedelta(days=i)).strftime("%a %m/%d")
            for i in range(7)
        ]
        st.subheader("Enter hours", divider="gray")
        if timesheet_editable and projects:
            active_project_ids = {task.project_id for task in active_tasks}
            selectable_projects = [
                project for project in projects if project.id in active_project_ids
            ]
            selectable_projects.sort(
                key=lambda project: (
                    not any(key[0] == project.id for key in favorite_keys),
                    project.client.casefold(),
                    project.name.casefold(),
                )
            )
            project_labels = {
                project.id: (
                    ("★ " if any(key[0] == project.id for key in favorite_keys) else "")
                    + f"{project.client or 'Internal'} · {project.name}"
                )
                for project in selectable_projects
            }
            with st.container(horizontal=True, vertical_alignment="bottom"):
                selected_project_id = st.selectbox(
                    "Project",
                    list(project_labels),
                    format_func=project_labels.get,
                    key=f"week_add_project_{row_state_key}",
                )
                available_tasks = [
                    task
                    for task in active_tasks
                    if task.project_id == selected_project_id
                ]
                available_tasks.sort(
                    key=lambda task: (
                        (selected_project_id, task.id) not in favorite_keys,
                        task.name.casefold(),
                    )
                )
                task_labels = {
                    task.id: (
                        ("★ " if (selected_project_id, task.id) in favorite_keys else "")
                        + task.name
                    )
                    for task in available_tasks
                }
                selected_task_id = st.selectbox(
                    "Task code",
                    list(task_labels),
                    format_func=task_labels.get,
                    key=f"week_add_task_{row_state_key}",
                )
                row_notes = st.text_input(
                    "Notes",
                    placeholder="Optional work details",
                    key=f"week_add_notes_{row_state_key}",
                )
                is_favorite = (
                    selected_project_id,
                    selected_task_id,
                ) in favorite_keys
                favorite_enabled = st.toggle(
                    "★ Favorite" if is_favorite else "☆ Favorite",
                    value=is_favorite,
                    key=(
                        f"week_favorite_{employee.id}_"
                        f"{selected_project_id}_{selected_task_id}"
                    ),
                    help="Favorites appear first in the project and task menus.",
                )
                if favorite_enabled != is_favorite:
                    if favorite_enabled:
                        add_favorite(
                            session,
                            employee.id,
                            selected_project_id,
                            selected_task_id,
                        )
                        st.toast("Added to favorites.", icon=":material/star:")
                    else:
                        remove_favorite(
                            session,
                            employee.id,
                            selected_project_id,
                            selected_task_id,
                        )
                        st.toast("Removed from favorites.", icon=":material/star_border:")
                    st.rerun()
                if st.button(
                    "Add row",
                    icon=":material/add:",
                    type="primary" if editor_source.empty else "secondary",
                    key=f"week_add_button_{row_state_key}",
                ):
                    candidate = {
                        "project_id": selected_project_id,
                        "task_id": selected_task_id,
                        "notes": row_notes.strip(),
                    }
                    if candidate in extra_rows:
                        st.warning("That project, task, and notes row already exists.")
                    else:
                        extra_rows.append(candidate)
                        st.rerun()
        if editor_source.empty:
            st.info(
                "No work rows yet. Choose a project and task above or copy the previous "
                "week to begin."
            )
        else:
            show_row_details = st.toggle(
                "Show row details",
                value=False,
                key=f"week_show_details_{row_state_key}",
                help=(
                    "Show classification, notes, and capital handling."
                ),
            )
            st.caption(
                "Select a day cell, then type hours or use its up/down controls. "
                "Values move in 0.25-hour steps and cannot be negative."
            )
            visible_columns = [
                "Project",
                "Task",
                "Classification",
                "Notes",
                *day_columns,
                "Total",
                "Hands-on capital",
                "Delete row",
            ]
            hidden_columns = ["Project ID", "Task ID", "Original Notes"]
            editor_source = editor_source[visible_columns + hidden_columns]
            component_rows = []
            rows_by_id = {}
            for _, row in editor_source.iterrows():
                project_id = int(row["Project ID"])
                task_id = int(row["Task ID"])
                original_notes = str(row["Original Notes"] or "")
                identity = f"{project_id}|{task_id}|{original_notes}"
                row_id = hashlib.sha256(identity.encode()).hexdigest()[:12]
                hours = [
                    0.0 if pd.isna(row[column]) else float(row[column])
                    for column in day_columns
                ]
                rows_by_id[row_id] = {
                    "project_id": project_id,
                    "task_id": task_id,
                    "notes": original_notes,
                    "hours": hours,
                    "hands_on": bool(row["Hands-on capital"]),
                }
                component_rows.append(
                    {
                        "id": row_id,
                        "project": str(row["Project"]),
                        "task": str(row["Task"]),
                        "classification": str(row["Classification"]),
                        "notes": original_notes,
                        "hours": hours,
                        "handsOn": bool(row["Hands-on capital"]),
                        "managerOversight": (
                            str(row["Task"]).casefold() == "manager oversight"
                        ),
                    }
                )

            result = timesheet_grid(
                rows=component_rows,
                days=day_columns,
                editable=timesheet_editable,
                show_details=show_row_details,
                max_hours=float(MAX_DAILY_HOURS),
                key=f"timesheet_grid_{row_state_key}",
            )
            action = getattr(result, "action", None)
            try:
                if action and timesheet_editable:
                    row = rows_by_id[str(action["rowId"])]
                    if action["type"] == "hours":
                        offset = int(action["offset"])
                        value = float(action["value"])
                        set_daily_task_hours(
                            session,
                            row["project_id"],
                            row["task_id"],
                            week_start + timedelta(days=offset),
                            value,
                            row["notes"],
                            match_description=row["notes"],
                            manager_hands_on=row["hands_on"],
                            employee_id=employee.id,
                        )
                        extra_candidate = {
                            "project_id": row["project_id"],
                            "task_id": row["task_id"],
                            "notes": row["notes"],
                        }
                        if extra_candidate in extra_rows and value > 0:
                            extra_rows.remove(extra_candidate)
                        st.toast("Time updated.", icon=":material/cloud_done:")
                    elif action["type"] == "notes":
                        new_notes = str(action["notes"])
                        for offset, value in enumerate(row["hours"]):
                            if value > 0:
                                set_daily_task_hours(
                                    session,
                                    row["project_id"],
                                    row["task_id"],
                                    week_start + timedelta(days=offset),
                                    value,
                                    new_notes,
                                    match_description=row["notes"],
                                    manager_hands_on=row["hands_on"],
                                    employee_id=employee.id,
                                )
                    elif action["type"] == "handsOn":
                        new_hands_on = bool(action["value"])
                        for offset, value in enumerate(row["hours"]):
                            if value > 0:
                                set_daily_task_hours(
                                    session,
                                    row["project_id"],
                                    row["task_id"],
                                    week_start + timedelta(days=offset),
                                    value,
                                    row["notes"],
                                    match_description=row["notes"],
                                    manager_hands_on=new_hands_on,
                                    employee_id=employee.id,
                                )
                    elif action["type"] == "remove":
                        delete_week_row(
                            session,
                            week_start,
                            row["project_id"],
                            row["task_id"],
                            row["notes"],
                            employee.id,
                        )
                        extra_candidate = {
                            "project_id": row["project_id"],
                            "task_id": row["task_id"],
                            "notes": row["notes"],
                        }
                        if extra_candidate in extra_rows:
                            extra_rows.remove(extra_candidate)
                        st.toast("Work row removed.", icon=":material/delete:")
                    st.rerun()
            except ValueError as error:
                st.error(str(error))

            st.caption(
                "Hours save automatically. Use **Show row details** to edit notes."
            )
            with st.expander("Daily completion details"):
                st.dataframe(
                    daily_summary,
                    hide_index=True,
                    column_config={
                        "Hours": st.column_config.NumberColumn(format="%.2f h"),
                        "Expected": st.column_config.NumberColumn(format="%.2f h"),
                    },
                )

            with st.bottom:
              with st.container(horizontal=True, vertical_alignment="center"):
                if timesheet_editable:
                    if st.button(
                        "Submit week",
                        icon=":material/send:",
                        disabled=total_hours == 0,
                    ):
                        try:
                            submit_timesheet(session, week_start, employee.id)
                            st.rerun()
                        except ValueError as error:
                            st.error(str(error))
                elif (
                    timesheet.status == "Submitted"
                    and st.button("Recall timesheet", icon=":material/edit:")
                ):
                    recall_timesheet(session, week_start, employee.id)
                    st.rerun()

    if main_view == "Insights":
      with st.container():
        insight_week_start = fiscal_week_start(st.session_state.week_of)
        insight_week_end = insight_week_start + timedelta(days=6)
        insight_entries = entries_between(
            session, insight_week_start, insight_week_end, employee.id
        )
        insight_timesheet = get_timesheet(
            session, insight_week_start, employee.id
        )
        expected_hours = float(expected_hours_for_week(employee, insight_week_start))
        total_hours = sum(
            duration_between(entry, insight_week_start, insight_week_end)
            for entry in insight_entries
        ) / 3600
        difference = total_hours - expected_hours

        project_hours: dict[str, float] = {}
        task_hours: dict[str, float] = {}
        work_type_hours = {"Project": 0.0, "Non-project": 0.0}
        expense_hours = {"CapEx": 0.0, "OpEx": 0.0}
        for entry in insight_entries:
            hours = duration_between(
                entry, insight_week_start, insight_week_end
            ) / 3600
            project = projects_by_id.get(entry.project_id)
            task = tasks_by_id.get(entry.task_id)
            project_name = project.name if project else "Unknown project"
            task_name = task.name if task else "General"
            project_hours[project_name] = project_hours.get(project_name, 0) + hours
            task_label = f"{project_name} · {task_name}"
            task_hours[task_label] = task_hours.get(task_label, 0) + hours
            work_type_hours[project.work_type if project else "Project"] += hours
            expense_hours[entry.resolved_expense_type or "OpEx"] += hours

        primary_project = (
            max(project_hours, key=project_hours.get) if project_hours else "No time yet"
        )
        projects_worked = len(project_hours)
        if difference < 0:
            target_label = "Remaining"
            target_value = f"{abs(difference):.2f} h"
        elif difference > 0:
            target_label = "Over target"
            target_value = f"{difference:.2f} h"
        else:
            target_label = "Weekly target"
            target_value = "Complete"
        st.subheader(f"Week of {insight_week_start:%B %d, %Y}")
        st.caption(
            f"Timesheet status: {insight_timesheet.status} · "
            "Insights follow the week selected in My week."
        )

        with st.container(horizontal=True):
            st.metric("Hours recorded", f"{total_hours:.2f} h", border=True)
            st.metric(
                target_label,
                target_value,
                border=True,
            )
            st.metric("Projects worked", projects_worked, border=True)
            st.metric("Primary focus", primary_project, border=True)
        with st.container(horizontal=True):
            st.metric("Project hours", f"{work_type_hours['Project']:.2f} h", border=True)
            st.metric(
                "Support / non-project",
                f"{work_type_hours['Non-project']:.2f} h",
                border=True,
            )
            st.metric("Capital (CapEx)", f"{expense_hours['CapEx']:.2f} h", border=True)
            st.metric("Operating (OpEx)", f"{expense_hours['OpEx']:.2f} h", border=True)

        standard_daily = float(employee.expected_weekly_hours) / 5 if employee.expected_weekly_hours else 0
        insight_holidays = holiday_dates_in_week(insight_week_start)
        daily_rows = []
        for offset in range(7):
            day = insight_week_start + timedelta(days=offset)
            hours = sum(
                duration_between(entry, day, day) for entry in insight_entries
            ) / 3600
            daily_rows.append(
                {
                    "Day": day.strftime("%a %m/%d"),
                    "Hours": round(hours, 2),
                    "Expected": round(
                        standard_daily
                        if day.weekday() < 5 and day not in insight_holidays
                        else 0,
                        2,
                    ),
                }
            )

        chart_left, chart_right = st.columns(2)
        with chart_left.container(border=True, height="stretch"):
            st.subheader("Daily completion")
            st.bar_chart(pd.DataFrame(daily_rows), x="Day", y=["Hours", "Expected"])
        with chart_right.container(border=True, height="stretch"):
            st.subheader("Hours by project")
            if project_hours:
                project_frame = pd.DataFrame(
                    [
                        {"Project": name, "Hours": round(hours, 2)}
                        for name, hours in sorted(
                            project_hours.items(), key=lambda item: item[1], reverse=True
                        )
                    ]
                )
                st.bar_chart(
                    project_frame, x="Project", y="Hours", horizontal=True
                )
            else:
                st.info("No project time recorded for this week.")

        st.subheader("Task breakdown")
        if task_hours:
            task_frame = pd.DataFrame(
                [
                    {"Project and task": name, "Hours": round(hours, 2)}
                    for name, hours in sorted(
                        task_hours.items(), key=lambda item: item[1], reverse=True
                    )
                ]
            )
            st.dataframe(
                task_frame,
                hide_index=True,
                column_config={
                    "Hours": st.column_config.NumberColumn(format="%.2f h")
                },
            )
        else:
            st.info("Add time in My week to see task-level insights.")

        classification_frame = pd.DataFrame(
            [
                {"Classification": label, "Hours": round(hours, 2)}
                for label, hours in expense_hours.items()
            ]
        )
        st.subheader("Capital versus operating")
        st.bar_chart(classification_frame, x="Classification", y="Hours")

    if main_view == "Timer":
      with st.container():
        st.subheader("Start a timer")
        if not projects:
            st.info("Create an active project before starting a timer.")
        elif running:
            st.warning("A timer is already running. Stop it before starting another.")
            if st.button("Refresh elapsed time"):
                st.rerun()
        else:
            active_project_ids = {project.id for project in projects}
            assignments = {
                (task.project_id, task.id): (
                    f"{projects_by_id[task.project_id].client or 'Internal'} · "
                    f"{projects_by_id[task.project_id].name} · {task.name}"
                )
                for task in active_tasks
                if task.project_id in active_project_ids
            }
            with st.form("start_timer"):
                assignment = st.selectbox(
                    "Project and task",
                    options=list(assignments),
                    format_func=assignments.get,
                )
                description = st.text_input("What are you working on?")
                timer_task = tasks_by_id.get(assignment[1]) if assignment else None
                timer_hands_on = st.checkbox(
                    "Hands-on contribution to a capital deliverable",
                    disabled=(
                        timer_task is None
                        or timer_task.name.casefold() != "manager oversight"
                    ),
                    help=(
                        "Manager Oversight normally remains OpEx. Select this only "
                        "when the work directly contributes to a capital deliverable."
                    ),
                )
                submitted = st.form_submit_button("Start timer", type="primary")
                if submitted:
                    try:
                        start_timer(
                            session,
                            assignment[0],
                            description,
                            task_id=assignment[1],
                            manager_hands_on=timer_hands_on,
                            employee_id=employee.id,
                        )
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

    if main_view == "Setup":
      with st.container():
        st.subheader("Reference data")
        workbook_path = "IT Hackathon Workbook.xlsx"
        if st.button(
            "Import official hackathon workbook",
            icon=":material/upload_file:",
            type="primary",
        ):
            try:
                summary = import_reference_workbook(session, workbook_path)
                st.session_state.reference_import_summary = {
                    "changed": summary.changed_records,
                    "employees": summary.employees_created,
                    "projects": summary.projects_created,
                    "tasks": summary.tasks_created,
                    "periods": summary.periods_created,
                    "warnings": summary.warnings,
                }
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(str(error))
        import_summary = st.session_state.pop("reference_import_summary", None)
        if import_summary:
            st.success(
                "Workbook import complete: "
                f"{import_summary['employees']} new partners, "
                f"{import_summary['projects']} new projects/categories, "
                f"{import_summary['tasks']} new task codes, and "
                f"{import_summary['periods']} new fiscal periods."
            )
            for warning in import_summary["warnings"]:
                st.warning(warning)

        st.subheader("Employee setup")
        with st.expander("Employee profile"):
            with st.form("employee_profile"):
                employee_name = st.text_input("Employee name", value=employee.name)
                department = st.text_input("Department", value=employee.department)
                manager = st.text_input("Manager", value=employee.manager)
                email = st.text_input("Email", value=employee.email)
                job_title = st.text_input("Job title", value=employee.job_title)
                engagement_type = st.selectbox(
                    "Engagement type",
                    ["Full-time", "Part-time", "Contractor"],
                    index=["Full-time", "Part-time", "Contractor"].index(
                        employee.engagement_type
                        if employee.engagement_type
                        in {"Full-time", "Part-time", "Contractor"}
                        else "Full-time"
                    ),
                )
                expected = st.number_input(
                    "Expected weekly hours",
                    min_value=0.0,
                    max_value=168.0,
                    value=float(employee.expected_weekly_hours),
                    step=1.0,
                )
                if st.form_submit_button("Save employee", type="primary"):
                    try:
                        update_employee(
                            session,
                            employee_name,
                            department,
                            manager,
                            expected,
                            email=email,
                            job_title=job_title,
                            engagement_type=engagement_type,
                            employee_id=employee.id,
                        )
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

        st.subheader("Reactivate records")
        st.caption(
            "Reactivation restores an existing record for future time entry "
            "without changing its history or identifier."
        )
        reactivate_type = st.segmented_control(
            "Record type to reactivate",
            ["Project", "Partner"],
            default="Project",
            key="reactivate_record_type",
        )
        if reactivate_type == "Project":
            inactive_project_labels = {
                project.id: (
                    f"{project.name} — {project.client}"
                    if project.client
                    else project.name
                )
                for project in all_projects
                if not project.active
            }
            if inactive_project_labels:
                reactivate_id = st.selectbox(
                    "Inactive project",
                    list(inactive_project_labels),
                    format_func=inactive_project_labels.get,
                    key="project_to_reactivate",
                )
                if st.button(
                    "Reactivate project",
                    icon=":material/refresh:",
                    key="reactivate_project_button",
                ):
                    try:
                        reactivate_project(session, reactivate_id)
                        st.toast("Project reactivated.", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
            else:
                st.caption("There are no inactive projects to reactivate.")
        else:
            inactive_partner_labels = {
                item.id: (
                    f"{item.name} · {item.partner_id}"
                    if item.partner_id
                    else item.name
                )
                for item in all_employees
                if not item.active
            }
            if inactive_partner_labels:
                reactivate_id = st.selectbox(
                    "Inactive partner",
                    list(inactive_partner_labels),
                    format_func=inactive_partner_labels.get,
                    key="partner_to_reactivate",
                )
                if st.button(
                    "Reactivate partner",
                    icon=":material/person_add:",
                    key="reactivate_partner_button",
                ):
                    try:
                        reactivate_employee(session, reactivate_id)
                        st.toast("Partner reactivated.", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
            else:
                st.caption("There are no inactive partners to reactivate.")

        assignable_registry = [
            item
            for item in all_projects
            if item.active and item.work_type == "Project"
        ]
        with st.expander("Partner project assignments"):
            current_assignments = list_project_assignments(session, employee.id)
            current_active_ids = {
                item.project_id for item in current_assignments if item.active
            }
            if current_assignments:
                st.dataframe(
                    [
                        {
                            "Project": projects_by_id[item.project_id].name,
                            "Active": item.active,
                            "Assigned by": item.assigned_by,
                            "Assigned at": item.assigned_at,
                        }
                        for item in current_assignments
                        if item.project_id in projects_by_id
                    ],
                    hide_index=True,
                )
            available_for_assignment = [
                item for item in assignable_registry if item.id not in current_active_ids
            ]
            if available_for_assignment:
                assignment_labels = {
                    item.id: f"{item.identifier} · {item.name}"
                    for item in available_for_assignment
                }
                with st.form("add_project_assignment"):
                    new_assignment_id = st.selectbox(
                        "Assign project",
                        list(assignment_labels),
                        format_func=assignment_labels.get,
                    )
                    assignment_actor = st.text_input(
                        "Assigned by", value="Administrator"
                    )
                    if st.form_submit_button("Add assignment"):
                        assign_project(
                            session,
                            employee.id,
                            new_assignment_id,
                            assignment_actor,
                        )
                        st.rerun()
            else:
                st.caption("All active projects are already assigned.")

        st.subheader("Projects and tasks")
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Project name")
            client = st.text_input("Business area")
            identifier = st.text_input("Project identifier")
            project_type = st.text_input("Project type")
            project_manager = st.text_input("Project manager")
            fiscal_year = st.text_input("Fiscal year", placeholder="FY27")
            work_type = st.segmented_control(
                "Work type", ["Project", "Non-project"], default="Project"
            )
            cost_type = st.segmented_control(
                "Cost type", ["Capital", "Operating", "Mixed"], default="Mixed"
            )
            submitted = st.form_submit_button("Create project", type="primary")
            if submitted:
                try:
                    create_project(
                        session,
                        name,
                        client,
                        work_type,
                        identifier=identifier,
                        project_type=project_type,
                        project_manager=project_manager,
                        fiscal_year=fiscal_year,
                        cost_type=cost_type,
                    )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

        if all_projects:
            project_labels = {
                project.id: (
                    f"{project.name} — {project.client}"
                    if project.client
                    else project.name
                )
                for project in all_projects
            }
            with st.form("new_task", clear_on_submit=True):
                task_project_id = st.selectbox(
                    "Project for task",
                    list(project_labels),
                    format_func=project_labels.get,
                )
                task_name = st.text_input("Task name")
                selected_project = projects_by_id.get(task_project_id)
                task_expense_type = st.segmented_control(
                    "Financial classification",
                    ["CapEx", "OpEx"],
                    default="OpEx",
                    disabled=(
                        selected_project is not None
                        and selected_project.work_type == "Non-project"
                    ),
                )
                use_helper = st.checkbox(
                    "Use classification helper suggestion",
                    disabled=(
                        selected_project is not None
                        and selected_project.work_type == "Non-project"
                    ),
                )
                st.caption(
                    "The helper reviews task wording for potential asset-creation work. "
                    "Non-project time is always OpEx."
                )
                if st.form_submit_button("Add task", icon=":material/add:"):
                    try:
                        suggestion, rationale = suggest_expense_type(
                            task_name,
                            selected_project.work_type if selected_project else "Project",
                        )
                        create_task(
                            session,
                            task_project_id,
                            task_name,
                            suggestion if use_helper else (task_expense_type or "OpEx"),
                        )
                        if use_helper:
                            st.toast(f"Helper selected {suggestion}: {rationale}")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

        if all_projects:
            project_rows = [
                {
                    "Project": project.name,
                    "Business area": project.client,
                    "Work type": project.work_type,
                    "Identifier": project.identifier,
                    "Type": project.project_type,
                    "Status": project.status,
                    "Project manager": project.project_manager,
                    "Fiscal year": project.fiscal_year,
                    "Cost type": project.cost_type,
                    "Active": project.active,
                    "Tasks": ", ".join(
                        f"{task.name} ({task.expense_type})"
                        for task in all_tasks
                        if task.project_id == project.id and task.active
                    ),
                }
                for project in all_projects
            ]
            st.dataframe(project_rows, width="stretch", hide_index=True)

        st.subheader("Deactivate records")
        st.caption(
            "Deactivation preserves time entries and referential integrity. "
            "Inactive records are hidden from future time entry."
        )
        record_type = st.segmented_control(
            "Record type",
            ["Project", "Partner"],
            default="Project",
            key="deactivate_record_type",
        )
        if record_type == "Project":
            active_project_labels = {
                project.id: (
                    f"{project.name} — {project.client}"
                    if project.client
                    else project.name
                )
                for project in all_projects
                if project.active
            }
            if active_project_labels:
                deactivate_id = st.selectbox(
                    "Active project",
                    list(active_project_labels),
                    format_func=active_project_labels.get,
                    key="project_to_deactivate",
                )
                related_count = project_entry_count(session, deactivate_id)
                st.caption(
                    f"{related_count} existing time "
                    f"entr{'y' if related_count == 1 else 'ies'} will be preserved."
                )
                confirm_deactivate = st.checkbox(
                    "I understand this project will be unavailable for new time",
                    key="confirm_project_deactivation",
                )
                if st.button(
                    "Deactivate project",
                    icon=":material/block:",
                    disabled=not confirm_deactivate,
                    key="deactivate_project_button",
                ):
                    try:
                        deactivate_project(session, deactivate_id)
                        st.toast("Project deactivated; existing entries were preserved.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
            else:
                st.caption("There are no active projects to deactivate.")
        else:
            partner_labels = {
                item.id: (
                    f"{item.name} · {item.partner_id}"
                    if item.partner_id
                    else item.name
                )
                for item in active_employees
            }
            if partner_labels:
                deactivate_id = st.selectbox(
                    "Active partner",
                    list(partner_labels),
                    format_func=partner_labels.get,
                    key="partner_to_deactivate",
                )
                st.caption(
                    "The partner's historical entries and timesheets will be preserved."
                )
                confirm_deactivate = st.checkbox(
                    "I understand this partner will be unavailable for new time",
                    key="confirm_partner_deactivation",
                )
                if st.button(
                    "Deactivate partner",
                    icon=":material/person_off:",
                    disabled=not confirm_deactivate,
                    key="deactivate_partner_button",
                ):
                    try:
                        deactivate_employee(session, deactivate_id)
                        st.toast("Partner deactivated; existing entries were preserved.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

    if main_view == "Period close":
      with st.container():
        st.subheader("Accounting period close")
        st.caption(
            "Create periods from the provided fiscal calendar, allow corrections, "
            "then lock the period to prevent further edits."
        )
        with st.container(horizontal=True):
            for fiscal_year in ("FY26", "FY27"):
                if st.button(
                    f"Load {fiscal_year} published calendar",
                    key=f"seed_{fiscal_year}",
                    icon=":material/calendar_month:",
                ):
                    try:
                        added = seed_published_fiscal_calendar(session, fiscal_year)
                        st.toast(f"Added {added} {fiscal_year} fiscal periods.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

        employees = list_employees(session)
        if employees:
            with st.expander(f"Partner directory ({len(employees)} records)"):
                st.dataframe(
                    [
                        {
                            "Partner ID": item.partner_id,
                            "Name": item.name,
                            "Role": item.job_title,
                            "Team": item.department,
                            "Email": item.email,
                            "Employment": item.engagement_type,
                            "Status": "Active" if item.active else "Inactive",
                        }
                        for item in employees
                    ],
                    hide_index=True,
                )
        periods = list_accounting_periods(session)
        with st.form("new_period", clear_on_submit=True):
            period_name = st.text_input("Period name", placeholder="FY26 period 01")
            period_start = st.date_input("Start date", key="period_start")
            period_end = st.date_input("End date", key="period_end")
            if st.form_submit_button("Create period", icon=":material/calendar_add_on:"):
                try:
                    create_accounting_period(
                        session, period_name, period_start, period_end
                    )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

        if periods:
            st.dataframe(
                [
                    {
                        "Period": period.name,
                        "Fiscal year": period.fiscal_year,
                        "Quarter": period.quarter,
                        "Period number": period.period_number,
                        "Weeks": period.week_count,
                        "Start": period.start_date,
                        "End": period.end_date,
                        "Status": period.status,
                        "Correction deadline": period.correction_deadline,
                    }
                    for period in periods
                ],
                hide_index=True,
            )
            period_labels = {
                period.id: f"{period.name} · {period.start_date} to {period.end_date}"
                for period in periods
            }
            with st.form("period_status"):
                selected_period_id = st.selectbox(
                    "Accounting period", list(period_labels), format_func=period_labels.get
                )
                new_status = st.segmented_control(
                    "Next status", ["Open", "Correction", "Locked"], default="Correction"
                )
                correction_deadline = st.date_input("Correction deadline")
                if st.form_submit_button("Update period", type="primary"):
                    try:
                        set_accounting_period_status(
                            session,
                            selected_period_id,
                            new_status,
                            correction_deadline if new_status == "Correction" else None,
                        )
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
        else:
            st.info("Create the first accounting period to enable period locking.")

    if main_view == "History":
      with st.container():
        st.subheader("Entry history")
        history_employees = [
            item for item in list_employees(session) if item.partner_id
        ] or [employee]
        history_labels = {
            item.id: (
                f"{item.name} · {item.partner_id} · "
                f"{'Active' if item.active else 'Inactive'}"
            )
            for item in history_employees
        }
        history_employee_id = st.selectbox(
            "Partner history",
            list(history_labels),
            index=list(history_labels).index(employee.id)
            if employee.id in history_labels
            else 0,
            format_func=history_labels.get,
            key="history_employee_id",
        )
        history_employee = get_employee_by_id(session, history_employee_id)
        _, latest_entry_date = entry_date_bounds(session, history_employee.id)
        default_end = max(date.today(), latest_entry_date or date.today())
        left, right = st.columns(2)
        start_date = left.date_input("From", value=date.today() - timedelta(days=6))
        end_date = right.date_input("Through", value=default_end)

        if start_date > end_date:
            st.error("The start date must be before the end date.")
        else:
            entries = entries_between(
                session, start_date, end_date, history_employee.id
            )
            frame = entries_frame(
                entries, projects_by_id, tasks_by_id, start_date, end_date
            )
            if frame.empty:
                st.info("No entries found for this date range.")
            else:
                st.dataframe(frame, width="stretch", hide_index=True)
                st.download_button(
                    "Export CSV",
                    frame.to_csv(index=False).encode("utf-8"),
                    file_name=f"time-entries-{start_date}-{end_date}.csv",
                    mime="text/csv",
                )

                entry_labels = {
                    entry.id: (
                        f"#{entry.id} · {utc_to_local(entry.started_at):%Y-%m-%d} · "
                        f"{projects_by_id.get(entry.project_id).name if projects_by_id.get(entry.project_id) else 'Unknown'}"
                    )
                    for entry in entries
                }
                if not history_employee.active:
                    st.caption("Inactive partner history is read-only.")
                else:
                    with st.expander("Delete an entry"):
                        entry_id = st.selectbox(
                            "Entry",
                            list(entry_labels),
                            format_func=entry_labels.get,
                        )
                        confirm = st.checkbox("I understand this cannot be undone")
                        if st.button("Delete selected entry", disabled=not confirm):
                            delete_entry(session, entry_id)
                            st.rerun()
