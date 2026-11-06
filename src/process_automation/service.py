from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update

from .database import Delivery, History, RequestRecord, serialize
from .domain import ACTORS, FLOW, ProcessError, moment, stamp, utcnow
from .integrations import card, graph_fields


def actor(user):
    if user not in ACTORS:
        raise ProcessError(401, "Choose a known synthetic lab identity")
    return ACTORS[user]


def require_role(user, role):
    if actor(user)["role"] != role:
        raise ProcessError(403, f"This action requires the {role} role")


def visible(session, request_id, user):
    who = actor(user)
    row = session.get(RequestRecord, request_id)
    if row is None or (who["role"] == "requester" and row.requester != user):
        raise ProcessError(404, "Request not found for this identity")
    return row


class Service:
    def __init__(self, store, clock=utcnow):
        self.store, self.clock = store, clock

    def deadline(self, value):
        now = self.clock()
        if not now + timedelta(minutes=1) <= value <= now + timedelta(days=30):
            raise ProcessError(422, "Approval deadline must be from one minute to 30 days in the future")
        return stamp(value)

    def audit(self, session, row, user, kind, previous=None, comment=""):
        snapshot = serialize(row)
        session.add(History(request_id=row.id, actor=user, kind=kind, previous_status=previous, status=row.status,
            comment=comment, created_at=stamp(self.clock()), snapshot=snapshot))
        key = f"{row.id}:{row.version}"
        session.add(Delivery(event_key=f"graph:{key}", request_id=row.id, channel="graph", payload=graph_fields(snapshot)))
        if kind == "created" or row.status in {"approved", "rejected"}:
            session.add(Delivery(event_key=f"teams:{key}", request_id=row.id, channel="teams", payload=card(snapshot, "new" if kind == "created" else row.status)))

    def create(self, session, data, user):
        require_role(user, "requester")
        now = stamp(self.clock())
        row = RequestRecord(id=str(uuid4()), requester=user, title=data.title, category=data.category, department=data.department,
            quantity=data.quantity, cost_cents=int(data.cost_eur * 100), justification=data.justification,
            approval_deadline=self.deadline(data.approval_deadline), created_at=now, updated_at=now, status="new", version=1)
        session.add(row)
        session.flush()
        self.audit(session, row, user, "created")
        session.commit()
        return serialize(row)

    def change(self, session, request_id, data, user, edit=False):
        row = visible(session, request_id, user)
        if row.version != data.version:
            raise ProcessError(409, "Version conflict. Reload the request before changing it")
        previous = row.status
        if edit:
            require_role(user, "requester")
            if row.requester != user or row.status != "new":
                raise ProcessError(409, "Only the owner can edit a new request")
            values = {key: getattr(data, key) for key in ["title", "category", "department", "quantity", "justification"]}
            values.update(cost_cents=int(data.cost_eur * 100), approval_deadline=self.deadline(data.approval_deadline))
        else:
            target = data.status.value
            role = FLOW[row.status].get(target)
            if role is None:
                raise ProcessError(409, f"Transition {row.status} to {target} is not allowed")
            require_role(user, role)
            if target == "done" and row.requester != user:
                raise ProcessError(403, "Only the requester can confirm completion")
            if target == "rejected" and len(data.comment) < 3:
                raise ProcessError(422, "Rejection needs a reason of at least three characters")
            values = {"status": target}
            if target == "done":
                values["done_at"] = stamp(self.clock())
        values.update(version=row.version + 1, updated_at=stamp(self.clock()))
        result = session.execute(update(RequestRecord).where(RequestRecord.id == row.id, RequestRecord.version == data.version).values(**values))
        if result.rowcount != 1:
            session.rollback()
            raise ProcessError(409, "Concurrent change detected. Reload the request")
        session.refresh(row)
        self.audit(session, row, user, "fields_updated" if edit else "status_changed", previous, "" if edit else data.comment)
        session.commit()
        return serialize(row)

    def reminders(self, session, user, as_of=None):
        require_role(user, "approver")
        when = moment(stamp(as_of or self.clock()))
        rows = session.scalars(select(RequestRecord).where(RequestRecord.status.in_(["new", "in_review"]), RequestRecord.approval_deadline < stamp(when))).all()
        count = 0
        for row in rows:
            key = f"reminder:{row.id}:{when.date().isoformat()}"
            if session.scalar(select(Delivery.id).where(Delivery.event_key == key)) is None:
                session.add(Delivery(event_key=key, request_id=row.id, channel="teams", payload=card(serialize(row), "approval reminder")))
                count += 1
        session.commit()
        return count

    def deliveries(self, session, request_id):
        return session.scalar(select(func.count()).select_from(Delivery).where(Delivery.request_id == request_id, Delivery.state == "pending"))
