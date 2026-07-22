# CI Packing List and GRN Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make linked Container packing lists the authoritative expected-quantity source for a CI's GRN, expose reconciliation/readiness in the CI SPA, and freeze that snapshot at the first submitted Truck Receipt.

**Architecture:** Add Frappe-free packing aggregation/reconciliation functions, then use them behind company-scoped Imports API helpers. GRN creation becomes an idempotent shell operation, an explicit refresh copies packing totals until the first receipt freezes them, and the CI form renders a focused logistics summary component.

**Tech Stack:** Python 3, Frappe/ERPNext v16, Django-style unittest/FrappeTestCase, Vue 3 Composition API, existing Stabler API client and Tabler CSS.

## Global Constraints

- The canonical route remains `/stabler/#/imports/commercial-invoices/:name`.
- Never add a Frappe Desk `/app/...` link or redirect.
- ERPNext native documents remain stock and financial truth.
- Every read and mutation must enforce company scope, Imports module gate and Frappe permission.
- Never branch on tenant/company name.
- Do not add Container-to-Truck product allocation.
- GRN Expected values come only from linked Container packing-list rows.
- Existing `Import Container Item` is reused; no duplicate packing-list DocType is created.
- Submitted Truck Receipts and Purchase Receipts are not changed in this plan.
- Monetary inputs must use `MoneyInput`; this plan adds no monetary inputs.
- Tables use the global striped style; do not add `table-striped`.

## Scope Split

The approved full design is intentionally split into independently reviewable plans:

1. This plan: packing-list aggregation, reconciliation, GRN shell/refresh/freeze and CI visibility.
2. CI workspace CRUD, shared sea lifecycle, multiple-GTD departure gates and independent Truck tracking.
3. Four-Truck supervisor matrix, inline receipt drawer, QC and mandatory exception photos.
4. GRN completion transaction, multi-GTD LCV consumption, CI delivery derivation, payment automation and migration reports.

---

## File Map

| File | Responsibility |
|---|---|
| `stabler/stabler/imports_module/packing_math.py` | Frappe-free aggregate and reconciliation rules |
| `stabler/stabler/imports_module/packing_service.py` | Frappe-backed scoped packing queries and GRN row synchronization |
| `stabler/tests/test_packing_math.py` | Unit tests for packing rules |
| `stabler/api/imports.py` | Scoped queries, CI payload, GRN create/refresh endpoints |
| `stabler/stabler/doctype/grn_checklist/grn_checklist.json` | Persist expected snapshot lock metadata |
| `stabler/stabler/imports_module/hooks.py` | Freeze the snapshot on first receipt submission |
| `stabler/stabler/doctype/import_container/import_container.py` | Block packing edits after freeze |
| `stabler/tests/test_ci_packing_grn_integration.py` | Frappe integration coverage for isolation and mutations |
| `stabler/public/js/api/imports.js` | Refresh endpoint client method |
| `stabler/public/js/pages/imports/CiLogisticsOverview.vue` | CI packing readiness, reconciliation and GRN action UI |
| `stabler/public/js/pages/imports/CommercialInvoiceForm.vue` | Mount focused logistics component without adding another monolith section |
| `stabler/tests/test_ci_logistics_workspace_source.py` | Frappe-free SPA invariant checks |

### Task 1: Pure Packing Aggregation and Reconciliation

**Files:**
- Create: `stabler/stabler/imports_module/packing_math.py`
- Create: `stabler/tests/test_packing_math.py`

**Interfaces:**
- Consumes: dictionaries with `container`, `item_code`, `item_name`, `box_qty`, `box_kg`, `total_kg`.
- Produces: `aggregate_container_items(rows)`, `reconcile_ci_items(ci_rows, packed_rows)`, and `packing_readiness(container_names, packed_rows, reconciliation)`.

- [ ] **Step 1: Write failing unit tests**

