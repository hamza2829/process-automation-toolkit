"""Real HTTP and CLI process exercise, entirely on the GitHub runner."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from openpyxl import Workbook, load_workbook
from playwright.sync_api import sync_playwright

from process_automation.excel import IMPORT_COLUMNS
from process_automation.integrations import GraphClient, validate_card

root = Path("artifacts").resolve()
root.mkdir(exist_ok=True)
env = {**os.environ, "LAB_NOW": "2026-11-02T09:00:00Z", "APP_DATABASE_URL": "sqlite:///" + (root / "app.sqlite").as_posix(),
    "GRAPH_DATABASE_URL": "sqlite:///" + (root / "graph.sqlite").as_posix(), "TEAMS_DATABASE_URL": "sqlite:///" + (root / "teams.sqlite").as_posix(),
    "GRAPH_BASE_URL": "http://127.0.0.1:8011/v1.0/sites/lab/lists/requests", "GRAPH_TOKEN": "synthetic-lab-token", "TEAMS_WEBHOOK_URL": "http://127.0.0.1:8012/webhook"}
processes, logs = [], []


def cli(*arguments, expected=0):
    result = subprocess.run([sys.executable, "-m", "process_automation.cli", *arguments], env=env, text=True, capture_output=True)
    print(result.stdout, flush=True)
    assert result.returncode == expected, result.stderr + result.stdout
    return result.stdout


def start(service, port):
    output = (root / f"{service}.log").open("w")
    logs.append(output)
    process = subprocess.Popen([sys.executable, "-m", "process_automation.cli", "serve", "--service", service, "--port", str(port)], env=env, stdout=output, stderr=subprocess.STDOUT)
    processes.append(process)
    for _ in range(100):
        assert process.poll() is None, f"{service} exited before startup"
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{service} did not become ready")


try:
    start("mock-graph", 8011)
    start("mock-teams", 8012)
    start("app", 8000)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as api:
        payload = {"title": "Synthetic calibration tool", "category": "tool", "department": "Production", "quantity": 2,
            "cost_eur": "45.50", "justification": "Synthetic validation in the fictional assembly cell.", "approval_deadline": "2026-11-03T09:00:00Z"}

        def create(title):
            result = api.post("/api/requests", json={**payload, "title": title})
            assert result.status_code == 201, result.text
            assert result.json()["pending_deliveries"] == 0
            return result.json()

        def move(row, status, who="nolan", comment=""):
            result = api.patch(f"/api/requests/{row['id']}/status", headers={"X-Lab-User": who}, json={"version": row["version"], "status": status, "comment": comment})
            assert result.status_code == 200, result.text
            return result.json()

        first = create("Synthetic calibration tool")
        blocked = api.patch(f"/api/requests/{first['id']}/status", json={"status": "in_review", "version": 1})
        assert blocked.status_code == 403
        first = move(first, "in_review")
        first = move(first, "approved", comment="Synthetic trial approved")
        first = move(first, "done", "mira")
        second = move(create("Synthetic material replenishment"), "in_review")
        second = move(second, "rejected", comment="Synthetic stock is already available")
        third = create("Synthetic software license")
        events = api.get(f"/api/requests/{first['id']}/history").json()
        assert [row["to_status"] for row in events] == ["new", "in_review", "approved", "done"]
        graph = GraphClient(env["GRAPH_BASE_URL"], env["GRAPH_TOKEN"])
        assert len(graph.items(page_size=1)) == 3
        assert graph.items("fields/Status eq 'new'")[0]["fields"]["RequestId"] == third["id"]

        # Browser creates and approves another request through the actual web page.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto("http://127.0.0.1:8000")
            page.locator("#title").fill("Synthetic browser tool")
            page.locator("#justification").fill("Synthetic browser acceptance check for the lab.")
            page.locator("#deadline").fill("2026-11-03T09:00")
            page.screenshot(path=str(root / "request-form.png"), full_page=True)
            page.get_by_role("button", name="Submit request").click()
            page.get_by_role("status").filter(has_text="Request created").wait_for()
            page.select_option("#identity", "nolan")
            article = page.locator("article").filter(has_text="Synthetic browser tool")
            article.get_by_role("button", name="Start review").click()
            article.get_by_role("button", name="Approve", exact=True).click()
            article.locator(".badge.approved").wait_for()
            article.get_by_role("button", name="History").click()
            page.locator("#history table").wait_for()
            page.select_option("#status-filter", "approved")
            page.wait_for_function("document.querySelectorAll('article').length === 1")
            page.screenshot(path=str(root / "web-page.png"), full_page=True)
            assert errors == [], errors
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(root / "web-page-mobile.png"), full_page=True)
            browser.close()

        # Two valid rows, one invalid row, an empty row, and a rejected formula.
        book = Workbook()
        book.active.append(IMPORT_COLUMNS)
        for values in [payload, {**payload, "department": "Unknown", "quantity": 0}, None,
                {**payload, "title": "Synthetic office material", "department": "Office"}, {**payload, "title": "=1+1"}]:
            book.active.append([values[key] for key in IMPORT_COLUMNS] if values else [None] * 7)
        source = root / "new-requests.xlsx"
        book.save(source)
        cli("import-excel", str(source), "--out", str(root / "import-results.json"), expected=1)
        results = json.loads((root / "import-results.json").read_text())
        assert [row["status"] for row in results] == ["created", "error", "skipped", "created", "error"]
        assert len(results[1]["errors"]) == 2
        reminders = json.loads(cli("remind", "--as-of", "2026-11-05T09:00:00Z"))
        assert reminders["queued"] == 3
        assert json.loads(cli("remind", "--as-of", "2026-11-05T10:00:00Z"))["queued"] == 0
        cli("deliver")
        cli("report", "--out", str(root / "weekly-report.xlsx"), "--as-of", "2026-11-05T09:00:00Z")
        report = load_workbook(root / "weekly-report.xlsx")
        assert report["Weekly overview"]["B7"].value == 4  # Three pending plus the approved browser request.
        assert report["Weekly overview"]["B10"].value == 3
        assert report["Weekly overview"]["B9"].value == 0  # Fixed synthetic clock; the unit test independently proves six hours.
        assert len(report["Departments"]._charts) == 1
        messages = httpx.get("http://127.0.0.1:8012/messages").json()
        assert all(validate_card(message["payload"]) for message in messages)
        notification_events = [message["payload"]["attachments"][0]["content"]["body"][1]["facts"][5]["value"] for message in messages]
        assert notification_events.count("new") == 6 and notification_events.count("approved") == 2
        assert notification_events.count("rejected") == 1 and notification_events.count("approval reminder") == 3
        assert len(graph.items(page_size=1)) == 6
        deliveries = api.get("/api/deliveries", headers={"X-Lab-User": "nolan"}).json()
        assert all(row["state"] == "sent" for row in deliveries)
        (root / "e2e-proof.json").write_text(json.dumps({"http_servers": 3, "graph_items": 6, "notifications": len(messages),
            "events": notification_events, "invalid_requester_approval": 403, "history_statuses": [row["to_status"] for row in events],
            "reminders_first_run": 3, "reminders_repeat": 0, "excel_open_requests": 4, "excel_overdue_approvals": 3,
            "import_statuses": [row["status"] for row in results], "browser_errors": errors, "browser_approval_passed": True,
            "all_deliveries_sent": True, "lab_clock": env["LAB_NOW"]}, indent=2) + "\n")
finally:
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for output in logs:
        output.close()
