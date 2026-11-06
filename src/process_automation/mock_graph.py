import os
import re

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .database import GraphItem, configured_store

PATH = "/v1.0/sites/lab/lists/requests/items"
FIELDS = {"Title", "RequestId", "Requester", "Department", "Category", "Quantity", "Cost", "Reason", "Status", "Deadline", "RequestVersion"}


def create_app(store=None, token=None):
    store = store or configured_store("GRAPH_DATABASE_URL", "sqlite:///artifacts/graph.sqlite")
    token = token or os.getenv("GRAPH_TOKEN", "synthetic-lab-token")
    app = FastAPI(title="Local Graph-shaped SharePoint list")
    app.state.store = store

    @app.exception_handler(HTTPException)
    async def graph_error(request, error):
        return JSONResponse({"error": {"code": "invalidRequest", "message": str(error.detail)}}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def input_error(request, error):
        return JSONResponse({"error": {"code": "invalidRequest", "message": "Invalid query or JSON body"}}, status_code=400)

    def authorize(authorization: str = Header(default="")):
        if authorization != f"Bearer {token}":
            raise HTTPException(401, "A valid bearer token is required by this mock")

    def fields_ok(fields):
        if not isinstance(fields, dict) or not fields or set(fields) - FIELDS:
            raise HTTPException(400, "Supply supported list columns in fields")
        if any(not isinstance(value, (str, int, float)) for value in fields.values()):
            raise HTTPException(400, "This mock accepts scalar list column values")

    def item(row):
        return {"id": str(row.id), "eTag": f'"{row.version}"', "fields": row.fields}

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "mock-graph"}

    @app.post(PATH, dependencies=[Depends(authorize)], status_code=201)
    def create(payload: dict = Body()):
        if set(payload) != {"fields"}:
            raise HTTPException(400, "Create expects a fields object")
        fields_ok(payload["fields"])
        if not payload["fields"].get("Title"):
            raise HTTPException(400, "Title is required")
        with store.sessions() as session:
            row = GraphItem(fields=payload["fields"], version=1)
            session.add(row)
            session.commit()
            return item(row)

    @app.get(PATH, dependencies=[Depends(authorize)])
    def collection(request: Request, expression: str | None = Query(default=None, alias="$filter"),
            top: int = Query(default=100, ge=1, le=100, alias="$top"), skip: int = Query(default=0, ge=0, alias="$skiptoken"),
            expand: str = Query(default="fields", alias="$expand")):
        if expand != "fields":
            raise HTTPException(400, "This mock supports $expand=fields only")
        with store.sessions() as session:
            rows = session.scalars(select(GraphItem).order_by(GraphItem.id)).all()
            if expression:
                match = re.fullmatch(r"fields/(Title|RequestId|Status|Department|Requester) eq '((?:[^']|'')*)'", expression)
                if not match:
                    raise HTTPException(400, "Supported $filter: fields/Column eq 'value'; escape apostrophes as two apostrophes")
                field, expected = match.groups()
                rows = [row for row in rows if str(row.fields.get(field, "")) == expected.replace("''", "'")]
            result = {"@odata.context": str(request.base_url) + "v1.0/$metadata#items", "value": [item(row) for row in rows[skip:skip + top]]}
            if skip + top < len(rows):
                result["@odata.nextLink"] = str(request.url.include_query_params(**{"$skiptoken": skip + top, "$top": top}))
            return result

    @app.get(PATH + "/{item_id}", dependencies=[Depends(authorize)])
    def read(item_id: int):
        with store.sessions() as session:
            row = session.get(GraphItem, item_id)
            if row is None:
                raise HTTPException(404, "List item does not exist")
            return item(row)

    @app.patch(PATH + "/{item_id}/fields", dependencies=[Depends(authorize)])
    def patch(item_id: int, fields: dict = Body(), if_match: str | None = Header(default=None)):
        fields_ok(fields)
        with store.sessions() as session:
            row = session.get(GraphItem, item_id)
            if row is None:
                raise HTTPException(404, "List item does not exist")
            if if_match and if_match != f'"{row.version}"':
                raise HTTPException(412, "The supplied eTag no longer matches")
            row.fields = {**row.fields, **fields}
            row.version += 1
            session.commit()
            return row.fields

    return app