```python
from stabler.stabler.imports_module import packing_math


class TestPackingMath(unittest.TestCase):
	def test_aggregate_combines_same_item_across_containers(self):
		rows = [
			{"container": "C1", "item_code": "BEEF", "item_name": "Beef", "box_qty": 10, "box_kg": 20, "total_kg": 200},
			{"container": "C2", "item_code": "BEEF", "item_name": "Beef", "box_qty": 5, "box_kg": 20, "total_kg": 100},
		]
		self.assertEqual(packing_math.aggregate_container_items(rows), [{
			"item_code": "BEEF", "item_name": "Beef", "expected_boxes": 15,
			"expected_box_kg": 20.0, "expected_total_kg": 300.0,
		}])

	def test_readiness_requires_every_linked_container_and_matching_ci_kg(self):
		packed = packing_math.aggregate_container_items([
			{"container": "C1", "item_code": "BEEF", "box_qty": 10, "box_kg": 20, "total_kg": 200},
		])
		reconciliation = packing_math.reconcile_ci_items([{"item_code": "BEEF", "qty": 200}], packed)
		self.assertEqual(packing_math.packing_readiness(["C1", "C2"], ["C1"], reconciliation), "Incomplete")
		self.assertEqual(packing_math.packing_readiness(["C1"], ["C1"], reconciliation), "Ready")
```

- [ ] **Step 2: Run the unit test and verify RED**

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_packing_math -v`

Expected: FAIL with `ImportError: cannot import name 'packing_math'`.

- [ ] **Step 3: Implement the minimal pure module**

```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping


def aggregate_container_items(rows: Iterable[Mapping[str, object]]) -> list[dict]:
	agg: dict[str, dict] = defaultdict(lambda: {"item_name": "", "boxes": 0, "kg": 0.0})
	for row in rows:
		item = str(row.get("item_code") or "").strip()
		if not item:
			continue
		entry = agg[item]
		entry["item_name"] = entry["item_name"] or str(row.get("item_name") or item)
		entry["boxes"] += int(row.get("box_qty") or 0)
		entry["kg"] += float(row.get("total_kg") or 0)
	return [{
		"item_code": item,
		"item_name": values["item_name"],
		"expected_boxes": values["boxes"],
		"expected_box_kg": round(values["kg"] / values["boxes"], 3) if values["boxes"] else 0.0,
		"expected_total_kg": round(values["kg"], 3),
	} for item, values in sorted(agg.items())]


def reconcile_ci_items(ci_rows: Iterable[Mapping[str, object]], packed_rows: Iterable[Mapping[str, object]]) -> list[dict]:
	ci = {str(row.get("item_code") or row.get("item") or ""): float(row.get("qty") or 0) for row in ci_rows}
	packed = {str(row.get("item_code") or ""): float(row.get("expected_total_kg") or 0) for row in packed_rows}
	return [{"item_code": item, "ci_kg": round(ci.get(item, 0), 3), "packed_kg": round(packed.get(item, 0), 3), "difference_kg": round(packed.get(item, 0) - ci.get(item, 0), 3), "matches": abs(packed.get(item, 0) - ci.get(item, 0)) <= 0.01} for item in sorted(set(ci) | set(packed))]


def packing_readiness(container_names: Iterable[str], containers_with_rows: Iterable[str], reconciliation: Iterable[Mapping[str, object]]) -> str:
	names = set(container_names)
	if not names or not names.issubset(set(containers_with_rows)):
		return "Incomplete"
	return "Ready" if all(bool(row.get("matches")) for row in reconciliation) else "Mismatch"
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_packing_math -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add stabler/stabler/imports_module/packing_math.py stabler/tests/test_packing_math.py
git commit -m "feat(imports): aggregate container packing lists"
```

### Task 2: Company-Scoped CI Packing Summary

**Files:**
- Create: `stabler/stabler/imports_module/packing_service.py`
- Modify: `stabler/api/imports.py`
- Create: `stabler/tests/test_ci_packing_grn_integration.py`

**Interfaces:**
- Consumes: Task 1 packing functions and a CI name already checked by `get_commercial_invoice`.
- Produces: `packing_service.summary_for_ci(commercial_invoice, company)` and CI payload keys `packing_summary` and `grn`.

- [ ] **Step 1: Write a failing Frappe integration test**

```python
import frappe
from frappe.tests.utils import FrappeTestCase
from stabler.api import imports


