# Task 4 — Tender Execution Workspace

## Status

Implemented and committed as `9a32b6c feat(tender): add tender execution workspace`.

## Changes

- Added `tender_workspace(deal)` with company scope, document permissions, batch item-link traversal, and finance-role gating.
- Added query-backed Overview, Vendor & PO, Delivery, and permission-gated Finance tabs.
- Preserved `tender-po-control` and the existing PO route; delivery and invoice rows do not link to Frappe Desk.
- Reused the existing PO lanes and landed-cost editor in Vendor & PO; included supplier quotation policy badges and vendor selection.
- Kept `router.js` untouched because it already preserves the required
  `tender-po-control` route; its current unstaged edit belongs to another task.

## Verification

```sh
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_workspace_spa \
  stabler.tests.test_tender_dashboard_behavior -v
```

Result: `Ran 31 tests ... OK`.

Also parsed all three changed Vue SFCs with `@vue/compiler-sfc` and ran
`git diff --check` for Task 4 files successfully. The repository root has no
`npm run build` script, so a production bundle could not be run.

## Task 3 dependency

None. Task 3's dashboard components are already complete; Task 4 does not
depend on its API review fix. Both tasks currently touch `tender.py` and the
behaviour test file, so commits are being serialized to preserve the review
hunks.

## Finance review follow-up

- Finance totals now deduplicate invoice rows by invoice name, because one
  Purchase or Sales Invoice can be linked to multiple deal orders.
- AP, AR, paid, outstanding, and actual invoice margin now aggregate ERPNext
  base-currency fields and return the company currency for display.
- Finance now returns the planned profit from the existing tender bid-pricing
  P&L and renders it next to actual invoice margin.

Verification passed on 2026-07-24:

```sh
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_workspace_spa \
  stabler.tests.test_tender_dashboard_behavior -v
```

All 34 tests passed. The three Tender Workspace Vue SFCs also parse cleanly
with `@vue/compiler-sfc`; `python3 -m py_compile` and `git diff --check` pass
for the follow-up files.

## i18n follow-up

- Added `TenderDocumentChain.vue` to the Tender Dashboard i18n source scan.
- Added nonempty `Purchase execution`, `Sales execution`, `Sales order`, and
  `No linked documents` translations in en, ru, uz, uzc, and tr.

Verification passed on 2026-07-24:

```sh
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_i18n \
  stabler.tests.test_tender_workspace_spa \
  stabler.tests.test_tender_dashboard_behavior -v
```

All 38 tests passed. `TenderDocumentChain.vue` also parses cleanly with
`@vue/compiler-sfc`, and `git diff --check` passes for the i18n follow-up
files.
