from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select

from process_automation.database import Delivery
from process_automation.integrations import GraphClient, IntegrationError, card, validate_card
from process_automation.mock_graph import PATH
from conftest import create, move


def test_graph_crud_partial_patch_etag_and_missing_items(lab):
    result = lab.graph.post(PATH, headers=lab.headers, json={"fields": {"Title": "Synthetic", "Department": "IT"}})
    assert result.status_code == 201
    row = result.json()
    assert row["id"] == "1" and row["fields"]["Title"] == "Synthetic"
    assert lab.graph.get(PATH + "/1", headers=lab.headers).json() == row
    changed = lab.graph.patch(PATH + "/1/fields", headers={**lab.headers, "If-Match": '"1"'}, json={"Title": "Updated"})
    assert changed.status_code == 200 and changed.json() == {"Title": "Updated", "Department": "IT"}
    assert lab.graph.patch(PATH + "/1/fields", headers={**lab.headers, "If-Match": '"1"'}, json={"Title": "Stale"}).status_code == 412
    assert lab.graph.get(PATH + "/999", headers=lab.headers).status_code == 404
    assert lab.graph.patch(PATH + "/999/fields", headers=lab.headers, json={"Title": "Missing"}).status_code == 404


def test_graph_filter_and_nextlink_preserve_query(lab):
    for title in ["One", "Two", "O'Brien"]:
        lab.graph.post(PATH, headers=lab.headers, json={"fields": {"Title": title, "Status": "new"}})
    first = lab.graph.get(PATH, headers=lab.headers, params={"$filter": "fields/Status eq 'new'", "$top": 1}).json()
    assert len(first["value"]) == 1 and "@odata.nextLink" in first
    second = lab.graph.get(first["@odata.nextLink"], headers=lab.headers).json()
    assert second["value"][0]["fields"]["Title"] == "Two"
    assert len(lab.graph_client.items(page_size=1)) == 3
    assert lab.graph_client.items("fields/Title eq 'O''Brien'")[0]["fields"]["Title"] == "O'Brien"
    assert lab.graph_client.items("fields/Status eq 'approved'") == []


@pytest.mark.parametrize("payload", [{}, {"fields": {}}, {"fields": {"Bogus": "x"}}, {"fields": {"Title": []}}, {"fields": {"Status": "new"}}, {"fields": {"Title": "x"}, "other": "x"}])
def test_graph_rejects_unsupported_fields(lab, payload):
    assert lab.graph.post(PATH, headers=lab.headers, json=payload).status_code == 400


def test_graph_auth_and_unsupported_queries(lab):
    assert lab.graph.get(PATH).status_code == 401
    assert lab.graph.get(PATH, headers={"Authorization": "Bearer wrong"}).status_code == 401
    for params in [{"$filter": "fields/Status ne 'new'"}, {"$top": 0}, {"$skiptoken": -1}, {"$expand": "other"}]:
        result = lab.graph.get(PATH, headers=lab.headers, params=params)
        assert result.status_code == 400 and "error" in result.json()
    assert lab.graph.get("/health").json()["service"] == "mock-graph"


def test_client_only_base_url_and_token_configuration():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    client = GraphClient("https://graph.microsoft.com/v1.0/sites/site-id/lists/list-id", "synthetic-test-token", httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.items("fields/Status eq 'new'") == []
    assert captured[0].url.host == "graph.microsoft.com"
    assert captured[0].url.path == "/v1.0/sites/site-id/lists/list-id/items"
    assert captured[0].headers["Authorization"] == "Bearer synthetic-test-token"
    assert captured[0].url.params["$expand"] == "fields"


@pytest.mark.parametrize("data,message", [({"value": [], "@odata.nextLink": "https://other.invalid/items"}, "left"),
    ({"value": [], "@odata.nextLink": "http://testserver/v1.0/sites/lab/lists/requests/items"}, "repeated"), ({"wrong": []}, "collection")])
def test_client_rejects_unsafe_or_broken_paging(data, message):
    client = GraphClient("http://testserver/v1.0/sites/lab/lists/requests", "lab", httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))))
    with pytest.raises(IntegrationError, match=message):
        client.items()


