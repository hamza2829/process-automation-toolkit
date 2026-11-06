import os
from pathlib import Path
from threading import Lock

from sqlalchemy import JSON, ForeignKey, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class RequestRecord(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    requester: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    department: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    cost_cents: Mapped[int] = mapped_column(Integer)
    justification: Mapped[str] = mapped_column(String)
    approval_deadline: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="new")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
    done_at: Mapped[str | None] = mapped_column(String, nullable=True)


class History(Base):
    __tablename__ = "history"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    actor: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    previous_status: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    comment: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict] = mapped_column(JSON)


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String, unique=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    channel: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)


class GraphItem(Base):
    __tablename__ = "graph_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    fields: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WebhookMessage(Base):
    __tablename__ = "webhook_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Store:
    def __init__(self, url):
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = {"connect_args": {"check_same_thread": False, "timeout": 30}}
        if url == "sqlite:///:memory:":
            options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.delivery_lock = Lock()


def configured_store(name="APP_DATABASE_URL", default="sqlite:///artifacts/app.sqlite"):
    return Store(os.getenv(name, default))


def serialize(row):
    return {"id": row.id, "requester": row.requester, "title": row.title, "category": row.category, "department": row.department,
        "quantity": row.quantity, "cost_eur": f"{row.cost_cents / 100:.2f}", "justification": row.justification,
        "approval_deadline": row.approval_deadline, "status": row.status, "version": row.version,
        "created_at": row.created_at, "updated_at": row.updated_at, "done_at": row.done_at}
