# Known Test Debt Baseline & Resolutions

This document tracks frappe-free test suite health and historical test debt resolutions.

## Active Debt Status
**Active Failing Modules**: 0 (all 85 frappe-free test modules are passing as of 2026-08-02).

---

## Resolved Stale Assertions & Debt Log (2026-08-02)

| Module | Test Name | Root Cause & Resolution |
| --- | --- | --- |
| `stabler.tests.test_company_scope_guard` | `test_all_company_endpoints_are_scoped` | Gated document endpoints in `api/tender_documents.py` call `_get_deal_and_master` helper which enforces `_assert_company_scope`. Resolved by registering `_get_deal_and_master` in `_SCOPE_TOKENS`. |
| `stabler.tests.test_director_board_source` | `test_root_carries_the_wrapper_class` | Legacy assertion checked for `class="director-board-page stbl-ds"`, but page now uses `<TenderPage>` design wrapper. Resolved by checking `<TenderPage` tag. |
| `stabler.tests.test_director_board_source` | `test_the_embedded_funnel_is_still_rendered` | Legacy assertion searched for exact `<TenderFunnel />` self-closing tag, but component is mounted as `<TenderFunnel pipeline-strip ...>`. Resolved by checking `<TenderFunnel`. |
| `stabler.tests.test_operations_desk_source` | `test_root_carries_the_wrapper_class` | Legacy assertion checked for `class="operations-desk-page stbl-ds"`, but page now uses `<TenderPage>` design wrapper. Resolved by checking `<TenderPage` tag. |
| `stabler.tests.test_seed_tender_demo` | `test_the_lost_lot_was_the_most_expensive_bid` & `test_the_portfolio_shows_a_spread_of_margins_not_one_number` | Test helper imported `_compute_bid_pnl` from `api/tender.py` (which imports `frappe`), breaking frappe-free execution. Resolved by extracting pure math to `api/_bid_pnl.py`. |
| `stabler.tests.test_tender_crm_source` | `test_root_carries_the_opt_in_wrapper` | Legacy assertion checked for `class="tender-crm-page stbl-ds"`, but page now uses `<TenderPage>` design wrapper. Resolved by checking `<TenderPage` tag. |
| `stabler.tests.test_tender_dashboard_behavior` | `test_ready_transition_occurs_when_required_documents_complete` & `test_ready_regression_clears_audit_and_recompletion_records_a_new_transition` | Document Center (K2 rule) derives document completion from attached files or written waivers. Legacy test payload passed raw `"done": 1` without files. Resolved by supplying `"files": [{"file_name": "..."}]`. |
| `stabler.tests.test_tender_sidebar_navigation` | `test_every_tender_screen_is_reachable_from_the_bar` | `/tender/documents` route was added as a deal-scoped drill-down page. Resolved by registering `/tender/documents` in `DRILL_DOWNS`. |
| `stabler.tests.test_tender_flow_source` | `test_it_is_on_the_design_layer`, `test_empty_and_unknown_are_different_words`, `test_only_edge_and_over_colour_the_wait` | `TenderFlow.vue` uses `<TenderPage>` wrapper and imports labels from `flowLabels.js`. Resolved by checking `<TenderPage` tag and inspecting `flowLabels.js`. |
