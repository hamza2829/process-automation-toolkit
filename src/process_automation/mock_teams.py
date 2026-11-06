from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from .database import WebhookMessage, configured_store
from .integrations import validate_card


def create_app(store=None):
    store = store or configured_store("TEAMS_DATABASE_URL", "sqlite:///artifacts/teams.sqlite")
    app = FastAPI(title="Local Adaptive Card webhook receiver")
    app.state.store = store

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "mock-teams"}

    @app.post("/webhook", response_class=PlainTextResponse)
    def receive(payload: dict = Body()):
        if not validate_card(payload):
            raise HTTPException(422, "Expected the documented Adaptive Card message envelope")
        with store.sessions() as session:
            session.add(WebhookMessage(payload=payload))
            session.commit()
        return "1"

    @app.get("/messages")
    def messages():
        with store.sessions() as session:
            return [{"id": row.id, "payload": row.payload} for row in session.scalars(select(WebhookMessage).order_by(WebhookMessage.id))]

    return app
