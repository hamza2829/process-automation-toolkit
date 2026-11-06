from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import ValidationError
from sqlalchemy import select

from .database import History
from .domain import ProcessError, RequestInput, moment, stamp

IMPORT_COLUMNS = ["title", "category", "department", "quantity", "cost_eur", "justification", "approval_deadline"]


def safe(value):
    return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value


def sheet(book, name, title, headers, rows, widths):
    page = book.create_sheet(name)
    page.sheet_view.showGridLines = False
    page["A2"] = title
    page["A2"].font = Font(name="Arial", size=15, bold=True, color="20374F")
    for index, header in enumerate(headers, 1):
        cell = page.cell(4, index, header)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="243C59")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    page.row_dimensions[4].height = 32
    for row_index, row in enumerate(rows, 5):
        for column, value in enumerate(row, 1):
            cell = page.cell(row_index, column, safe(value))
            cell.font = Font(name="Arial", size=10, color="20374F")
            cell.alignment = Alignment(vertical="top", wrap_text=True, horizontal="right" if isinstance(value, (int, float)) else "left")
            if isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
            elif isinstance(value, float):
                cell.number_format = "0.00"
            if row_index % 2:
                cell.fill = PatternFill("solid", fgColor="F1F5FA")
        page.row_dimensions[row_index].height = max(32, 14 * max(len(str(value)) // max(1, widths[index] - 3) + 1 for index, value in enumerate(row)))
    for index, width in enumerate(widths, 1):
        page.column_dimensions[get_column_letter(index)].width = width
    page.freeze_panes = "B5"
    page.auto_filter.ref = f"A4:{get_column_letter(len(headers))}{max(4, page.max_row)}"
    page.page_setup.orientation = "landscape"
    page.page_setup.paperSize = page.PAPERSIZE_A3
    page.sheet_properties.pageSetUpPr.fitToPage = True
    page.page_setup.fitToWidth, page.page_setup.fitToHeight = 1, 0
    page.print_title_rows = "1:4"
    return page


def weekly_metrics(session, as_of):
    as_of = moment(stamp(as_of))
    snapshots = {}
    for history in session.scalars(select(History).where(History.created_at <= stamp(as_of)).order_by(History.id)):
        snapshots[history.request_id] = history.snapshot
    rows = list(snapshots.values())
    week_start = datetime.combine(as_of.date() - timedelta(days=as_of.weekday()), time.min, timezone.utc)
    created = [row for row in rows if moment(row["created_at"]) >= week_start]
    done = [row for row in rows if row["done_at"] and week_start <= moment(row["done_at"]) <= as_of]
    hours = [(moment(row["done_at"]) - moment(row["created_at"])).total_seconds() / 3600 for row in done]
    open_rows = [row for row in rows if row["status"] not in {"done", "rejected"}]
    overdue = [row for row in rows if row["status"] in {"new", "in_review"} and moment(row["approval_deadline"]) < as_of]
    return {"week_start": stamp(week_start), "as_of": stamp(as_of), "open": open_rows, "overdue": overdue,
        "completed_count": len(done), "average_processing_hours": sum(hours) / len(hours) if hours else None,
        "departments": dict(sorted(Counter(row["department"] for row in created).items()))}


def write_report(session, path, as_of):
    metrics = weekly_metrics(session, as_of)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.remove(book.active)
    overview = sheet(book, "Weekly overview", "Weekly request process", ["Metric", "Value"],
        [["Week start (UTC)", metrics["week_start"]], ["As of (UTC)", metrics["as_of"]], ["Open requests", len(metrics["open"])],
         ["Completed this week", metrics["completed_count"]], ["Average processing hours", metrics["average_processing_hours"] if metrics["average_processing_hours"] is not None else "No completed requests"],
         ["Overdue approvals", len(metrics["overdue"])]], [36, 36])
    overview["A13"] = "Processing: created to done (UTC)."
    overview["A14"] = "Snapshot from audit history."
    overview["A13"].font = overview["A14"].font = Font(name="Arial", size=10, italic=True, color="53657C")
    overview.conditional_formatting.add("B10", CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor="FCE4E4")))
    headers = ["Request", "Title", "Requester", "Department", "Category", "Status", "Approval deadline (UTC)", "Quantity"]
    for name, values in [("Open requests", metrics["open"]), ("Overdue approvals", metrics["overdue"])]:
        sheet(book, name, name, headers, [[row["id"], row["title"], row["requester"], row["department"], row["category"], row["status"],
            moment(row["approval_deadline"]).replace(tzinfo=None), row["quantity"]] for row in values], [39, 38, 14, 18, 21, 16, 26, 12])
    departments = sheet(book, "Departments", "Requests created this week", ["Department", "Requests"],
        [[key, value] for key, value in metrics["departments"].items()], [24, 18])
    if metrics["departments"]:
        chart = BarChart()
        chart.title, chart.y_axis.title, chart.x_axis.title = "Requests per department", "Requests", "Department"
        chart.add_data(Reference(departments, min_col=2, min_row=4, max_row=departments.max_row), titles_from_data=True)
        chart.set_categories(Reference(departments, min_col=1, min_row=5, max_row=departments.max_row))
        chart.height, chart.width = 9, 16
        departments.add_chart(chart, "D4")
    book.save(target)
    return metrics


def import_requests(path, service, dispatcher, user):
    book = load_workbook(path, data_only=False)
    page = book.active
    headers = [cell.value for cell in page[1]]
    if headers != IMPORT_COLUMNS:
        raise ValueError(f"Expected these Excel headers in this order: {IMPORT_COLUMNS}")
    results = []
    for row in page.iter_rows(min_row=2):
        row_number = row[0].row
        if all(cell.value is None for cell in row):
            results.append({"row": row_number, "status": "skipped", "errors": []})
            continue
        try:
            if any(cell.data_type == "f" for cell in row):
                raise ValueError("Formulas are not accepted as request input")
            values = {key: cell.value for key, cell in zip(headers, row, strict=True)}
            if isinstance(values["approval_deadline"], datetime) and values["approval_deadline"].tzinfo is None:
                values["approval_deadline"] = values["approval_deadline"].replace(tzinfo=timezone.utc)
            data = RequestInput.model_validate(values)
            with service.store.sessions() as session:
                result = service.create(session, data, user)
            dispatcher.deliver()
            results.append({"row": row_number, "status": "created", "request_id": result["id"], "errors": []})
        except ValidationError as error:
            results.append({"row": row_number, "status": "error", "errors": [".".join(map(str, item["loc"])) + ": " + item["msg"] for item in error.errors()]})
        except (ValueError, ProcessError) as error:
            results.append({"row": row_number, "status": "error", "errors": [str(error)]})
    book.close()
    return results
