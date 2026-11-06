from datetime import timedelta
import json

from openpyxl import Workbook, load_workbook
import pytest

from process_automation import cli
from process_automation.database import Store
from process_automation.domain import moment
from process_automation.excel import IMPORT_COLUMNS, import_requests, safe, weekly_metrics, write_report
from conftest import create, move


def test_weekly_metrics_real_processing_time_and_historical_snapshot(lab, payload):
    first = create(lab, payload)
    start = lab.clock()
    first = move(lab, first, "in_review").json()
    lab.clock.advance(hours=2)
    first = move(lab, first, "approved").json()
    lab.clock.advance(hours=4)
    first = move(lab, first, "done", "mira").json()
    second = create(lab, {**payload, "department": "IT"})
    with lab.store.sessions() as session:
        metrics = weekly_metrics(session, lab.clock())
        assert metrics["average_processing_hours"] == 6
        assert metrics["completed_count"] == 1
        assert len(metrics["open"]) == 1
        assert metrics["departments"] == {"IT": 1, "Production": 1}
        old = weekly_metrics(session, start)
        assert old["average_processing_hours"] is None
        assert old["open"][0]["status"] == "in_review"
        lab.clock.advance(days=2)
        assert weekly_metrics(session, lab.clock())["overdue"][0]["id"] == second["id"]


def test_week_boundary_excludes_prior_completions(lab, payload):
    row = move(lab, create(lab, payload), "in_review").json()
    row = move(lab, row, "approved").json()
    lab.clock.advance(hours=2)
    move(lab, row, "done", "mira")
    lab.clock.advance(days=7)
    with lab.store.sessions() as session:
        metrics = weekly_metrics(session, lab.clock())
    assert metrics["departments"] == {} and metrics["average_processing_hours"] is None


def test_excel_report_values_format_chart_and_overdue(lab, payload, tmp_path):
    create(lab, payload)
    lab.clock.advance(days=2)
    path = tmp_path / "nested" / "weekly.xlsx"
    with lab.store.sessions() as session:
        metrics = write_report(session, path, lab.clock())
    assert len(metrics["overdue"]) == 1
    book = load_workbook(path)
    assert book.sheetnames == ["Weekly overview", "Open requests", "Overdue approvals", "Departments"]
    assert book["Weekly overview"]["B7"].value == 1
    assert book["Weekly overview"]["B10"].value == 1
    assert book["Weekly overview"]["B9"].value == "No completed requests"
    assert len(book["Weekly overview"].conditional_formatting) == 1
    assert len(book["Departments"]._charts) == 1
    assert book["Departments"]["A5"].value == "Production" and book["Departments"]["B5"].value == 1
    assert book["Open requests"]["G5"].value.tzinfo is None
    assert book["Open requests"]["G5"].number_format == "yyyy-mm-dd hh:mm"
    assert book["Open requests"].freeze_panes == "B5"
    assert not book["Open requests"].sheet_view.showGridLines


def test_empty_report_no_average_or_chart(lab, tmp_path):
    with lab.store.sessions() as session:
        write_report(session, tmp_path / "empty.xlsx", lab.clock())
    book = load_workbook(tmp_path / "empty.xlsx")
    assert book["Weekly overview"]["B7"].value == 0
    assert book["Departments"]._charts == []


def make_import(path, payload, rows):
    book = Workbook()
    book.active.append(IMPORT_COLUMNS)
    for values in rows:
        book.active.append([values.get(key) for key in IMPORT_COLUMNS] if values else [None] * 7)
    book.save(path)


def test_import_row_errors_continue_after_invalid_rows(lab, payload, tmp_path):
    path = tmp_path / "input.xlsx"
    naive = moment(payload["approval_deadline"]).replace(tzinfo=None)
    make_import(path, payload, [payload, {**payload, "department": "Invalid", "quantity": 0}, None,
        {**payload, "title": "Another synthetic tool", "approval_deadline": naive}, {**payload, "title": "=1+1"}])
    rows = import_requests(path, lab.service, lab.dispatcher, "mira")
    assert [row["status"] for row in rows] == ["created", "error", "skipped", "created", "error"]
    assert rows[1]["row"] == 3 and len(rows[1]["errors"]) == 2
    assert "department" in " ".join(rows[1]["errors"]) and "quantity" in " ".join(rows[1]["errors"])
    assert "Formulas" in rows[-1]["errors"][0]
    assert len(lab.api.get("/api/requests").json()) == 2


