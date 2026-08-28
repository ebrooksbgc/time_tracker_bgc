from streamlit.testing.v1 import AppTest


def test_app_loads_without_errors(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "app-test.db"
    monkeypatch.setenv(
        "TIME_TRACKER_DATABASE_URL", f"sqlite:///{database_path}"
    )
    monkeypatch.setenv("TIME_TRACKER_TIMEZONE", "America/Chicago")

    from database import create_db_and_tables, open_session
    from services import create_project

    create_db_and_tables()
    with open_session() as session:
        create_project(session, "Visible hour controls", work_type="Non-project")

    app = AppTest.from_file("../app.py", default_timeout=10).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Employee time tracker"]
    assert "Work as partner" in [item.label for item in app.selectbox]
    assert app.segmented_control[0].label == "View"
    assert app.segmented_control[0].options == [
        "My week",
        "Insights",
        "Timer",
        "Setup",
        "History",
        "Period close",
    ]
    next(button for button in app.button if button.label == "Add row").click().run()
    assert not app.exception
    for view in app.segmented_control[0].options[1:]:
        app.segmented_control[0].set_value(view).run()
        assert not app.exception


def test_timesheet_grid_has_inline_quarter_hour_controls() -> None:
    from timesheet_grid import _GRID_CSS, _GRID_JS

    assert 'el("button", "", "−")' in _GRID_JS
    assert 'el("button", "", "+")' in _GRID_JS
    assert 'input.type = "number"' in _GRID_JS
    assert 'input.step = "0.25"' in _GRID_JS
    assert 'input.min = "0"' in _GRID_JS
    assert 'appearance: textfield' in _GRID_CSS
    assert '::-webkit-inner-spin-button' in _GRID_CSS
