# Automated test traceability

The function names below are collected by pytest. A test also checks that every requirement id is mapped and each listed test function exists. The CI scripts add actual HTTP, browser, workbook rendering and measurement checks.

| Case | Requirement | Scenario | Automated test or CI check |
| --- | --- | --- | --- |
| T-01 | R-01 | Required values, finite limits, strict quantity and forbidden fields | `test_input_limits`, `test_required_fields`, `test_extra_fields_forbidden_and_identity_server_mapped` |
| T-02 | R-02 | Valid approval and rejection, invalid skipped stages and terminal states | `test_complete_approved_flow_and_duration`, `test_rejected_flow_reason_and_terminal_state`, `test_role_ownership_and_skipped_stages` |
| T-03 | R-03 | Role checks, ownership and private requester views | `test_role_ownership_and_skipped_stages`, `test_extra_fields_forbidden_and_identity_server_mapped`, `test_edit_new_request_audits_and_syncs` |
| T-04 | R-04 | Full snapshots and immutable earlier history after edits | `test_valid_creation_sync_and_history`, `test_edit_new_request_audits_and_syncs` |
| T-05 | R-05 | Stale version does not append a change | `test_stale_version_conflict_does_not_add_history` |
| T-06 | R-06 | Graph create/read/partial update, auth and eTag | `test_graph_crud_partial_patch_etag_and_missing_items`, `test_graph_auth_and_unsupported_queries` |
| T-07 | R-07 | Filter, apostrophe escaping and multi-page reads | `test_graph_filter_and_nextlink_preserve_query`, `test_client_rejects_unsafe_or_broken_paging` |
| T-08 | R-08 | Client URL/token contract, durable retries and monotonic versions | `test_client_only_base_url_and_token_configuration`, `test_outbox_failure_persists_and_retries_in_order`, `test_graph_sync_idempotent_and_never_downgrades_version` |
| T-09 | R-09 | Actual envelope, events, invalid card rejection and delivery failure | `test_teams_new_approved_rejected_payloads_and_no_other_status_notifications`, `test_webhook_rejects_invalid_payload_and_card_validation`, `test_webhook_failure_is_durable` |
| T-10 | R-10 | Deadline boundaries, equality, UTC date dedup and terminal exclusions | `test_deadline_boundaries`, `test_reminders_overdue_boundary_dedup_and_roles`, `test_timezone_normalization_and_naive_rejection` |
| T-11 | R-11 | Hand-checked six-hour processing duration, historical cutoffs and chart | `test_weekly_metrics_real_processing_time_and_historical_snapshot`, `test_week_boundary_excludes_prior_completions`, `test_excel_report_values_format_chart_and_overdue` |
| T-12 | R-12 | Mixed good/bad rows, multiple errors, blank rows and formulas | `test_import_row_errors_continue_after_invalid_rows`, `test_import_header_errors_and_role_errors`, `test_cli_report_import_remind_deliver` |
| T-13 | R-13 | Page and assets, browser form, filters, approval and history | `test_web_template_and_assets`, `ci/e2e.py` |
| T-14 | R-14 | Reopened file database retains committed requests and audit | `test_sqlite_persistence_after_reopening`, `test_file_store_can_create_directories` |
| T-15 | R-15 | CLI commands, collection size, coverage gate and full CI pipeline | `test_cli_report_import_remind_deliver`, `test_serve_configuration_without_opening_port`, `ci/e2e.py`, `ci/measure.py` |
