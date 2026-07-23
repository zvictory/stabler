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