class CIPackingGrnIntegrationTest(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		self.item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		if not all((self.company, self.supplier, self.item)):
			self.skipTest("Company, Supplier and Item fixtures are required")
		settings = frappe.get_single("Stabler Settings")
		module = next((row for row in settings.company_modules or [] if row.company == self.company), None)
		module = module or settings.append("company_modules", {"company": self.company})
		module.enable_imports = 1
		settings.save(ignore_permissions=True)
		self.ci = frappe.new_doc("Commercial Invoice")
		self.ci.update({"company": self.company, "supplier": self.supplier, "ci_number": frappe.generate_hash(length=10), "ci_date": frappe.utils.today()})
		self.ci.append("items", {"item": self.item, "qty": 300, "boxes": 15, "box_weight_kg": 20})
		self.ci.insert(ignore_permissions=True)
		self.containers = []
		for suffix, boxes, kg in (("A", 10, 200), ("B", 5, 100)):
			container = frappe.new_doc("Import Container")
			container.update({"company": self.company, "commercial_invoice": self.ci.name, "container_number": f"TEST-{suffix}-{frappe.generate_hash(length=6)}"})
			container.append("items", {"item_code": self.item, "box_qty": boxes, "box_kg": 20, "total_kg": kg})
			container.insert(ignore_permissions=True)
			self.containers.append(container)
		self.container_1, self.container_2 = self.containers

	def tearDown(self):
		frappe.db.rollback()

	def test_ci_payload_aggregates_only_same_company_linked_containers(self):
		other_ci = frappe.copy_doc(self.ci)
		other_ci.ci_number = frappe.generate_hash(length=10)
		other_ci.insert(ignore_permissions=True)
		other = frappe.new_doc("Import Container")
		other.update({"company": self.company, "commercial_invoice": other_ci.name, "container_number": f"OTHER-{frappe.generate_hash(length=6)}"})
		other.append("items", {"item_code": self.item, "box_qty": 50, "box_kg": 20, "total_kg": 1000})
		other.insert(ignore_permissions=True)
		payload = imports.get_commercial_invoice(self.ci.name)
		self.assertEqual(payload["packing_summary"]["status"], "Ready")
		self.assertEqual(payload["packing_summary"]["expected_items"][0]["expected_total_kg"], 300.0)
		self.assertIsNone(payload["grn"])
```

- [ ] **Step 2: Run the integration test and verify RED**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration --case CIPackingGrnIntegrationTest.test_ci_payload_aggregates_only_same_company_linked_containers`

Expected: FAIL because `packing_summary` is absent.

- [ ] **Step 3: Add scoped query and payload fields**

```python
import frappe

from stabler.stabler.imports_module import packing_math


def summary_for_ci(commercial_invoice: str, company: str) -> dict:
	containers = frappe.get_all("Import Container", filters={"commercial_invoice": commercial_invoice, "company": company}, fields=["name", "container_number"], order_by="creation asc")
	container_names = [row.name for row in containers]
	rows = frappe.get_all("Import Container Item", filters={"parent": ["in", container_names], "parenttype": "Import Container", "parentfield": "items"}, fields=["parent as container", "item_code", "item_name", "box_qty", "box_kg", "total_kg"]) if container_names else []
	from stabler.stabler.imports_module import packing_math
	expected = packing_math.aggregate_container_items(rows)
	ci_items = frappe.get_all("Commercial Invoice Item", filters={"parent": commercial_invoice, "parenttype": "Commercial Invoice", "parentfield": "items"}, fields=["item as item_code", "qty"])
	reconciliation = packing_math.reconcile_ci_items(ci_items, expected)
	return {"status": packing_math.packing_readiness(container_names, {row.container for row in rows}, reconciliation), "container_count": len(container_names), "containers_with_items": len({row.container for row in rows}), "expected_items": expected, "reconciliation": reconciliation}
```

Place that function in `packing_service.py`. In `imports.py`, import
`_assert_can_write` beside `_assert_can_read`, import `packing_service`, and add:

```python
"packing_summary": packing_service.summary_for_ci(name, doc.company),
"grn": frappe.db.get_value("GRN Checklist", {"commercial_invoice": name, "company": doc.company}, ["name", "docstatus", "receipt_status", "expected_snapshot_locked"], as_dict=True),
```

- [ ] **Step 4: Run focused and existing CI tests**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: PASS with no skipped assertions on the configured test site.

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_imports_api_invariants -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stabler/stabler/imports_module/packing_service.py stabler/api/imports.py stabler/tests/test_ci_packing_grn_integration.py
git commit -m "feat(imports): expose CI packing readiness"
```

### Task 3: GRN Shell, Refresh and Snapshot Metadata

**Files:**
- Modify: `stabler/stabler/doctype/grn_checklist/grn_checklist.json`
- Modify: `stabler/stabler/imports_module/packing_service.py`
- Modify: `stabler/stabler/imports_module/hooks.py`
- Modify: `stabler/api/imports.py`
- Modify: `stabler/public/js/api/imports.js`
- Modify: `stabler/tests/test_ci_packing_grn_integration.py`

**Interfaces:**
- Consumes: `packing_service.summary_for_ci(commercial_invoice, company)`.
- Produces: `packing_service.replace_grn_expected_rows(grn, expected_items)`, `packing_service.create_or_get_grn(ci, ignore_permissions)`, `refresh_grn_expected_quantities(name)`, and response `{name, packing_status, expected_snapshot_locked}`.

- [ ] **Step 1: Add failing integration cases**

```python
def test_create_grn_uses_packing_aggregate_not_ci_lines(self):
	result = imports.create_grn_for_ci(self.ci.name)
	grn = frappe.get_doc("GRN Checklist", result["name"])
	self.assertEqual(grn.grn_items[0].expected_total_kg, 300.0)

def test_incomplete_packing_creates_shell_without_invented_rows(self):
	self.container_2.set("items", [])
	self.container_2.save(ignore_permissions=True)
	result = imports.create_grn_for_ci(self.ci.name)
	self.assertEqual(result["packing_status"], "Incomplete")
	grn = frappe.get_doc("GRN Checklist", result["name"])
	self.assertEqual(grn.grn_items[0].expected_total_kg, 200.0)

def test_stuffed_hook_uses_the_same_packing_aggregate(self):
	self.ci.status = "STUFFED"
	self.ci.save(ignore_permissions=True)
	grn_name = frappe.db.get_value("GRN Checklist", {"commercial_invoice": self.ci.name})
	grn = frappe.get_doc("GRN Checklist", grn_name)
	self.assertEqual(grn.grn_items[0].expected_total_kg, 300.0)
```

- [ ] **Step 2: Run and verify RED**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: FAIL because GRN creation still copies the 300 kg CI line instead of the remaining 200 kg packing aggregate.

- [ ] **Step 3: Add lock fields and replace/refresh implementation**

Add `expected_snapshot_locked` and `expected_snapshot_locked_at` to `field_order`
immediately before `section_items`, then add the read-only field definitions:

```json
{"default": "0", "fieldname": "expected_snapshot_locked", "fieldtype": "Check", "label": "Expected Snapshot Locked", "read_only": 1},
{"fieldname": "expected_snapshot_locked_at", "fieldtype": "Datetime", "label": "Expected Snapshot Locked At", "read_only": 1}
```

Implement:

```python
def replace_grn_expected_rows(grn, expected_items: list[dict]) -> None:
	grn.set("grn_items", [])
	for item in expected_items:
		grn.append("grn_items", item)


def create_or_get_grn(ci, *, ignore_permissions: bool) -> dict:
	existing = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci.name, "company": ci.company})
	if existing:
		locked = bool(frappe.db.get_value("GRN Checklist", existing, "expected_snapshot_locked"))
		return {"name": existing, "created": False, "packing_status": summary_for_ci(ci.name, ci.company)["status"], "expected_snapshot_locked": locked}
	summary = summary_for_ci(ci.name, ci.company)
	grn = frappe.new_doc("GRN Checklist")
	grn.company = ci.company
	grn.commercial_invoice = ci.name
	grn.supplier = ci.supplier
	grn.expected_arrival_date = ci.get("eta_transit_port")
	replace_grn_expected_rows(grn, summary["expected_items"])
	grn.insert(ignore_permissions=ignore_permissions)
	return {"name": grn.name, "created": True, "packing_status": summary["status"], "expected_snapshot_locked": False}


