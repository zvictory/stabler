# Tender Master CRM Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved two-level Tender CRM foundation so one Tender Master aggregates multiple existing CRM Deal lot records and users can drill from tender to lot without leaving the Stabler SPA.

**Architecture:** `Tender Master` is a new company-scoped parent record. Existing `CRM Deal` remains the transactional lot record and receives one `custom_parent_tender` Link through an idempotent post-model-sync patch. Backend APIs enforce selected-company and document permission checks; the Vue page is a projection over those APIs and routes lot selection to the existing Stabler tender workspace.

**Tech Stack:** Frappe/ERPNext Python APIs and DocType JSON, Vue 3 Composition API, Vue Router, Vitest, Python `unittest`, existing Stabler API client and i18n CSV catalogs.

## Global Constraints

- Never link or redirect to Frappe Desk `/app/...`; all drill-down stays under `/stabler/#/...`.
- Preserve the existing `CRM Deal` as the lot and transaction unit; do not migrate RFQ, quotations, pricing, purchase, logistics, or finance ownership to `Tender Master`.
- Every named-record API verifies selected company, record company, module access, and `frappe.has_permission`.
- Dashboard, list, and Kanban are projections; no copied KPI or board-state tables.
- Monetary display uses company currency and `font-monospace`; no bare numeric money inputs.
- Tables use `.table` and inherit global striping; never add `table-striped`.
- All new user-facing labels use `t()` and exist in `en`, `ru`, `uz`, `uzc`, and `tr`.
- New no-site tests must be registered in `.github/frappe-free-tests.txt`.
- Use TDD: each production behavior is preceded by a failing test and verified red before implementation.
- Preserve unrelated changes and do not modify the original main worktree.

---

### Task 1: Tender Master schema and lot link

**Files:**
- Create: `stabler/stabler/doctype/tender_master/__init__.py`
- Create: `stabler/stabler/doctype/tender_master/tender_master.json`
- Create: `stabler/stabler/doctype/tender_master/tender_master.py`
- Create: `stabler/patches/v61_tender_master_link.py`
- Modify: `stabler/patches.txt`
- Modify: `stabler/hooks.py`
- Create: `stabler/tests/test_tender_master_schema.py`
- Modify: `.github/frappe-free-tests.txt`

**Interfaces:**
- Produces: DocType `Tender Master`.
- Produces: required `CRM Deal.custom_parent_tender` Link to `Tender Master`.
- Produces: `TenderMaster.validate()` enforcing `submission_deadline >= publication_date` when both dates exist.
- Produces: company-scoped `permission_query_conditions` and `has_permission` hooks for `Tender Master`.

- [ ] **Step 1: Write the failing schema contract test**

```python
class TestTenderMasterSchema(unittest.TestCase):
    def test_parent_schema_and_lot_link_patch_are_registered(self):
        schema = json.loads(TENDER_MASTER_JSON.read_text())
        fields = {field["fieldname"]: field for field in schema["fields"]}
        self.assertEqual(fields["company"]["options"], "Company")
        self.assertEqual(fields["company"]["reqd"], 1)
        self.assertEqual(fields["status"]["options"], "New\nSourcing\nBid Preparation\nSubmitted\nWon\nLost\nCancelled")
        patch_source = PATCH.read_text()
        self.assertIn('"custom_parent_tender"', patch_source)
        self.assertIn('"options": "Tender Master"', patch_source)
        self.assertIn("stabler.patches.v61_tender_master_link.execute", PATCHES.read_text())
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest stabler.tests.test_tender_master_schema -v`

Expected: FAIL because the DocType JSON and patch do not exist.

- [ ] **Step 3: Add the minimal schema and controller**

The DocType must have `track_changes: 1`, `autoname: "naming_series:"`, title field `title`, and these fields:

```json
[
  {"fieldname": "naming_series", "fieldtype": "Select", "options": "TND-.YYYY.-.#####", "default": "TND-.YYYY.-.#####", "reqd": 1},
  {"fieldname": "company", "fieldtype": "Link", "options": "Company", "reqd": 1, "in_standard_filter": 1},
  {"fieldname": "title", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
  {"fieldname": "tender_number", "fieldtype": "Data", "in_list_view": 1},
  {"fieldname": "buyer_name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
  {"fieldname": "source", "fieldtype": "Select", "options": "\nUZEX\nDirect\nPortal\nOther"},
  {"fieldname": "publication_date", "fieldtype": "Date"},
  {"fieldname": "submission_deadline", "fieldtype": "Datetime", "in_list_view": 1},
  {"fieldname": "currency", "fieldtype": "Link", "options": "Currency"},
  {"fieldname": "estimated_total", "fieldtype": "Currency", "options": "currency"},
  {"fieldname": "status", "fieldtype": "Select", "options": "New\nSourcing\nBid Preparation\nSubmitted\nWon\nLost\nCancelled", "default": "New", "reqd": 1, "in_list_view": 1},
  {"fieldname": "owner_user", "fieldtype": "Link", "options": "User"}
]
```

Controller validation:

```python
def validate(self):
    if self.publication_date and self.submission_deadline:
        if getdate(self.submission_deadline) < getdate(self.publication_date):
            frappe.throw(_("Submission deadline cannot be before publication date."))
```

Patch field:

```python
"CRM Deal": [
    {
        "fieldname": "custom_parent_tender",
        "label": "Parent Tender",
        "fieldtype": "Link",
        "options": "Tender Master",
        "insert_after": "custom_deal_type",
        "depends_on": 'eval:doc.custom_deal_type=="Tender"',
        "no_copy": 1,
    }
]
```

- [ ] **Step 4: Add permission hooks and register all no-site tests**

Add `Tender Master` to both `permission_query_conditions` and `has_permission` using the existing company-scope helpers. Register `stabler.tests.test_tender_master_schema` and the inherited no-site CRM tests:

```text
stabler.tests.test_crm_activity_controller
stabler.tests.test_crm_company_scope
stabler.tests.test_crm_daily_work_schema
stabler.tests.test_list_row_ordinals
stabler.tests.test_tender_master_schema
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
python -m unittest stabler.tests.test_tender_master_schema -v
make test
git add .github/frappe-free-tests.txt stabler/hooks.py stabler/patches.txt stabler/patches/v61_tender_master_link.py stabler/stabler/doctype/tender_master stabler/tests/test_tender_master_schema.py
git commit -m "feat(tender): add Tender Master schema"
```

Expected: all registered tests pass.

---

### Task 2: Company-safe Tender Master API

**Files:**
- Create: `stabler/api/tender_master.py`
- Create: `stabler/tests/test_tender_master_api.py`
- Modify: `.github/frappe-free-tests.txt`

**Interfaces:**
- Consumes: DocType `Tender Master` and `CRM Deal.custom_parent_tender`.
- Produces: `list_tender_masters(company=None, status=None, search=None, start=0, limit=50)`.
- Produces: `get_tender_master(name, company=None)`.
- Produces: `save_tender_master(data, company=None)`.
- Produces: `validate_deal_parent_tender(doc, method=None)` for CRM Deal hooks.
- Response shape: `{"records": [...], "total": int}` for list and `{"tender": {...}, "lots": [...], "summary": {...}}` for detail.

- [ ] **Step 1: Write failing behavior tests**

Cover these real behaviors with the repository’s fake-Frappe pattern:

```python
def test_get_tender_master_rejects_cross_company_name(self):
    with self.assertRaises(PermissionError):
        api.get_tender_master("TND-2026-00001", company="Other Co")

def test_get_tender_master_returns_only_permitted_child_lots(self):
    result = api.get_tender_master("TND-2026-00001", company="ACME")
    self.assertEqual([row["name"] for row in result["lots"]], ["LOT-ALLOWED"])

def test_save_tender_master_uses_allowlisted_fields(self):
    result = api.save_tender_master(
        {"title": "Network tender", "company": "ACME", "owner": "Administrator"},
        company="ACME",
    )
    self.assertNotIn("owner", result)

def test_parent_tender_company_must_match_deal_company(self):
    with self.assertRaises(ValueError):
        api.validate_deal_parent_tender(self.cross_company_deal)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest stabler.tests.test_tender_master_api -v`

Expected: FAIL because `stabler.api.tender_master` does not exist.

- [ ] **Step 3: Implement selected-company and permission guards**

Use one internal scope function:

