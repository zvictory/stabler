# Tender Sourcing Phase 2 — RFQ, Quotation Entry, Auditable Award, Supplier Panel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the sourcing gap identified on 2026-07-30: today the SPA can only
*read* Supplier Quotations that someone tagged to a deal elsewhere. This phase adds
the full in-SPA chain — RFQ creation → quotation capture → normalized evaluation →
auditable award (`Tender Sourcing Decision`) — plus a Quotations tab on the supplier
panel, per the approved design (`docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md`, §5, §7).

**Architecture:** Reuse ERPNext-native documents wherever one exists (Request for
Quotation, Supplier Quotation) and tag them to the lot via `custom_crm_deal`
(mirroring v30/v34). The only NEW doctype is `Tender Sourcing Decision` — the award
record that turns "cheapest row highlighted" into "selected quotation with reason,
approver, and timestamp". All endpoints follow the Tender Master API conventions:
module gate + selected-company scope + `has_permission` + field allowlists.

**Tech Stack:** Frappe/ERPNext v16, Python `unittest` (frappe-free where possible),
Vue 3 Composition API, Vitest source contracts, Tabler CSS.

## Global Constraints

- No `/app/...` Frappe Desk links (hard rule). Missing CRUD is built in Stabler.
- No tenant-name conditionals; gates = module + role + company + `has_permission`.
- All money via `MoneyInput` / `font-monospace`; comparison math uses
  **`base_grand_total`** (company currency), never mixed-currency `grand_total`.
- Dates via `formatDate` / `DateInput`; no bare `<input type="date">`.
- Tables inherit global striping; statuses via `getStatusBadgeClass`; list pages
  use `ListToolbar` + `SkeletonRows`.
- Patches idempotent + pre-model-sync safe (`has_column` / Custom Field guards;
  patches.txt has NO `[post_model_sync]`).
- New module defaults follow governance doc: gate stays inside `tender` module
  (no new `enable_*` flag needed — sourcing is tender-owned, tenant = mikas).
- Every new user-facing string lands in all five CSVs (`en,ru,uz,uzc,tr`),
  appended with CRLF, never rewriting the files.
- Frappe v16 trap: no SQL functions in string SELECT fields — fetch plain
  columns, count in Python.
- `git add -A` forbidden; stage explicit paths.

## File Structure

### Create

- `stabler/patches/v62_rfq_tender_deal.py` — `custom_crm_deal` on Request for Quotation (mirrors v30).
- `stabler/stabler/doctype/tender_sourcing_decision/` — award doctype (+ controller + tests).
- `stabler/api/sourcing.py` — RFQ/SQ/decision endpoints (company-safe, module-gated).
- `stabler/public/js/pages/tender/SourcingWorkspace.vue` — RFQ list + quotation entry + evaluation + award panel (evolves SourcingCompare).
- `stabler/public/js/components/QuotationEntryDrawer.vue` — in-SPA Supplier Quotation form (items, currency, validity).
- `stabler/tests/test_sourcing_api.py`, `test_sourcing_decision.py`, `test_sourcing_spa.py` (+ Vitest `sourcing_workspace.test.mjs`).

### Modify

- `stabler/api/tender.py` — `po_control_board` vendor delta: compare on `base_grand_total` (bugfix, see Task 0).
- `stabler/public/js/components/Sidebar.vue` — dedupe children by path (duplicate "Tender CRM" bugfix, Task 0).
- `stabler/public/js/pages/purchasing/Suppliers.vue` — new **Quotations** tab.
- `stabler/api/purchasing.py` — `supplier_quotation_history(supplier, company)` endpoint.
- `stabler/public/js/router.js`, `TenderNav.vue` — route `/tender/sourcing` keeps its path, page becomes the workspace.
- `stabler/patches.txt`, `.github/frappe-free-tests.txt`, 5 × translations CSV.

---

### Task 0: Two shipped bugfixes (small, independent, do first)

**Files:** `Sidebar.vue`, `stabler/api/tender.py`, tests.

- [ ] **Step 1: Failing test — sidebar renders no duplicate path.**
  `test_tender_sidebar_navigation.py`: assert the `tenderChildren` source dedupes
  by `path` (a user holding both director+sourcing currently sees "Tender CRM" twice).
- [ ] **Step 2: Fix** — dedupe `tenderChildren` on `path` after the role filter.
- [ ] **Step 3: Failing test — PO-vs-quotation delta is company-currency.**
  `po_control_board` sums SQ `grand_total` (mixed currencies) against PO
  `base_grand_total`. Assert the quotation side reads `base_grand_total`.
- [ ] **Step 4: Fix + run** both suites GREEN, commit:
  `fix(tender): dedupe sidebar children; compare vendor deltas in company currency`

### Task 1: RFQ tagged to the lot (patch v62 + API)

**Files:** `v62_rfq_tender_deal.py`, `stabler/api/sourcing.py`, `test_sourcing_api.py`.

- [ ] **Step 1: Failing tests.** Patch idempotency (double-run safe, Custom Field
  guard); `list_rfqs(deal)` and `create_rfq(deal, suppliers, items, schedule_date)`:
  module gate, company scope, cross-company deal → `PermissionError`,
  RFQ lands with `custom_crm_deal = deal`, suppliers ⊆ permitted Suppliers.
