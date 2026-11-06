from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from process_automation.app import create_app
from process_automation.database import Store
from process_automation.domain import RequestInput
from process_automation.integrations import Dispatcher, GraphClient, TeamsClient
from process_automation.mock_graph import create_app as graph_app
from process_automation.mock_teams import create_app as teams_app


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **values):
        self.now += timedelta(**values)


@pytest.fixture
def lab():
    clock = Clock()
    store, graph_store, teams_store = [Store("sqlite:///:memory:") for _ in range(3)]
    with TestClient(graph_app(graph_store, "lab-token")) as graph, TestClient(teams_app(teams_store)) as teams:
        graph_client = GraphClient("http://testserver/v1.0/sites/lab/lists/requests", "lab-token", graph)
        dispatcher = Dispatcher(store, graph_client, TeamsClient("http://testserver/webhook", teams))
        application = create_app(store, dispatcher, clock)
        with TestClient(application) as api:
            yield SimpleNamespace(clock=clock, store=store, graph_store=graph_store, teams_store=teams_store,
                api=api, app=application, graph=graph, teams=teams, graph_client=graph_client, dispatcher=dispatcher,
                service=application.state.service, headers={"Authorization": "Bearer lab-token"})
    for database in [store, graph_store, teams_store]:
        database.engine.dispose()


@pytest.fixture
def payload(lab):
    return {"title": "Synthetic inspection tool", "category": "tool", "department": "Production", "quantity": 2,
        "cost_eur": "40.50", "justification": "Synthetic trial for the fictional production cell.",
        "approval_deadline": (lab.clock() + timedelta(days=1)).isoformat()}


def create(lab, payload, user="mira"):
    response = lab.api.post("/api/requests", json=payload, headers={"X-Lab-User": user})
    assert response.status_code == 201, response.text
    return response.json()


def move(lab, row, status, user="nolan", comment=""):
    return lab.api.patch(f"/api/requests/{row['id']}/status", json={"status": status, "version": row["version"], "comment": comment}, headers={"X-Lab-User": user})


def input_data(payload):
    return RequestInput.model_validate(payload)
