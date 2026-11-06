# Requirements

This lab processes only synthetic requests. The role selector and mock services are demonstration components. UTC is used for all deadlines and reporting.

| ID | Requirement and acceptance condition |
| --- | --- |
| R-01 | Validate required fields, allowed category and department, quantity 1 to 1000, cost EUR 0 to 100000 with cents, title 3 to 120 characters, and reason 10 to 2000 characters. Reject extra fields and invalid input without storing a request. |
| R-02 | Enforce new to in_review to approved or rejected, then approved to done. Terminal states cannot reopen. Rejection requires at least three characters of explanation. |
| R-03 | Map the synthetic identity to its server-defined role. Only approvers review and decide. Only the owning requester edits a new request or confirms completion. Other requesters cannot read that request. |
| R-04 | Append an audit entry for creation, field edits and status changes, with actor, UTC timestamp, previous and new status, comment and full snapshot. Keep earlier snapshots unchanged. |
| R-05 | Require the current integer version for every edit or status change. Reject a stale version with HTTP 409 without adding a history entry. |
| R-06 | Provide Graph-shaped list item creation, reading and partial field updates, including ids, fields and eTags. Require the mock bearer token and reject stale If-Match values. |
| R-07 | Support the documented equality subset of $filter, $top paging and absolute @odata.nextLink values that preserve the filter. Reject unsupported expressions. |
| R-08 | Sync creation, edits and status changes through a configurable Graph client. Persist an outbox transactionally, retry failures and prevent stale Graph updates from replacing a newer version. |
| R-09 | Send an Adaptive Card message for new, approved and rejected events to a configurable webhook URL. Capture and validate the actual JSON in the local receiver. |
| R-10 | Accept an aware approval deadline from one minute to 30 days ahead. Remind for overdue new or in_review requests at most once per UTC date. Do not remind for completed decisions. |
| R-11 | Create a weekly Excel report with open requests, completed-request average processing hours, department creation counts and overdue approvals. Include typed cells, formatting and a department chart when data exists. Use audit snapshots for historical cutoffs. |
| R-12 | Read new requests from Excel, validate every data row, continue after invalid rows, report row numbers and all field errors, skip empty rows and reject formulas. A partial import returns a nonzero CLI exit code. |
| R-13 | Provide one HTML page with the form, status and department filters, review, approve, reject and completion actions, and change history. Show role and delivery feedback. Render untrusted text as text. |
| R-14 | Persist requests, history and pending integration deliveries in SQLite through SQLAlchemy, with committed data readable after reopening the database. |
| R-15 | Run the CLI, Ruff, at least 40 pytest cases, at least 85 percent line coverage and a real three-server end-to-end scenario in GitHub Actions. Upload the weekly workbook and measured proof. |

Deadline equality is not overdue. Approved requests remain open until done, but no longer need an approval reminder. Cost is a validated estimate; this lab has no purchasing or accounting integration.
