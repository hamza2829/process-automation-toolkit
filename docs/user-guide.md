# User guide

This guide describes the synthetic lab. GitHub Actions runs the complete demonstration automatically. No PC installation, account or manual step is required.

## Submit a request

1. The page opens with Mira Fenn, a synthetic requester. Sola Vale is another requester. Nolan Voss is the approver.
2. Enter an invented title, category, department, quantity, estimated cost, business reason and approval deadline.
3. Use a UTC deadline from one minute to 30 days ahead. Click Submit request.
4. The page reports the saved request and its pending delivery count. A nonzero count means an integration delivery needs retry, not that the saved request disappeared.

Each requester sees only their own requests. The identity selector is a lab switch, not authentication. It creates no account and uses no password.

## Review, approve and finish

1. Select Nolan Voss. Start review on a new request.
2. Choose Approve or Reject. Reject requires a reason with at least three characters.
3. For an approved request, the owning requester can select Confirm done.
4. Use History to view timestamps, actors, state changes and comments. The API also returns full audit snapshots.

The allowed path is `new -> in_review -> approved -> done` or `new -> in_review -> rejected`. Rejected and done requests cannot reopen. An owning requester can edit form fields through `PATCH /api/requests/{id}` only while new. Every edit and transition includes the current version. A stale version returns 409; refresh before trying again.

Use the status and department filters to narrow the list. The page displays up to 50 requests. The API also supports `offset` and `limit` for larger synthetic datasets.

## Reminders and delivery retries

Nolan's Check deadline reminders button checks new and in_review requests with deadlines before the current UTC time. It queues one reminder per request per UTC date. A deadline exactly at the cutoff is not overdue. Approved requests remain open work but no longer need approval reminders.

Retry pending deliveries repeats unsuccessful Graph syncs and card delivery attempts. The request, its history and the delivery queue survive a server restart. Graph events retain per-request order after a delivery failure. Use `GET /api/deliveries` as Nolan to inspect state, attempt counts and error summaries.

For an already prepared runner environment:

```sh
process-toolkit remind --as-of 2026-11-05T09:00:00Z
process-toolkit deliver
```

There is no permanently hosted scheduler in this lab. CI invokes the reminder command and proves that a repeated same-day run creates no duplicate reminder.

## Weekly workbook

```sh
process-toolkit report --out artifacts/weekly-report.xlsx --as-of 2026-11-05T09:00:00Z
```

The workbook contains Weekly overview, Open requests, Overdue approvals and Departments. Creation counts run from Monday 00:00 UTC through the cutoff. Average processing time is elapsed hours from creation to done for requests completed in that UTC week. With no completions, the cell says No completed requests. Open requests exclude done and rejected. Historical values come from the latest audit snapshot at the cutoff, not today's final status. Dates in Excel are naive cells labeled UTC because Excel does not store timezone-aware datetimes.

The Departments sheet contains a chart when the week has creation data. Workbooks are static reports; changing a cell does not rerun the process calculations.

## Import an Excel workbook

The first sheet must have these exact headers in row 1:

```text
title | category | department | quantity | cost_eur | justification | approval_deadline
```

The separators above describe seven separate Excel cells. Supply UTC ISO timestamp text, or an Excel datetime cell interpreted as UTC. Use integer quantity cells and a cost with no more than two decimal places. Formulas are rejected and never evaluated.

```sh
process-toolkit import-excel artifacts/new-requests.xlsx --actor mira --out artifacts/import-results.json
```

The result has a status for every data row: created, error or skipped. Error rows include the Excel row number and every validation message for that row. Good rows after a bad row still import. Any error gives CLI exit code 1, including a partial import. A fully valid import returns 0. Re-running an import creates new requests for its valid rows; spreadsheet import is not an idempotent sync.

The CI artifact includes a mixed synthetic workbook and its actual row report. CI uses `LAB_NOW=2026-11-02T09:00:00Z` so its example deadlines remain reproducible. Normal execution leaves LAB_NOW unset and uses the real UTC clock. To replay the artifact input in a prepared lab environment, use the same synthetic clock for the app and CLI.