@frappe.whitelist()
def refresh_grn_expected_quantities(name: str):
	if not name or not frappe.db.exists("GRN Checklist", name):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(name))
	company = _company_of("GRN Checklist", name)
	_assert_imports_access(company)
	_assert_can_write("GRN Checklist", name)
	grn = frappe.get_doc("GRN Checklist", name)
	if grn.docstatus != 0 or cint(grn.expected_snapshot_locked):
		frappe.throw(_("Expected quantities are locked after the first submitted Truck Receipt."))
	summary = packing_service.summary_for_ci(grn.commercial_invoice, company)
	packing_service.replace_grn_expected_rows(grn, summary["expected_items"])
	grn.save(ignore_permissions=False)
	return {"name": grn.name, "packing_status": summary["status"], "expected_snapshot_locked": False}
```

Change `create_grn_for_ci` to call `packing_service.create_or_get_grn(ci, ignore_permissions=False)`; for an existing GRN, check read permission before returning it. Replace the body of `create_grn_for_ci_hook` in `hooks.py` with `packing_service.create_or_get_grn(ci, ignore_permissions=True)`. Both paths must allow a shell with zero rows when no packing list exists, preserve partial aggregate rows while readiness is blocked, and never copy CI lines. Add the client method:

```javascript
refreshGrnExpectedQuantities: (name) => call(`${P}.refresh_grn_expected_quantities`, { name }),
```

- [ ] **Step 4: Run migration and tests**

Run: `bench --site msaerp.local migrate`

Expected: `GRN Checklist` gains both lock columns without errors.

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stabler/stabler/doctype/grn_checklist/grn_checklist.json stabler/stabler/imports_module/packing_service.py stabler/stabler/imports_module/hooks.py stabler/api/imports.py stabler/public/js/api/imports.js stabler/tests/test_ci_packing_grn_integration.py
git commit -m "feat(imports): refresh GRN expected packing snapshot"
```

