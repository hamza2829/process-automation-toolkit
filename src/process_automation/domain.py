from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import os

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Status(str, Enum):
    new = "new"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    done = "done"


DEPARTMENTS = ["Production", "Engineering", "Office", "IT"]
CATEGORIES = ["tool", "material", "software_license"]
ACTORS = {"mira": {"name": "Mira Fenn", "role": "requester"}, "sola": {"name": "Sola Vale", "role": "requester"},
    "nolan": {"name": "Nolan Voss", "role": "approver"}}
FLOW = {"new": {"in_review": "approver"}, "in_review": {"approved": "approver", "rejected": "approver"},
    "approved": {"done": "requester"}, "rejected": {}, "done": {}}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone is required")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def configured_clock():
    value = os.getenv("LAB_NOW")
    if not value:
        return utcnow
    fixed = moment(stamp(datetime.fromisoformat(value.replace("Z", "+00:00"))))
    return lambda: fixed


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=120)
    category: str
    department: str
    quantity: int = Field(ge=1, le=1000, strict=True)
    cost_eur: Decimal = Field(ge=0, le=100000, multiple_of=Decimal("0.01"))
    justification: str = Field(min_length=10, max_length=2000)
    approval_deadline: AwareDatetime

    @field_validator("category", "department")
    @classmethod
    def allowed(cls, value, info):
        choices = CATEGORIES if info.field_name == "category" else DEPARTMENTS
        if value not in choices:
            raise ValueError(f"Choose one of {choices}")
        return value


class EditInput(RequestInput):
    version: int = Field(ge=1, strict=True)


class TransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Status
    version: int = Field(ge=1, strict=True)
    comment: str = Field(default="", max_length=500)


class ProcessError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)