def test_import_header_errors_and_role_errors(lab, payload, tmp_path):
    path = tmp_path / "input.xlsx"
    book = Workbook()
    book.active.append(["bad headers"])
    book.save(path)
    with pytest.raises(ValueError, match="headers"):
        import_requests(path, lab.service, lab.dispatcher, "mira")
    make_import(path, payload, [payload])
    rows = import_requests(path, lab.service, lab.dispatcher, "nolan")
    assert rows[0]["status"] == "error" and "requester role" in rows[0]["errors"][0]


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1)", "-SUM(A1)", "@SUM(A1)"])
def test_formula_text_is_neutralized(value):
    assert safe(value) == "'" + value
    assert safe(2) == 2


def test_cli_report_import_remind_deliver(lab, payload, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configured_store", lambda: lab.store)
    monkeypatch.setattr(cli, "configured_dispatcher", lambda store: lab.dispatcher)
    monkeypatch.setattr(cli, "Service", lambda store: lab.service)
    path = tmp_path / "new.xlsx"
    make_import(path, payload, [payload, {**payload, "quantity": -1}])
    report = tmp_path / "rows.json"
    assert cli.main(["import-excel", str(path), "--out", str(report)]) == 1
    assert json.loads(report.read_text())[0]["status"] == "created"
    assert cli.main(["report", "--out", str(tmp_path / "weekly.xlsx"), "--as-of", lab.clock().isoformat()]) == 0
    assert cli.main(["remind", "--as-of", (lab.clock() + timedelta(days=2)).isoformat()]) == 0
    assert cli.main(["deliver"]) == 0
    assert cli.main(["report", "--out", str(tmp_path / "bad.xlsx"), "--as-of", "not a date"]) == 1
    assert "ERROR:" in capsys.readouterr().out
    make_import(path, payload, [payload])
    assert cli.main(["import-excel", str(path), "--out", str(report)]) == 0


def test_cli_missing_file_and_invalid_zip(lab, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "configured_store", lambda: lab.store)
    monkeypatch.setattr(cli, "configured_dispatcher", lambda store: lab.dispatcher)
    path = tmp_path / "missing.xlsx"
    assert cli.main(["import-excel", str(path), "--out", str(tmp_path / "rows.json")]) == 1
    path.write_text("not an Excel workbook")
    assert cli.main(["import-excel", str(path), "--out", str(tmp_path / "rows.json")]) == 1


@pytest.mark.parametrize("service,module", [("app", "app"), ("mock-graph", "mock_graph"), ("mock-teams", "mock_teams")])
def test_serve_configuration_without_opening_port(monkeypatch, service, module):
    called = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: called.append((args, kwargs)))
    assert cli.main(["serve", "--service", service, "--port", "8123"]) == 0
    assert called[0][0] == (f"process_automation.{module}:create_app",)
    assert called[0][1]["host"] == "127.0.0.1" and called[0][1]["factory"]


def test_cli_requires_command():
    with pytest.raises(SystemExit) as error:
        cli.main([])
    assert error.value.code == 2


def test_store_configured_environment(tmp_path, monkeypatch):
    from process_automation.database import configured_store
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///" + (tmp_path / "db.sqlite").as_posix())
    store = configured_store()
    assert (tmp_path / "db.sqlite").exists()
    store.engine.dispose()


def test_web_template_and_assets(lab):
    page = lab.api.get("/")
    assert page.status_code == 200 and "Request desk" in page.text
    assert "request-form" in page.text and "Synthetic lab identity" in page.text
    assert lab.api.get("/static/app.js").status_code == 200
    assert lab.api.get("/static/style.css").status_code == 200
    assert lab.api.delete("/api/requests/anything").status_code == 405


def test_file_store_can_create_directories(tmp_path):
    store = Store("sqlite:///" + (tmp_path / "nested" / "lab.sqlite").as_posix())
    store.engine.dispose()
    assert (tmp_path / "nested" / "lab.sqlite").exists()
