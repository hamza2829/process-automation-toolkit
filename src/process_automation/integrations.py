from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from .database import Delivery


class IntegrationError(ValueError):
    pass


class GraphClient:
    """Graph v1 list operations. The configured URL includes the site and list ids."""
    def __init__(self, base_url, token, client=None):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = client or httpx.Client(timeout=3)

    def items(self, filter_expression=None, page_size=100):
        url = self.base_url + "/items"
        params = {"$expand": "fields", "$top": page_size}
        if filter_expression:
            params["$filter"] = filter_expression
        seen, rows = set(), []
        while url:
            parsed, expected = urlsplit(url), urlsplit(self.base_url)
            if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path + "/items"):
                raise IntegrationError("Graph nextLink left the configured list endpoint")
            if url in seen or len(seen) >= 1000:
                raise IntegrationError("Graph paging repeated or exceeded 1000 pages")
            seen.add(url)
            response = self.client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data.get("value"), list):
                raise IntegrationError("Graph response has no item collection")
            rows.extend(data["value"])
            url, params = data.get("@odata.nextLink"), None
        return rows

    def sync(self, fields):
        escaped = str(fields["RequestId"]).replace("'", "''")
        matches = self.items(f"fields/RequestId eq '{escaped}'")
        if len(matches) > 1:
            raise IntegrationError("Multiple Graph items have the same RequestId")
        if not matches:
            response = self.client.post(self.base_url + "/items", headers=self.headers, json={"fields": fields})
        else:
            item = matches[0]
            if int(item["fields"].get("RequestVersion", 0)) > fields["RequestVersion"]:
                return
            response = self.client.patch(self.base_url + f"/items/{item['id']}/fields", headers=self.headers, json=fields)
        response.raise_for_status()


def graph_fields(record):
    return {"Title": record["title"], "RequestId": record["id"], "Requester": record["requester"], "Department": record["department"],
        "Category": record["category"], "Quantity": record["quantity"], "Cost": float(record["cost_eur"]), "Reason": record["justification"],
        "Status": record["status"], "Deadline": record["approval_deadline"], "RequestVersion": record["version"]}


def card(record, event):
    facts = [{"title": key, "value": str(value)} for key, value in [("Request", record["id"]), ("Requester", record["requester"]),
        ("Department", record["department"]), ("Status", record["status"]), ("Approval deadline", record["approval_deadline"]),
        ("Event", event), ("Version", record["version"])]]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.2",
            "body": [{"type": "TextBlock", "text": f"Request {event}: {record['title']}", "wrap": True}, {"type": "FactSet", "facts": facts}]}}]}


def validate_card(payload):
    try:
        attachment = payload["attachments"][0]
        content = attachment["content"]
        return (payload["type"] == "message" and len(payload["attachments"]) == 1
            and attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
            and content["type"] == "AdaptiveCard" and content["version"] == "1.2"
            and content["body"][0]["type"] == "TextBlock" and bool(content["body"][0]["text"])
            and content["body"][1]["type"] == "FactSet" and len(content["body"][1]["facts"]) == 7
            and all(set(fact) == {"title", "value"} and isinstance(fact["title"], str) and isinstance(fact["value"], str)
                for fact in content["body"][1]["facts"]))
    except (KeyError, IndexError, TypeError):
        return False


class TeamsClient:
    def __init__(self, webhook_url, client=None):
        self.webhook_url = webhook_url
        self.client = client or httpx.Client(timeout=3)

    def send(self, payload):
        self.client.post(self.webhook_url, json=payload).raise_for_status()


class Dispatcher:
    """A durable outbox. Failed Graph events hold later Graph events for that request."""
    def __init__(self, store, graph, teams):
        self.store, self.graph, self.teams = store, graph, teams

    def deliver(self):
        sent, failed, blocked = 0, 0, set()
        with self.store.delivery_lock, self.store.sessions() as session:
            rows = session.scalars(select(Delivery).where(Delivery.state == "pending").order_by(Delivery.id)).all()
            for row in rows:
                if row.channel == "graph" and row.request_id in blocked:
                    continue
                row.attempts += 1
                try:
                    if row.channel == "graph":
                        self.graph.sync(row.payload)
                    else:
                        self.teams.send(row.payload)
                    row.state, row.last_error = "sent", None
                    sent += 1
                except (httpx.HTTPError, IntegrationError, ValueError) as error:
                    row.last_error = f"{type(error).__name__}: delivery failed; retry with deliver"
                    failed += 1
                    if row.channel == "graph":
                        blocked.add(row.request_id)
                session.commit()
        return {"sent": sent, "failed": failed}