- [ ] **Step 2: RED**, then implement patch + endpoints. `create_rfq` builds a
  native Request for Quotation (draft), one message per supplier left to the
  user; NO email sending in this slice.
- [ ] **Step 3:** Register tests in `.github/frappe-free-tests.txt`; GREEN; commit.

### Task 2: In-SPA Supplier Quotation entry

**Files:** `stabler/api/sourcing.py`, `QuotationEntryDrawer.vue`, tests.

- [ ] **Step 1: Failing tests.** `save_supplier_quotation(deal, supplier, currency,
  valid_till, items)` creates/updates a DRAFT native SQ tagged to the deal;
  submit stays a separate explicit call (`submit_supplier_quotation`) so policy
  counts can distinguish draft vs submitted; company + permission + module gates;
  item rates non-negative; rejects a supplier not on the deal's company.
- [ ] **Step 2: Implement.** Drawer UI: supplier Typeahead, currency select,
  `DateInput` for validity, `MoneyInput` rates, line add/remove.
- [ ] **Step 3: Contract tests** (`test_sourcing_spa.py`): drawer uses MoneyInput +
  DateInput, no `/app/` links, `⌘K` placeholder on search. GREEN; commit.

### Task 3: `Tender Sourcing Decision` — the auditable award

**Files:** new doctype, `stabler/api/sourcing.py`, `test_sourcing_decision.py`.

Fields: `company` (Link, reqd), `deal` (Link CRM Deal, reqd, unique-open),
`selected_quotation` (Link SQ, reqd), `cheapest_quotation` (Link SQ, read-only —
snapshot, cheapest ≠ selected are separate facts), `comparison_snapshot` (JSON:
normalized base-currency rows at decision time), `selection_reason` (Text, reqd),
`technical_result` (Select: Compliant/Deviations/NA), `policy_exception` (Check +
`exception_reason`), `status` (Draft → Approved, one-way), `approved_by`,
`approved_at` (server-stamped, like `mark_tender_submitted`).

- [ ] **Step 1: Failing schema/controller tests.** Status transition one-way;
  approve stamps user+time server-side and rejects self-set values; approved
  decision immutable except `status` no; selected SQ must belong to the deal;
  policy gaps (<5 quotes / <2 countries) REQUIRE `policy_exception` + reason.
- [ ] **Step 2: API.** `save_sourcing_decision(deal, ...)` (sourcing view),
  `approve_sourcing_decision(name)` (director view via `_require_tender_view`).
  Snapshot is computed server-side from `tender_quotations(deal)` at save time —
  the UI never posts its own numbers.
- [ ] **Step 3: Surface it.** SourcingWorkspace: "Kazananı seç" panel; PO control
  board marks the awarded vendor (`selected` badge) by reading the approved
  decision. GREEN; commit.

### Task 4: Supplier panel — Quotations tab

**Files:** `stabler/api/purchasing.py`, `Suppliers.vue`, tests.

- [ ] **Step 1: Failing tests.** `supplier_quotation_history(supplier, company)`:
  ONE query, company scope, permission filter; rows = SQ no, linked tender/lot
  label, base total, status, valid_till, decision outcome (awarded/lost/open —
  derived from approved decisions, never stored).
- [ ] **Step 2: UI.** Fourth tab "Quotations" after Ledger/Orders/Invoices;
  count badge; row click → `/tender/sourcing?deal=<deal>`; dates `formatDate`,
  money `font-monospace`.
- [ ] **Step 3:** GREEN + commit.

### Task 5: i18n, navigation, gates, release

- [ ] **Step 1:** Locale-key test additions; append new strings to 5 CSVs (CRLF!).
- [ ] **Step 2:** Route `/tender/sourcing` → SourcingWorkspace with
  `meta.module: "tender"`; TenderNav unchanged paths; direct-URL refresh loads
  populated (route-param guard, not `isCreate`).
- [ ] **Step 3:** Full suite: frappe-free list + `npm run test:js` +
  `make check` (split pre-existing debt vs new findings — fix only ours).
- [ ] **Step 4:** Deploy per CLAUDE.md (backup → dry-run rsync from `apps/` with
  `-rltzvn` shown before real run → build → **migrate ALL 7 sites** (v62 +
  new doctype) → restart at low traffic).
- [ ] **Step 5: Smoke (browser).** mikas: create RFQ → enter 2 quotations →
  see policy badges → save decision with exception reason → director approves →
  PO board shows awarded vendor → supplier panel Quotations tab lists both.
  msa: `/tender/sourcing` blocked; suppliers page unchanged. anjan: no tender UI.
- [ ] **Step 6:** Commit trailer `Co-Authored-By: Claude <noreply@anthropic.com>`;
  stage explicit paths only (never the whole `translations/` dir — 5 CSVs by name).

## Out of scope (Phase 3+)

RFQ e-posta/portal gönderimi, tedarikçi self-service portalı, Evrak Merkezi (DMS),
Tender Work Item / günlük plan, OCR ve e-imza. Bunlar ayrı planlarda ele alınacak.
