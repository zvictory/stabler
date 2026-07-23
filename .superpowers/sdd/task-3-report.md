# Task 3 — P1 Executive Control Tower

## Status

Completed and committed.

## Commit

`92805a8 feat(tender): redesign executive control tower`

## Changed files

- `stabler/public/js/pages/Dashboard.vue`
- `stabler/public/js/pages/tender/TenderTrendChart.vue`
- `stabler/public/js/pages/tender/TenderExecutionFlow.vue`
- `stabler/public/js/pages/tender/TenderPortfolioPreview.vue`
- `stabler/tests/test_tender_dashboard_spa.py`

## Verification

Initial red test command (expected failure before implementation):

```sh
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
```

Output: `FAILED (failures=1, errors=1)` because the three P1 component files and Dashboard composition were absent.

Final test command:

```sh
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa stabler.tests.test_tender_dashboard_i18n -v
```

Output:

```text
test_company_disabled_tender_keeps_financial_fallback ... ok
test_dashboard_error_is_announced_and_focuses_retry ... ok
test_dashboard_execution_cards_stack_on_phone ... ok
test_dashboard_gates_role_specific_destinations ... ok
test_dashboard_has_accessible_spa_drilldowns_without_desk_links ... ok
test_dashboard_presents_explicit_lifecycle_and_execution_counts ... ok
test_dashboard_uses_capability_gate_and_aggregate_endpoint ... ok
test_p1_components_preserve_visual_and_keyboard_accessibility ... ok
test_p1_dashboard_composes_accessible_visuals ... ok
test_sales_order_board_reads_dashboard_period_and_status ... ok
test_every_dashboard_copy_key_has_a_nonempty_translation ... ok

Ran 11 tests in 0.023s

OK
```

## Concerns

- Task 3 consumes the `trend`, `portfolio_preview`, and `execution.invoice_status` API extensions from Task 2; the UI safely renders empty arrays/counts until those aggregates are available.
- Existing unrelated working-tree changes were preserved. `git diff --check` reports pre-existing trailing whitespace outside Task 3 files in Kassa sources.

## Review follow-up

Completed the Task 3 review fixes:

- Added non-empty translations for the visual components in `en`, `ru`, `uz`, `uzc`, and `tr`; the translation contract now scans all three P1 components and Turkish.
- Localized the mobile portfolio table data labels with `t()`.
- Kept KPI queries scoped to the selected period while requesting and returning a separate three-month trend range.

Verification:

```text
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa stabler.tests.test_tender_dashboard_i18n -v

Ran 12 tests in 0.028s

OK

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_behavior -v

Ran 30 tests in 0.027s

OK
```
