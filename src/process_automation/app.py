import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from .database import Delivery, History, RequestRecord, configured_store, serialize
from .domain import ACTORS, CATEGORIES, DEPARTMENTS, EditInput, ProcessError, RequestInput, Status, TransitionInput, configured_clock
from .integrations import Dispatcher, GraphClient, TeamsClient
from .service import Service, actor, require_role, visible


def configured_dispatcher(store):
    return Dispatcher(store, GraphClient(os.getenv("GRAPH_BASE_URL", "http://127.0.0.1:8011/v1.0/sites/lab/lists/requests"),
        os.getenv("GRAPH_TOKEN", "synthetic-lab-token")), TeamsClient(os.getenv("TEAMS_WEBHOOK_URL", "http://127.0.0.1:8012/webhook")))


def create_app(store=None, dispatcher=None, clock=None):
    store = store or configured_store()
    clock = clock or configured_clock()
    service = Service(store, clock)
    dispatcher = dispatcher or configured_dispatcher(store)
    app = FastAPI(title="Process automation toolkit", version="0.1.0")
    app.state.store, app.state.service, app.state.dispatcher = store, service, dispatcher
    folder = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=folder / "static"), name="static")
    templates = Jinja2Templates(directory=folder / "templates")

    @app.exception_handler(ProcessError)
    async def process_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    def identity(x_lab_user: str = Header(default="mira")):
        actor(x_lab_user)
        return x_lab_user

    def session():
        with store.sessions() as connection:
            yield connection

    def response_with_delivery(record):
        dispatcher.deliver()
        with store.sessions() as connection:
            record["pending_deliveries"] = service.deliveries(connection, record["id"])
        return record

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "request-app"}

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(request=request, name="index.html", context={"actors": ACTORS, "departments": DEPARTMENTS, "categories": CATEGORIES})

    @app.get("/api/identities")
    def identities():
        return ACTORS

    @app.post("/api/requests", status_code=201)
    def create(data: RequestInput, user=Depends(identity), db=Depends(session)):
        return response_with_delivery(service.create(db, data, user))

    @app.get("/api/requests")
    def requests(status: Status | None = None, department: str | None = None, offset: int = Query(default=0, ge=0),
            limit: int = Query(default=50, ge=1, le=100), user=Depends(identity), db=Depends(session)):
        query = select(RequestRecord).order_by(RequestRecord.created_at.desc(), RequestRecord.id)
        if actor(user)["role"] == "requester":
            query = query.where(RequestRecord.requester == user)
        if status:
            query = query.where(RequestRecord.status == status.value)
        if department:
            if department not in DEPARTMENTS:
                raise ProcessError(422, "Unknown department filter")
            query = query.where(RequestRecord.department == department)
        return [serialize(row) for row in db.scalars(query.offset(offset).limit(limit))]

    @app.get("/api/requests/{request_id}")
    def read(request_id: str, user=Depends(identity), db=Depends(session)):
        result = serialize(visible(db, request_id, user))
        result["pending_deliveries"] = service.deliveries(db, request_id)
        return result

    @app.patch("/api/requests/{request_id}")
    def edit(request_id: str, data: EditInput, user=Depends(identity), db=Depends(session)):
        return response_with_delivery(service.change(db, request_id, data, user, edit=True))

    @app.patch("/api/requests/{request_id}/status")
    def transition(request_id: str, data: TransitionInput, user=Depends(identity), db=Depends(session)):
        return response_with_delivery(service.change(db, request_id, data, user))

    @app.get("/api/requests/{request_id}/history")
    def history(request_id: str, user=Depends(identity), db=Depends(session)):
        visible(db, request_id, user)
        return [{"id": row.id, "actor": row.actor, "kind": row.kind, "from_status": row.previous_status, "to_status": row.status,
            "comment": row.comment, "created_at": row.created_at, "snapshot": row.snapshot}
            for row in db.scalars(select(History).where(History.request_id == request_id).order_by(History.id))]

    @app.post("/api/reminders")
    def reminders(user=Depends(identity), db=Depends(session)):
        queued = service.reminders(db, user)
        return {"queued": queued, **dispatcher.deliver()}

    @app.post("/api/deliveries/retry")
    def retry(user=Depends(identity)):
        require_role(user, "approver")
        return dispatcher.deliver()

    @app.get("/api/deliveries")
    def deliveries(user=Depends(identity), db=Depends(session)):
        require_role(user, "approver")
        return [{"id": row.id, "request_id": row.request_id, "channel": row.channel, "state": row.state, "attempts": row.attempts,
            "last_error": row.last_error} for row in db.scalars(select(Delivery).order_by(Delivery.id))]

    return app