```python
def _master_scope(name: str, company: str | None, ptype: str = "read"):
    selected_company = require_selected_company(company)
    master = frappe.get_doc("Tender Master", name)
    if master.company != selected_company:
        frappe.throw(_("Tender does not belong to the selected company."), frappe.PermissionError)
    if not frappe.has_permission("Tender Master", ptype=ptype, doc=master):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    return master, selected_company
```

The list query must filter `company=selected_company`; detail must query child `CRM Deal` rows with both `company=selected_company` and `custom_parent_tender=name`, then remove rows failing `frappe.has_permission("CRM Deal", "read", deal_name)`.

The summary is derived once from permitted lots:

```python
summary = {
    "lot_count": len(lots),
    "open_lot_count": sum(1 for lot in lots if lot["status"] not in {"Won", "Lost", "Cancelled"}),
    "estimated_total": sum(flt(lot.get("custom_estimated_value")) for lot in lots),
    "currency": master.currency,
}
```

`save_tender_master` allowlists only the Task 1 schema fields and calls `insert()` or `save()` so Frappe Version history remains intact.

- [ ] **Step 4: Register CRM Deal validation hook**

Add:

```python
doc_events = {
    "CRM Deal": {
        "validate": "stabler.api.tender_master.validate_deal_parent_tender",
    },
}
```

Merge with existing `doc_events` entries rather than replacing them.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
python -m unittest stabler.tests.test_tender_master_api -v
make test
git add .github/frappe-free-tests.txt stabler/api/tender_master.py stabler/hooks.py stabler/tests/test_tender_master_api.py
git commit -m "feat(tender): add Tender Master APIs"
```

Expected: API tests and the registered suite pass.

---

### Task 3: Tender CRM list, Kanban, and lot drill-down

**Files:**
- Create: `stabler/public/js/composables/tenderMaster.js`
- Create: `stabler/public/js/pages/tender/TenderCrm.vue`
- Create: `stabler/public/js/tests/tenderMaster.spec.js`
- Create: `stabler/tests/test_tender_master_spa_contract.py`
- Modify: `.github/frappe-free-tests.txt`

**Interfaces:**
- Consumes: `stabler.api.tender_master.list_tender_masters`.
- Consumes: `stabler.api.tender_master.get_tender_master`.
- Produces: `normalizeTenderMaster(record)` and `groupTenderMasters(records)` pure functions.
- Produces: `TenderCrm.vue` with `tender` and `lots` depth, plus `kanban` and `list` modes.
- Lot selection routes to existing `/tender/po-control?deal=<encoded CRM Deal name>`.

- [ ] **Step 1: Write failing Vitest contracts**

```javascript
import { describe, expect, it } from "vitest";
import { groupTenderMasters, normalizeTenderMaster } from "../composables/tenderMaster.js";

describe("Tender Master projections", () => {
  it("groups records by approved CRM stage order without duplicating them", () => {
    const grouped = groupTenderMasters([
      { name: "TND-1", status: "Sourcing" },
      { name: "TND-2", status: "Submitted" },
    ]);
    expect(grouped.map((lane) => lane.key)).toEqual([
      "New",
      "Sourcing",
      "Bid Preparation",
      "Submitted",
      "Closed",
    ]);
    expect(grouped.flatMap((lane) => lane.records).map((row) => row.name)).toEqual(["TND-1", "TND-2"]);
  });

  it("preserves zero values instead of replacing them with placeholders", () => {
    expect(normalizeTenderMaster({ lot_count: 0, estimated_total: 0 })).toMatchObject({
      lotCount: 0,
      estimatedTotal: 0,
    });
  });
});
```

- [ ] **Step 2: Run Vitest and verify RED**

Run: `npx vitest run stabler/public/js/tests/tenderMaster.spec.js`

Expected: FAIL because the composable does not exist.

- [ ] **Step 3: Implement the pure projection and page**

The page must:

- call the shared `call()` client with active `session.company`;
- show `SkeletonRows` while loading and `EmptyState` when empty;
- render one tender exactly once in either list or Kanban mode;
- show tender number/title, buyer, submission deadline, lot count, estimated company-currency total, status, owner, and document-readiness placeholder only when supplied by the API;
- open the parent detail in-place and render permitted lots returned by `get_tender_master`;
- preserve active company when reloading;
- route lot selection only inside the SPA.

- [ ] **Step 4: Add the SPA source contract**

```python
def test_tender_crm_stays_inside_spa_and_uses_parent_api(self):
    source = TENDER_CRM.read_text()
    self.assertIn("stabler.api.tender_master.list_tender_masters", source)
    self.assertIn("stabler.api.tender_master.get_tender_master", source)
    self.assertIn("/tender/po-control", source)
    self.assertNotIn("/app/", source)
    self.assertNotIn("table-striped", source)
