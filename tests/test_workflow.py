from datetime import timedelta, timezone

import pytest
from sqlalchemy import select

from process_automation.database import History, RequestRecord, Store
from process_automation.domain import ACTORS, ProcessError, stamp
from process_automation.service import Service
from conftest import create, input_data, move


def test_valid_creation_sync_and_history(lab, payload):
    row = create(lab, payload)
    assert row["status"] == "new" and row["version"] == 1 and row["pending_deliveries"] == 0
    assert row["cost_eur"] == "40.50"
    history = lab.api.get(f"/api/requests/{row['id']}/history").json()
    assert history[0]["kind"] == "created" and history[0]["actor"] == "mira"
    assert history[0]["snapshot"]["title"] == payload["title"]
    assert lab.graph_client.items()[0]["fields"]["Status"] == "new"


@pytest.mark.parametrize("field,value", [("title", "ab"), ("title", "x" * 121), ("title", "   "), ("category", "other"),
    ("department", "Unknown"), ("quantity", 0), ("quantity", 1001), ("quantity", 1.5), ("quantity", True),
    ("cost_eur", "-0.01"), ("cost_eur", "100000.01"), ("cost_eur", "0.001"), ("cost_eur", "NaN"),
    ("justification", "short"), ("justification", "x" * 2001), ("approval_deadline", "yesterday"), ("approval_deadline", "2026-11-03T09:00:00")])
def test_input_limits(lab, payload, field, value):
    payload[field] = value
    assert lab.api.post("/api/requests", json=payload).status_code == 422
    assert lab.api.get("/api/requests").json() == []


@pytest.mark.parametrize("field", ["title", "category", "department", "quantity", "cost_eur", "justification", "approval_deadline"])
def test_required_fields(lab, payload, field):
    del payload[field]
    assert lab.api.post("/api/requests", json=payload).status_code == 422


def test_extra_fields_forbidden_and_identity_server_mapped(lab, payload):
    payload["requester"] = "nolan"
    assert lab.api.post("/api/requests", json=payload).status_code == 422
    del payload["requester"]
    assert lab.api.post("/api/requests", json=payload, headers={"X-Lab-User": "admin"}).status_code == 401
    assert lab.api.post("/api/requests", json=payload, headers={"X-Lab-User": "nolan"}).status_code == 403
    assert lab.api.get("/api/identities").json() == ACTORS


@pytest.mark.parametrize("seconds,expected", [(59, 422), (60, 201), (30 * 86400, 201), (30 * 86400 + 1, 422), (-1, 422)])
def test_deadline_boundaries(lab, payload, seconds, expected):
    payload["approval_deadline"] = (lab.clock() + timedelta(seconds=seconds)).isoformat()
    assert lab.api.post("/api/requests", json=payload).status_code == expected


def test_complete_approved_flow_and_duration(lab, payload):
    row = create(lab, payload)
    row = move(lab, row, "in_review").json()
    lab.clock.advance(hours=2)
    row = move(lab, row, "approved", comment="Budget confirmed").json()
    assert move(lab, row, "done").status_code == 403
    lab.clock.advance(hours=4)
    row = move(lab, row, "done", "mira").json()
    assert row["done_at"] == stamp(lab.clock()) and row["version"] == 4
    assert move(lab, row, "new", "mira").status_code == 409
    history = lab.api.get(f"/api/requests/{row['id']}/history").json()
    assert [event["to_status"] for event in history] == ["new", "in_review", "approved", "done"]
    assert history[2]["comment"] == "Budget confirmed"
    assert history[0]["snapshot"]["status"] == "new"
    assert lab.graph_client.items()[0]["fields"]["Status"] == "done"


def test_rejected_flow_reason_and_terminal_state(lab, payload):
    row = move(lab, create(lab, payload), "in_review").json()
    assert move(lab, row, "rejected", comment="no").status_code == 422
    row = move(lab, row, "rejected", comment="Existing stock is sufficient").json()
    assert row["status"] == "rejected"
    assert move(lab, row, "approved").status_code == 409


def test_role_ownership_and_skipped_stages(lab, payload):
    row = create(lab, payload)
    assert move(lab, row, "in_review", "mira").status_code == 403
    assert move(lab, row, "approved").status_code == 409
    assert lab.api.get(f"/api/requests/{row['id']}", headers={"X-Lab-User": "sola"}).status_code == 404
    assert lab.api.get("/api/requests", headers={"X-Lab-User": "sola"}).json() == []
    assert lab.api.get("/api/requests/missing").status_code == 404
    assert lab.api.get(f"/api/requests/{row['id']}/history", headers={"X-Lab-User": "sola"}).status_code == 404