### Task 4: Freeze Expected Snapshot and Protect Packing Lists

**Files:**
- Modify: `stabler/stabler/imports_module/hooks.py`
- Modify: `stabler/stabler/doctype/import_container/import_container.py`
- Modify: `stabler/tests/test_ci_packing_grn_integration.py`

**Interfaces:**
- Consumes: `GRN Checklist.expected_snapshot_locked` from Task 3.
- Produces: `_lock_grn_expected_snapshot(grn_name)` and `ImportContainer._check_packing_snapshot_lock()`.

- [ ] **Step 1: Write failing integration cases**

```python
def test_snapshot_lock_is_persisted(self):
	from stabler.stabler.imports_module.hooks import _lock_grn_expected_snapshot
	grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
	_lock_grn_expected_snapshot(grn_name)
	grn = frappe.get_doc("GRN Checklist", grn_name)
	self.assertEqual(grn.expected_snapshot_locked, 1)
	self.assertIsNotNone(grn.expected_snapshot_locked_at)

def test_snapshot_lock_rejects_incomplete_packing(self):
	from stabler.stabler.imports_module.hooks import _lock_grn_expected_snapshot
	self.container_2.set("items", [])
	self.container_2.save(ignore_permissions=True)
	grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
	with self.assertRaises(frappe.ValidationError):
		_lock_grn_expected_snapshot(grn_name)

def test_locked_snapshot_blocks_item_change_but_allows_seal_change(self):
	from stabler.stabler.imports_module.hooks import _lock_grn_expected_snapshot
	grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
	_lock_grn_expected_snapshot(grn_name)
	self.container_1.seal_number = "NEW-SEAL"
	self.container_1.save(ignore_permissions=True)
	self.container_1.items[0].total_kg = 999
	with self.assertRaises(frappe.ValidationError):
		self.container_1.save(ignore_permissions=True)

def test_submit_hook_locks_before_creating_purchase_receipt(self):
	import inspect
	from stabler.stabler.imports_module import hooks
	body = inspect.getsource(hooks.truck_receipt_on_submit)
	self.assertLess(body.index("_lock_grn_expected_snapshot"), body.index("_create_pr_for_truck_receipt"))
```

- [ ] **Step 2: Run and verify RED**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: FAIL because neither freeze nor edit protection exists.

- [ ] **Step 3: Implement transactional freeze and item comparison**

In `hooks.py`, import `now_datetime` and `packing_service`, then call `_lock_grn_expected_snapshot(doc.grn_checklist)` immediately before `_create_pr_for_truck_receipt(doc)`:

```python
def _lock_grn_expected_snapshot(grn_name: str) -> None:
	grn = frappe.get_doc("GRN Checklist", grn_name)
	if grn.expected_snapshot_locked:
		return
	summary = packing_service.summary_for_ci(grn.commercial_invoice, grn.company)
	if summary["status"] != "Ready":
		frappe.throw(frappe._("Container packing lists must be complete and reconciled before the first Truck Receipt can be submitted."))
	packing_service.replace_grn_expected_rows(grn, summary["expected_items"])
	grn.expected_snapshot_locked = 1
	grn.expected_snapshot_locked_at = now_datetime()
	grn.save(ignore_permissions=True)
```