def test_graph_sync_idempotent_and_never_downgrades_version(lab, payload):
    row = create(lab, payload)
    fields = lab.graph_client.items()[0]["fields"]
    lab.graph_client.sync(fields)
    assert len(lab.graph_client.items()) == 1
    newer = {**fields, "RequestVersion": 5, "Status": "approved"}
    lab.graph_client.sync(newer)
    lab.graph_client.sync(fields)
    assert lab.graph_client.items()[0]["fields"]["Status"] == "approved"
    lab.graph.post(PATH, headers=lab.headers, json={"fields": fields})
    with pytest.raises(IntegrationError, match="Multiple"):
        lab.graph_client.sync(fields)
    assert row["id"] == fields["RequestId"]


def test_teams_new_approved_rejected_payloads_and_no_other_status_notifications(lab, payload):
    one = create(lab, payload)
    one = move(lab, one, "in_review").json()
    one = move(lab, one, "approved").json()
    move(lab, one, "done", "mira")
    two = move(lab, create(lab, payload), "in_review").json()
    move(lab, two, "rejected", comment="Stock is available")
    messages = lab.teams.get("/messages").json()
    assert len(messages) == 4
    events = []
    for message in messages:
        value = message["payload"]
        assert validate_card(value)
        attachment = value["attachments"][0]
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachment["content"]["version"] == "1.2"
        facts = {fact["title"]: fact["value"] for fact in attachment["content"]["body"][1]["facts"]}
        assert facts["Requester"] == "mira" and facts["Department"] == "Production"
        assert facts["Request"] in {one["id"], two["id"]}
        events.append(facts["Event"])
    assert events == ["new", "approved", "new", "rejected"]
    assert lab.teams.get("/health").status_code == 200


def test_webhook_rejects_invalid_payload_and_card_validation(lab, payload):
    assert lab.teams.post("/webhook", json={"text": "bad"}).status_code == 422
    good = card(create(lab, payload), "new")
    assert lab.teams.post("/webhook", json=good).text == "1"
    bad = deepcopy(good)
    bad["attachments"][0]["content"]["version"] = "9.0"
    assert not validate_card(bad)
    bad = deepcopy(good)
    bad["attachments"][0]["content"]["body"][1]["facts"][0] = {"title": "Request", "value": []}
    assert not validate_card(bad)
    assert not validate_card({"attachments": []})
    assert not validate_card(None)


def test_outbox_failure_persists_and_retries_in_order(lab, payload, monkeypatch):
    original = lab.dispatcher.graph.sync
    monkeypatch.setattr(lab.dispatcher.graph, "sync", lambda fields: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    row = create(lab, payload)
    assert row["pending_deliveries"] == 1
    review = move(lab, row, "in_review").json()
    assert review["pending_deliveries"] == 2
    with lab.store.sessions() as session:
        attempts = session.scalars(select(Delivery).where(Delivery.channel == "graph").order_by(Delivery.id)).all()
        assert attempts[0].attempts == 2 and attempts[1].attempts == 0
    monkeypatch.setattr(lab.dispatcher.graph, "sync", original)
    admin = {"X-Lab-User": "nolan"}
    assert lab.api.post("/api/deliveries/retry").status_code == 403
    assert lab.api.get("/api/deliveries").status_code == 403
    assert lab.api.post("/api/deliveries/retry", headers=admin).json() == {"sent": 2, "failed": 0}
    assert lab.graph_client.items()[0]["fields"]["Status"] == "in_review"
    states = lab.api.get("/api/deliveries", headers=admin).json()
    assert all(item["state"] == "sent" and item["last_error"] is None for item in states)


def test_webhook_failure_is_durable(lab, payload, monkeypatch):
    original = lab.dispatcher.teams.send
    monkeypatch.setattr(lab.dispatcher.teams, "send", lambda value: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    row = create(lab, payload)
    assert row["pending_deliveries"] == 1
    states = lab.api.get("/api/deliveries", headers={"X-Lab-User": "nolan"}).json()
    assert states[-1]["state"] == "pending" and "ConnectError" in states[-1]["last_error"]
    monkeypatch.setattr(lab.dispatcher.teams, "send", original)
    assert lab.dispatcher.deliver() == {"sent": 1, "failed": 0}