def test_stale_version_conflict_does_not_add_history(lab, payload):
    row = create(lab, payload)
    assert move(lab, row, "in_review").status_code == 200
    assert move(lab, row, "in_review").status_code == 409
    assert len(lab.api.get(f"/api/requests/{row['id']}/history").json()) == 2


def test_edit_new_request_audits_and_syncs(lab, payload):
    row = create(lab, payload)
    changed = {**payload, "title": "Updated synthetic tool", "version": 1}
    result = lab.api.patch(f"/api/requests/{row['id']}", json=changed)
    assert result.status_code == 200 and result.json()["version"] == 2
    history = lab.api.get(f"/api/requests/{row['id']}/history").json()
    assert history[1]["kind"] == "fields_updated"
    assert history[0]["snapshot"]["title"] != history[1]["snapshot"]["title"]
    assert lab.graph_client.items()[0]["fields"]["Title"] == changed["title"]
    assert lab.api.patch(f"/api/requests/{row['id']}", json={**changed, "version": 2}, headers={"X-Lab-User": "nolan"}).status_code == 403
    row = move(lab, result.json(), "in_review").json()
    assert lab.api.patch(f"/api/requests/{row['id']}", json={**changed, "version": row["version"]}).status_code == 409


def test_api_filters_paging_and_query_validation(lab, payload):
    create(lab, payload)
    create(lab, {**payload, "department": "IT"}, "sola")
    admin = {"X-Lab-User": "nolan"}
    assert len(lab.api.get("/api/requests", headers=admin).json()) == 2
    assert len(lab.api.get("/api/requests?status=new&department=IT", headers=admin).json()) == 1
    assert len(lab.api.get("/api/requests?offset=1&limit=1", headers=admin).json()) == 1
    for query in ["status=bad", "department=bad", "offset=-1", "limit=101"]:
        assert lab.api.get("/api/requests?" + query).status_code == 422
    assert lab.api.get("/health").json()["status"] == "ok"


def test_reminders_overdue_boundary_dedup_and_roles(lab, payload):
    row = create(lab, payload)
    assert lab.api.post("/api/reminders").status_code == 403
    lab.clock.advance(days=1)
    admin = {"X-Lab-User": "nolan"}
    assert lab.api.post("/api/reminders", headers=admin).json()["queued"] == 0
    lab.clock.advance(seconds=1)
    assert lab.api.post("/api/reminders", headers=admin).json()["queued"] == 1
    assert lab.api.post("/api/reminders", headers=admin).json()["queued"] == 0
    lab.clock.advance(days=1)
    assert lab.api.post("/api/reminders", headers=admin).json()["queued"] == 1
    row = move(lab, row, "in_review").json()
    row = move(lab, row, "approved").json()
    lab.clock.advance(days=1)
    assert lab.api.post("/api/reminders", headers=admin).json()["queued"] == 0


def test_sqlite_persistence_after_reopening(tmp_path, lab, payload):
    path = "sqlite:///" + (tmp_path / "persist.sqlite").as_posix()
    store = Store(path)
    with store.sessions() as session:
        row = Service(store, lab.clock).create(session, input_data(payload), "mira")
    store.engine.dispose()
    reopened = Store(path)
    with reopened.sessions() as session:
        assert session.get(RequestRecord, row["id"]).title == payload["title"]
        assert session.scalar(select(History)).snapshot["version"] == 1
    reopened.engine.dispose()


def test_timezone_normalization_and_naive_rejection(lab, payload):
    assert stamp(lab.clock().astimezone(timezone(timedelta(hours=2)))) == stamp(lab.clock())
    with pytest.raises(ValueError, match="timezone"):
        stamp(lab.clock().replace(tzinfo=None))
    with pytest.raises(ProcessError):
        lab.service.deadline(lab.clock())


def test_configured_clock_is_explicit_and_requires_timezone(monkeypatch, lab):
    from process_automation.domain import configured_clock, utcnow
    monkeypatch.delenv("LAB_NOW", raising=False)
    assert configured_clock() is utcnow
    monkeypatch.setenv("LAB_NOW", "2026-11-02T11:00:00+02:00")
    assert configured_clock()() == lab.clock()
    monkeypatch.setenv("LAB_NOW", "2026-11-02T09:00:00")
    with pytest.raises(ValueError, match="timezone"):
        configured_clock()