```

Register `stabler.tests.test_tender_master_spa_contract`.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
npx vitest run stabler/public/js/tests/tenderMaster.spec.js
python -m unittest stabler.tests.test_tender_master_spa_contract -v
git add .github/frappe-free-tests.txt stabler/public/js/composables/tenderMaster.js stabler/public/js/pages/tender/TenderCrm.vue stabler/public/js/tests/tenderMaster.spec.js stabler/tests/test_tender_master_spa_contract.py
git commit -m "feat(tender): add hierarchical Tender CRM"
```

Expected: both suites pass.

---

### Task 4: Navigation, role visibility, and localization

**Files:**
- Modify: `stabler/public/js/router.js`
- Modify: `stabler/public/js/components/Sidebar.vue`
- Modify: `stabler/public/js/pages/tender/TenderNav.vue`
- Modify: `stabler/public/js/pages/tender/TenderControlTower.vue`
- Modify: `stabler/public/js/locales/en.csv`
- Modify: `stabler/public/js/locales/ru.csv`
- Modify: `stabler/public/js/locales/uz.csv`
- Modify: `stabler/public/js/locales/uzc.csv`
- Modify: `stabler/public/js/locales/tr.csv`
- Modify: `stabler/tests/test_tender_master_spa_contract.py`

**Interfaces:**
- Produces: route `/tender/crm`, name `tender-crm`, module `tender`.
- Produces: director and sourcing navigation to the same Tender CRM; backend permissions decide visible records.
- Produces: dashboard attention/KPI link target `/tender/crm` with query filters preserved.

- [ ] **Step 1: Extend the failing SPA contract**

```python
def test_tender_crm_route_and_navigation_are_wired(self):
    router = ROUTER.read_text()
    sidebar = SIDEBAR.read_text()
    nav = TENDER_NAV.read_text()
    self.assertIn('path: "/tender/crm"', router)
    self.assertIn('name: "tender-crm"', router)
    self.assertIn('path: "/tender/crm"', sidebar)
    self.assertIn('to="/tender/crm"', nav)
```

- [ ] **Step 2: Run the contract and verify RED**

Run: `python -m unittest stabler.tests.test_tender_master_spa_contract -v`

Expected: FAIL because the route and navigation do not exist.

- [ ] **Step 3: Wire the route and role-aware navigation**

Add the page import and route:

```javascript
{ path: "/tender/crm", name: "tender-crm", component: TenderCrm, meta: { title: t("Tender CRM"), module: "tender" } }
```

Show the Tender CRM child link for `director` or `sourcing` views. Update dashboard links that represent tender/lot portfolio counts to point to `/tender/crm`; do not change unrelated dashboard actions.

- [ ] **Step 4: Add exact localization keys**

Add translations for:

```text
Tender CRM
All tenders
Lots
Parent tender
Bid Preparation
Submission deadline
No tenders found
Back to all tenders
Open lot workspace
```

Every key must exist in `en`, `ru`, `uz`, `uzc`, and `tr`; Turkish values must be natural Turkish, not English copies.

- [ ] **Step 5: Run complete gates and commit**

Run:

```bash
python -m unittest stabler.tests.test_tender_master_spa_contract -v
npm run test:js
make check
git add stabler/public/js/router.js stabler/public/js/components/Sidebar.vue stabler/public/js/pages/tender/TenderNav.vue stabler/public/js/pages/tender/TenderControlTower.vue stabler/public/js/locales/en.csv stabler/public/js/locales/ru.csv stabler/public/js/locales/uz.csv stabler/public/js/locales/uzc.csv stabler/public/js/locales/tr.csv stabler/tests/test_tender_master_spa_contract.py
git commit -m "feat(tender): connect Tender CRM navigation"
```

Expected: Python tests, Vitest, ESLint, format checks, compilation, and SPA guards pass with no new warnings.