In `ImportContainer.validate`, import `cint` and `flt`, preserve the existing status validation and add:

```python
def _packing_signature(self, rows) -> tuple:
	return tuple(sorted((row.item_code, cint(row.box_qty), flt(row.box_kg), flt(row.total_kg)) for row in rows or []))

def _check_packing_snapshot_lock(self) -> None:
	before = self.get_doc_before_save()
	if not before or self._packing_signature(before.items) == self._packing_signature(self.items):
		return
	grn = frappe.db.get_value("GRN Checklist", {"commercial_invoice": self.commercial_invoice}, ["name", "expected_snapshot_locked"], as_dict=True)
	if grn and grn.expected_snapshot_locked:
		frappe.throw(frappe._("Packing-list quantities are locked by GRN {0} after the first submitted Truck Receipt.").format(grn.name))
```

- [ ] **Step 4: Run focused integration and receipt tests**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: PASS.

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_receipt_math stabler.tests.test_grn_variance_math -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stabler/stabler/imports_module/hooks.py stabler/stabler/doctype/import_container/import_container.py stabler/tests/test_ci_packing_grn_integration.py
git commit -m "feat(imports): freeze GRN expected snapshot"
```

### Task 5: CI Logistics Summary and GRN Actions in the SPA

**Files:**
- Create: `stabler/public/js/pages/imports/CiLogisticsOverview.vue`
- Modify: `stabler/public/js/pages/imports/CommercialInvoiceForm.vue`
- Create: `stabler/tests/test_ci_logistics_workspace_source.py`

**Interfaces:**
- Consumes: `packingSummary`, `grn`, `commercialInvoice`, `loading` props and emits `reload`.
- Produces: an in-route packing reconciliation table plus Create/Open GRN and Refresh Expected actions.

- [ ] **Step 1: Add failing source-invariant tests**

```python
class TestCiLogisticsWorkspaceSource(unittest.TestCase):
	def test_component_has_no_desk_redirect(self):
		self.assertNotIn("/app/", SOURCE)

	def test_component_exposes_packing_and_grn_actions(self):
		self.assertIn("packingSummary.reconciliation", SOURCE)
		self.assertIn("createGrnForCi", SOURCE)
		self.assertIn("refreshGrnExpectedQuantities", SOURCE)

	def test_ci_form_mounts_focused_component(self):
		self.assertIn("<CiLogisticsOverview", CI_FORM)
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_logistics_workspace_source -v`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the focused component and mount it**

Create `CiLogisticsOverview.vue`:

```vue
<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ commercialInvoice: { type: String, required: true }, packingSummary: { type: Object, required: true }, grn: { type: Object, default: null } });
const emit = defineEmits(["reload"]);
const router = useRouter();
const toast = useToast();
const busy = ref(false);

async function createOrOpenGrn() {
	if (props.grn?.name) return router.push(`/imports/grn-checklists/${props.grn.name}`);
	busy.value = true;
	try {
		const result = await importsApi.createGrnForCi(props.commercialInvoice);
		emit("reload");
		return router.push(`/imports/grn-checklists/${result.name}`);
	} catch (error) {
		toast.error(error?.message || t("Could not create the GRN."));
	} finally {
		busy.value = false;
	}
}

async function refreshExpected() {
	busy.value = true;
	try {
		await importsApi.refreshGrnExpectedQuantities(props.grn.name);
		toast.success(t("Expected quantities refreshed from container packing lists."));
		emit("reload");
	} catch (error) {
		toast.error(error?.message || t("Could not refresh expected quantities."));
	} finally {
		busy.value = false;
	}
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-header d-flex align-items-center">
			<h3 class="card-title mb-0">{{ t("Logistics readiness") }}</h3>
			<span class="badge ms-2" :class="packingSummary.status === 'Ready' ? 'bg-success-lt' : packingSummary.status === 'Mismatch' ? 'bg-warning-lt' : 'bg-secondary-lt'">{{ t(packingSummary.status) }}</span>
			<div class="ms-auto d-flex gap-2">
				<button v-if="grn && !grn.expected_snapshot_locked" type="button" class="btn btn-outline-primary btn-sm" :disabled="busy" @click="refreshExpected">{{ t("Refresh expected quantities") }}</button>
				<button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="createOrOpenGrn">{{ grn ? t("Open GRN") : t("Create GRN") }}</button>
			</div>
		</div>
		<div class="card-body">
			<p class="text-secondary mb-3">{{ t("{ready} of {total} containers have packing-list rows.", { ready: packingSummary.containers_with_items, total: packingSummary.container_count }) }}</p>
			<div v-if="packingSummary.status !== 'Ready'" class="alert alert-warning">{{ packingSummary.status === "Incomplete" ? t("Complete every container packing list before port-transfer readiness.") : t("Resolve CI versus packed quantity differences before port-transfer readiness.") }}</div>
			<div class="table-responsive">
				<table class="table table-vcenter">
					<thead><tr><th>{{ t("Item") }}</th><th class="text-end">{{ t("CI kg") }}</th><th class="text-end">{{ t("Packed kg") }}</th><th class="text-end">{{ t("Difference kg") }}</th></tr></thead>
					<tbody>
						<tr v-for="row in packingSummary.reconciliation" :key="row.item_code">
							<td class="font-monospace">{{ row.item_code }}</td><td class="text-end font-monospace">{{ row.ci_kg }}</td><td class="text-end font-monospace">{{ row.packed_kg }}</td><td class="text-end font-monospace" :class="row.matches ? 'text-success' : 'text-danger'">{{ row.difference_kg }}</td>
						</tr>
						<tr v-if="!packingSummary.reconciliation.length"><td colspan="4" class="text-secondary text-center">{{ t("No packing-list items yet.") }}</td></tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
```

In `CommercialInvoiceForm.vue`, import the component and mount it for saved CIs:

```vue
<CiLogisticsOverview
	v-if="!isCreate"
	:commercial-invoice="form.name"
	:packing-summary="form.packing_summary"
	:grn="form.grn"
	@reload="loadDoc"
/>
```

Extend `blankForm()` with `packing_summary: { status: "Incomplete", container_count: 0, containers_with_items: 0, expected_items: [], reconciliation: [] }` and `grn: null`.

- [ ] **Step 4: Run source tests and browser verification**

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_logistics_workspace_source -v`

Expected: PASS.

Run: `bench build --app stabler`

Expected: the Stabler assets build without a compile error. In the signed-in browser, open one saved CI and verify the readiness badge, mismatch rows, Create/Open GRN action and Refresh action all stay under `/stabler/#/...`.

- [ ] **Step 5: Commit**

```bash
git add stabler/public/js/pages/imports/CiLogisticsOverview.vue stabler/public/js/pages/imports/CommercialInvoiceForm.vue stabler/tests/test_ci_logistics_workspace_source.py
git commit -m "feat(imports): show CI packing and GRN readiness"
```

### Task 6: Phase Verification

**Files:**
- Modify only if verification exposes a defect in a file already listed above.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: verified Phase 1 foundation ready for review.

- [ ] **Step 1: Run all Frappe-free tests for this slice**

Run: `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_packing_math stabler.tests.test_ci_logistics_workspace_source stabler.tests.test_receipt_math stabler.tests.test_grn_variance_math stabler.tests.test_imports_api_invariants -v`

Expected: all tests PASS; zero skips.

- [ ] **Step 2: Run the real-site integration suite**

Run: `bench --site msaerp.local run-tests --app stabler --module stabler.tests.test_ci_packing_grn_integration`

Expected: all tests PASS; any fixture skip is treated as incomplete verification and the fixtures must be supplied before proceeding.

- [ ] **Step 3: Verify schema and SPA behavior**

Run: `bench --site msaerp.local migrate`

Expected: no migration error.

Run: `bench build --app stabler`

Expected: no compile error. Browser evidence must cover Ready, Incomplete and Mismatch CIs; shell GRN creation; refresh before receipt; and a rejected refresh after snapshot lock.

- [ ] **Step 4: Verify repository invariants**

Run: `git diff --check`

Expected: no output.

Run: `rg -n '/app/' stabler/public/js/pages/imports/CiLogisticsOverview.vue`

Expected: no output.

- [ ] **Step 5: Record verification evidence**

Append the exact test commands, PASS counts, site name and browser cases to the implementation task handoff. Do not claim completion if a test was skipped or the real site was unavailable.
