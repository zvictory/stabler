# MIKAS Tender Control Tower Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved P1 Executive Precision tender dashboard, role-aware Tender sidebar, and tender-scoped Vendor/PO workspace without breaking existing Stabler routes.

**Architecture:** Extend the existing `tender_dashboard` response with monthly trend and value-weighted portfolio progress, then render those fields through small Vue components owned by `Dashboard.vue`. Keep `/tender/po-control?deal=...` stable and evolve `PoControlBoard.vue` into a four-tab workspace that composes existing intake, quotation, PO, landed-cost, delivery, and finance data.

**Tech Stack:** Frappe/ERPNext v16, Python, Vue 3 Composition API, Pinia, Vue Router, Tabler CSS/icons, inline SVG, Python `unittest`, Node behavior tests.

## Global Constraints

- No `/app/...` Frappe Desk links or redirects.
- No tenant-name conditionals; use company, module, permission, and role gates.
- No new chart or icon dependency.
- ERPNext native documents remain financial and stock truth.
- All monetary inputs use `MoneyInput`.
- Currency values use `font-monospace`.
- Tables inherit global striping; do not add `table-striped`.
- Finance fields are excluded by the backend for unauthorized roles.
- Preserve `/dashboard`, `/tender/po-control`, and existing query-string deep links.
- UI keys must exist in `en`, `ru`, `uz`, `uzc`, and `tr`.

---

## File Structure

### Create

- `stabler/public/js/pages/tender/TenderTrendChart.vue` — accessible inline-SVG monthly trend.
- `stabler/public/js/pages/tender/TenderExecutionFlow.vue` — ERPNext document lifecycle visualization.
- `stabler/public/js/pages/tender/TenderPortfolioPreview.vue` — tender progress table and drill-down.
- `stabler/public/js/pages/tender/TenderWorkspaceTabs.vue` — query-backed workspace tab navigation.
- `stabler/public/js/pages/tender/TenderDocumentChain.vue` — PR/PI/DN/SI operational and finance rows.
- `stabler/tests/test_tender_sidebar_navigation.py` — sidebar role/group regression contract.
- `stabler/tests/test_tender_workspace_spa.py` — workspace and no-Desk-link contract.

### Modify

- `stabler/public/js/components/Sidebar.vue` — Tender Operations group and role-aware children.
- `stabler/public/js/stores/session.js` — cached tender views and loading action.
- `stabler/public/js/pages/tender/TenderNav.vue` — consume the shared cached views.
- `stabler/api/tender.py` — trend, portfolio progress, workspace document chain, finance exclusion.
- `stabler/public/js/pages/Dashboard.vue` — P1 Control Tower composition.
- `stabler/public/js/pages/tender/PoControlBoard.vue` — four-tab Tender Workspace shell.
- `stabler/public/js/router.js` — preserve route while updating page title.
- `stabler/tests/test_tender_dashboard.py` — response contract.
- `stabler/tests/test_tender_dashboard_behavior.py` — aggregation and permission behavior.
- `stabler/tests/test_tender_dashboard_spa.py` — P1 component and drill-down contract.
- `stabler/translations/{en,ru,uz,uzc,tr}.csv` — new UI labels.
- `stabler/tests/test_tender_dashboard_i18n.py` — required locale keys.

---

### Task 1: Restore and Upgrade Tender Sidebar Navigation

**Files:**
- Modify: `stabler/public/js/stores/session.js`
- Modify: `stabler/public/js/components/Sidebar.vue`
- Modify: `stabler/public/js/pages/tender/TenderNav.vue`
- Create: `stabler/tests/test_tender_sidebar_navigation.py`

**Interfaces:**
- Produces: `session.tenderViews: string[]`
- Produces: `session.ensureTenderViews(): Promise<string[]>`
- Consumes: `stabler.api.tender.tender_views`

- [ ] **Step 1: Write the failing sidebar contract**

```python
class TestTenderSidebarNavigation(unittest.TestCase):
	def test_tender_is_in_operations_group(self):
		self.assertIn(
			'names: ["purchasing", "imports", "tender", "inventory"',
			self.sidebar,
		)

	def test_sidebar_uses_role_filtered_tender_children(self):
		for route in (
			"/tender/director",
			"/tender/my-tenders",
			"/tender/po-control",
			"/tender/customs",
			"/tender/logistics",
		):
			self.assertIn(route, self.sidebar)
		self.assertIn("ensureTenderViews", self.sidebar)
		self.assertNotIn("/app/", self.sidebar)
```

- [ ] **Step 2: Run the test and confirm the current grouping bug**

Run:

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_sidebar_navigation -v
```

Expected: FAIL because `sections` omits `tender` and no role-aware child links exist.

- [ ] **Step 3: Cache tender views in the session store**

Add state:

```javascript
tenderViews: [],
tenderViewsLoaded: false,
```

Add action:

```javascript
async ensureTenderViews() {
	if (!this.canAccessModule("tender")) return [];
	if (this.tenderViewsLoaded) return this.tenderViews;
	const result = await call("stabler.api.tender.tender_views", {});
	this.tenderViews = Array.isArray(result?.views) ? result.views : [];
	this.tenderViewsLoaded = true;
	return this.tenderViews;
},
```

Reset `tenderViewsLoaded` on company change and visibility rehydration.

- [ ] **Step 4: Add Tender to Operations and render permitted children**

Use an explicit Tender descriptor in `Sidebar.vue`:

```javascript
const tenderChildren = computed(() => [
	{ view: "director", path: "/tender/director", label: t("Control Tower") },
	{ view: "sourcing", path: "/tender/my-tenders", label: t("My tenders") },
	{ view: "sourcing", path: "/tender/po-control", label: t("Vendor & PO") },
	{ view: "declarant", path: "/tender/customs", label: t("Customs queue") },
	{ view: "logist", path: "/tender/logistics", label: t("Logistics") },
].filter((item) => session.tenderViews.includes(item.view)));
```

Add `"tender"` under Operations between imports and inventory. Render the nested list only when Tender is active or expanded. Use buttons/RouterLinks with visible focus and `aria-expanded`.

- [ ] **Step 5: Reuse cached views in `TenderNav.vue`**

Replace the page-local API call with:

```javascript
const session = useSession();
const can = (view) => session.tenderViews.includes(view);
onMounted(() => session.ensureTenderViews());
```

- [ ] **Step 6: Run navigation regressions**

Run:

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_sidebar_navigation \
  stabler.tests.test_sidebar_profile_menu -v
node stabler/tests/tender_dashboard_company_gate.test.mjs
```

Expected: all tests PASS and the company module gate remains authoritative.

- [ ] **Step 7: Commit**

```bash
git add \
  stabler/public/js/stores/session.js \
  stabler/public/js/components/Sidebar.vue \
  stabler/public/js/pages/tender/TenderNav.vue \
  stabler/tests/test_tender_sidebar_navigation.py
git commit -m "fix(tender): expose role-aware sidebar navigation"
```

---

### Task 2: Extend the Dashboard Data Contract

**Files:**
- Modify: `stabler/api/tender.py`
- Modify: `stabler/tests/test_tender_dashboard.py`
- Modify: `stabler/tests/test_tender_dashboard_behavior.py`

**Interfaces:**
- Extends: `tender_dashboard(company, from_date, to_date)`
- Produces: `trend: Array<{month, submitted, won, won_value}>`
- Produces: `portfolio_preview: Array<TenderPortfolioRow>`
- Produces: `execution.invoice_status`

- [ ] **Step 1: Write failing behavior tests for month and progress aggregation**

Add `add_months` to the mocked `frappe.utils` surface in
`test_tender_dashboard_behavior.py`, then add tests that encode value-weighted
progress:

```python
def test_portfolio_progress_is_value_weighted(self):
	pos = [
		_Row(base_grand_total=100, per_received=100, per_billed=100),
		_Row(base_grand_total=300, per_received=0, per_billed=0),
	]
	result = tender._weighted_progress(pos, "per_received")
	self.assertEqual(result, 25.0)

def test_monthly_trend_uses_verified_server_dates(self):
	events = [
		{"submitted_at": "2026-05-08", "result": "won", "result_at": "2026-05-12", "value": 165},
		{"submitted_at": "2026-06-10", "result": "won", "result_at": "2026-06-14", "value": 213.6},
	]
	self.assertEqual(
		tender._monthly_trend(events, getdate("2026-05-01"), getdate("2026-06-30")),
		[
			{"month": "2026-05", "submitted": 1, "won": 1, "won_value": 165.0},
			{"month": "2026-06", "submitted": 1, "won": 1, "won_value": 213.6},
		],
	)
```

- [ ] **Step 2: Run targeted tests and verify failure**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_behavior \
  stabler.tests.test_tender_dashboard -v
```

Expected: FAIL because `_weighted_progress`, `_monthly_trend`, `trend`, and `portfolio_preview` do not exist.

- [ ] **Step 3: Implement pure aggregation helpers**

Add `add_months` to the existing `frappe.utils` import in `tender.py`, then add:

```python
def _weighted_progress(rows, field: str) -> float:
	total = sum(flt(row.get("base_grand_total")) for row in rows)
	if not total:
		return 0.0
	done = sum(
		flt(row.get("base_grand_total")) * flt(row.get(field)) / 100
		for row in rows
	)
	return round(done / total * 100, 1)


def _monthly_trend(events: list[dict], start, end) -> list[dict]:
	months = {}
	cursor = getdate(start).replace(day=1)
	while cursor <= end:
		key = cursor.strftime("%Y-%m")
		months[key] = {"month": key, "submitted": 0, "won": 0, "won_value": 0.0}
		cursor = add_months(cursor, 1)
	for event in events:
		submitted = str(event.get("submitted_at") or "")[:7]
		won = str(event.get("result_at") or "")[:7]
		if submitted in months:
			months[submitted]["submitted"] += 1
		if event.get("result") == "won" and won in months:
			months[won]["won"] += 1
			months[won]["won_value"] += flt(event.get("value"))
	return list(months.values())
```

- [ ] **Step 4: Build permission-filtered portfolio rows**

For each readable deal already admitted by `_tender_deal_names(company)`:

```python
procurement_total = sum(flt(row.base_grand_total) for row in deal_pos)
contract_total = sum(flt(row.base_grand_total) for row in deal_sos)

{
	"deal": deal,
	"label": _deal_label(deal),
	"lot_no": intake.get("lot_no") or "",
	"status": result,
	"risk": deadlines["risk"],
	"po_received_pct": _weighted_progress(deal_pos, "per_received"),
	"po_billed_pct": _weighted_progress(deal_pos, "per_billed"),
	"so_delivered_pct": _weighted_progress(deal_sos, "per_delivered"),
	"so_billed_pct": _weighted_progress(deal_sos, "per_billed"),
	"procurement_total": procurement_total,
	"contract_total": contract_total,
	"spread": contract_total - procurement_total,
}
```

Reuse the already company-scoped PO/SO query results; do not add one query per deal.

- [ ] **Step 5: Add invoice status counts without leaking finance rows**

Return only aggregate operational counts in `execution.invoice_status`:

```python
{
	"purchase_invoices": {"draft": 0, "submitted": 0, "unpaid": 0},
	"sales_invoices": {"draft": 0, "submitted": 0, "unpaid": 0},
}
```

Detailed amounts remain inside the role-gated `finance` section.

- [ ] **Step 6: Run backend tests**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard \
  stabler.tests.test_tender_dashboard_behavior -v
```

Expected: all tests PASS; unauthorized test users still receive no `finance` key.

- [ ] **Step 7: Commit**

```bash
git add \
  stabler/api/tender.py \
  stabler/tests/test_tender_dashboard.py \
  stabler/tests/test_tender_dashboard_behavior.py
git commit -m "feat(tender): add trend and portfolio aggregates"
```

---

### Task 3: Build the P1 Executive Control Tower

**Files:**
- Create: `stabler/public/js/pages/tender/TenderTrendChart.vue`
- Create: `stabler/public/js/pages/tender/TenderExecutionFlow.vue`
- Create: `stabler/public/js/pages/tender/TenderPortfolioPreview.vue`
- Modify: `stabler/public/js/pages/Dashboard.vue`
- Modify: `stabler/tests/test_tender_dashboard_spa.py`

**Interfaces:**
- Consumes: `tenderData.trend`
- Consumes: `tenderData.portfolio_preview`
- Consumes: existing `acquisition`, `attention`, `execution`, and permission scope
- Emits: `open-deal(deal: string, tab?: string)`

- [ ] **Step 1: Write failing SPA contract tests**

```python
def test_p1_dashboard_composes_accessible_visuals(self):
	source = _read(_DASHBOARD)
	for component in (
		"TenderTrendChart",
		"TenderExecutionFlow",
		"TenderPortfolioPreview",
	):
		self.assertIn(component, source)
	self.assertIn("portfolio_preview", source)
	self.assertIn("prefers-reduced-motion", source)
	self.assertNotIn("/app/", source)
```

Add component-specific source checks for `<svg role="img">`, `<title>`, keyboard row activation, and mobile stacking.

- [ ] **Step 2: Run the test and verify it fails**

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
```

Expected: FAIL because P1 components are absent.

- [ ] **Step 3: Implement the accessible trend chart**

`TenderTrendChart.vue` must:

```vue
<svg role="img" :aria-labelledby="titleId descriptionId" viewBox="0 0 640 220">
	<title :id="titleId">{{ t("Three-month tender conversion") }}</title>
	<desc :id="descriptionId">{{ accessibleSummary }}</desc>
	<path class="trend-area" :d="areaPath" />
	<path class="trend-line" :d="linePath" />
</svg>
<table class="visually-hidden">
	<tbody>
		<tr v-for="point in points" :key="point.month">
			<th>{{ point.month }}</th>
			<td>{{ point.submitted }}</td>
			<td>{{ point.won }}</td>
			<td>{{ point.won_value }}</td>
		</tr>
	</tbody>
</table>
```

Compute coordinates from props only. Guard empty and single-point arrays. Animate only opacity/transform and disable animation under `prefers-reduced-motion`.

- [ ] **Step 4: Implement execution flow and portfolio table**

`TenderExecutionFlow.vue` renders Won → SO → PO → PR → PI/SI → DN with labels and counts.

`TenderPortfolioPreview.vue` renders:

```vue
<tr
	v-for="row in rows"
	:key="row.deal"
	tabindex="0"
	@click="$emit('open-deal', row.deal)"
	@keydown.enter="$emit('open-deal', row.deal)"
	@keydown.space.prevent="$emit('open-deal', row.deal)"
>
```

Progress bars require `role="progressbar"`, `aria-valuenow`, and visible percentage text.

- [ ] **Step 5: Recompose `Dashboard.vue`**

Keep financial fallback unchanged when Tender is disabled. For Tender-enabled companies render:

1. route-backed filters,
2. P1 KPI strip,
3. trend + attention 8/4 grid,
4. execution flow,
5. portfolio preview,
6. permission-filtered finance summary.

Drill-down:

```javascript
function openTenderWorkspace(deal, tab = "overview") {
	router.push({
		name: "tender-po-control",
		query: { period: tenderPeriod.value, deal, tab },
	});
}
```

- [ ] **Step 6: Run frontend contract tests**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_spa \
  stabler.tests.test_tender_dashboard_i18n -v
```

Expected: PASS with no Desk link and all accessibility contracts present.

- [ ] **Step 7: Commit**

```bash
git add \
  stabler/public/js/pages/Dashboard.vue \
  stabler/public/js/pages/tender/TenderTrendChart.vue \
  stabler/public/js/pages/tender/TenderExecutionFlow.vue \
  stabler/public/js/pages/tender/TenderPortfolioPreview.vue \
  stabler/tests/test_tender_dashboard_spa.py
git commit -m "feat(tender): redesign executive control tower"
```

---

### Task 4: Convert PO Control into a Tender Workspace

**Files:**
- Modify: `stabler/api/tender.py`
- Create: `stabler/public/js/pages/tender/TenderWorkspaceTabs.vue`
- Create: `stabler/public/js/pages/tender/TenderDocumentChain.vue`
- Modify: `stabler/public/js/pages/tender/PoControlBoard.vue`
- Modify: `stabler/public/js/router.js`
- Create: `stabler/tests/test_tender_workspace_spa.py`
- Modify: `stabler/tests/test_tender_dashboard_behavior.py`

**Interfaces:**
- Produces: `tender_workspace(deal: str) -> dict`
- Consumes: query `deal` and `tab`
- Preserves: route name `tender-po-control`

- [ ] **Step 1: Write failing backend permission and chain tests**

```python
def test_workspace_omits_finance_for_non_finance_role(self):
	result = tender.tender_workspace("DEAL-1")
	self.assertNotIn("finance", result)
	self.assertIn("purchase_execution", result)
	self.assertIn("sales_execution", result)

def test_workspace_traces_invoices_through_order_item_links(self):
	result = tender.tender_workspace("DEAL-1")
	self.assertEqual(result["purchase_execution"]["invoices"][0]["purchase_order"], "PO-1")
	self.assertEqual(result["sales_execution"]["invoices"][0]["sales_order"], "SO-1")
```

- [ ] **Step 2: Run targeted tests and verify failure**

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_behavior -v
```

Expected: FAIL because `tender_workspace` does not exist.

- [ ] **Step 3: Implement the workspace endpoint**

Reuse `stabler.api.purchasing.tender_quotations` through a function-local import
to avoid introducing a module-level cycle. Add these concrete helper contracts:

```python
def _purchase_document_chain(deal: str, company: str) -> dict:
	"""Return company-scoped PO, Purchase Receipt, and Purchase Invoice rows."""
	# Resolve PO names by custom_tender_deal, then resolve PR/PI rows through
	# their item-table purchase_order links. Return:
	# {"orders": [...], "receipts": [...], "invoices": [...]}


def _sales_document_chain(deal: str, company: str) -> dict:
	"""Return company-scoped SO, Delivery Note, and Sales Invoice rows."""
	# Resolve SO names by custom_tender_deal, then resolve DN/SI rows through
	# their item-table sales_order links. Return:
	# {"orders": [...], "deliveries": [...], "invoices": [...]}


def _tender_finance_chain(purchase: dict, sales: dict) -> dict:
	"""Derive AP, AR, paid, outstanding, and actual margin from permitted rows."""
	return {
		"ap_total": sum(flt(row.get("grand_total")) for row in purchase["invoices"]),
		"ap_outstanding": sum(flt(row.get("outstanding_amount")) for row in purchase["invoices"]),
		"ar_total": sum(flt(row.get("grand_total")) for row in sales["invoices"]),
		"ar_outstanding": sum(flt(row.get("outstanding_amount")) for row in sales["invoices"]),
	}
```

The two document-chain helpers must use one parent query and one child-table
query per document type, never one query per document. Normalize every returned
row to the fields consumed by `TenderDocumentChain.vue`: `name`, `posting_date`,
`status`, `grand_total`, `outstanding_amount`, and the linked `purchase_order`
or `sales_order`.

Then add the endpoint:

```python
@frappe.whitelist()
def tender_workspace(deal: str) -> dict:
	from stabler.api.purchasing import tender_quotations

	company = _deal_scope(deal, write=False)
	out = {
		"deal": deal,
		"company": company,
		"overview": deal_intake(deal),
		"sourcing": tender_quotations(deal),
		"purchase_execution": _purchase_document_chain(deal, company),
		"sales_execution": _sales_document_chain(deal, company),
	}
	if _can_view_tender_finance():
		out["finance"] = _tender_finance_chain(
			out["purchase_execution"],
			out["sales_execution"],
		)
	return out
```

Every document list uses `frappe.get_list`, company filters where the DocType owns company, `docstatus < 2`, and `frappe.has_permission` before returning rows.

- [ ] **Step 4: Write the failing workspace SPA contract**

```python
def test_workspace_has_query_backed_tabs(self):
	for tab in ("overview", "vendor-po", "delivery", "finance"):
		self.assertIn(tab, self.workspace)
	self.assertIn("route.query.tab", self.workspace)
	self.assertIn("router.replace", self.workspace)
	self.assertNotIn("/app/", self.workspace)
```

- [ ] **Step 5: Implement tab routing**

`TenderWorkspaceTabs.vue` accepts `active`, `views`, and `hasFinance`.

```javascript
const activeTab = computed(() => {
	const requested = String(route.query.tab || "overview");
	return allowedTabs.value.includes(requested) ? requested : "overview";
});

function selectTab(tab) {
	router.replace({ query: { ...route.query, tab } });
}
```

Hide Finance when the endpoint omits `finance`.

- [ ] **Step 6: Recompose `PoControlBoard.vue`**

- Overview: existing `TenderIntake` and `BidPricing`.
- Vendor & PO: Supplier Quotations, policy badges, existing PO lanes, landed-cost editor, selected vendor.
- Delivery: `TenderDocumentChain` with PO → PR → PI and SO → DN → SI.
- Finance: AP/AR/outstanding and planned/actual margin when authorized.

Keep `openPo(name)` routed to `/purchasing/orders/:name`. All invoice and delivery drill-downs must use existing Stabler routes or stay non-clickable until a Stabler route exists.

- [ ] **Step 7: Run workspace regressions**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_workspace_spa \
  stabler.tests.test_tender_dashboard_behavior -v
```

Expected: PASS; finance remains absent for unauthorized roles.

- [ ] **Step 8: Commit**

```bash
git add \
  stabler/api/tender.py \
  stabler/public/js/pages/tender/TenderWorkspaceTabs.vue \
  stabler/public/js/pages/tender/TenderDocumentChain.vue \
  stabler/public/js/pages/tender/PoControlBoard.vue \
  stabler/public/js/router.js \
  stabler/tests/test_tender_workspace_spa.py \
  stabler/tests/test_tender_dashboard_behavior.py
git commit -m "feat(tender): add tender execution workspace"
```

---

### Task 5: Translate, Validate, and Perform Live Acceptance

**Files:**
- Modify: `stabler/translations/en.csv`
- Modify: `stabler/translations/ru.csv`
- Modify: `stabler/translations/uz.csv`
- Modify: `stabler/translations/uzc.csv`
- Modify: `stabler/translations/tr.csv`
- Modify: `stabler/tests/test_tender_dashboard_i18n.py`

**Interfaces:**
- Consumes: all new `t("...")` source strings from Tasks 1–4.
- Produces: locale-complete production UI.

- [ ] **Step 1: Add failing locale-key assertions**

```python
REQUIRED_KEYS = (
	"Control Tower",
	"Vendor & PO",
	"Three-month tender conversion",
	"Portfolio value",
	"Weighted margin",
	"Execution flow",
	"Purchase invoices",
	"Sales invoices",
	"Selected vendor",
)
```

Assert every key exists in `en`, `ru`, `uz`, `uzc`, and `tr`.

- [ ] **Step 2: Run the locale test and verify failure**

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_i18n -v
```

Expected: FAIL listing the new untranslated keys.

- [ ] **Step 3: Add translations**

Append the same source keys to all five CSV files. Preserve CSV quoting and UTF-8. Use Uzbek Latin as the reference copy, then provide Uzbek Cyrillic, Russian, Turkish, and English values.

- [ ] **Step 4: Run the complete focused suite**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard \
  stabler.tests.test_tender_dashboard_behavior \
  stabler.tests.test_tender_dashboard_spa \
  stabler.tests.test_tender_sidebar_navigation \
  stabler.tests.test_tender_workspace_spa \
  stabler.tests.test_tender_dashboard_i18n \
  stabler.tests.test_sidebar_profile_menu -v
node stabler/tests/tender_dashboard_company_gate.test.mjs
node stabler/tests/tender_board_filters.test.mjs
```

Expected: zero failures and zero skipped tests.

- [ ] **Step 5: Build and migrate the production candidate**

Use the project deployment runbook. Required operations:

```bash
bench build --app stabler
bench --site mikas.erpstable.com migrate
bench --site mikas.erpstable.com clear-cache
```

Expected: commands exit `0`; migration does not create tenant-specific schema.

- [ ] **Step 6: Run live `[TEST-E2E]` acceptance**

As `zvictory2001@gmail.com`:

1. Sidebar shows Tender and only role-permitted children.
2. May 2026 shows completed PO/SO.
3. June 2026 shows PO 60% and SO 40%.
4. July 2026 shows open PO/SO and draft PI/SI.
5. June Vendor & PO shows five quotations and Gulf Source FZE selected.
6. Finance content is visible only for a finance-authorized role.
7. Browser viewport checks pass at 1440 px, 1024 px, and mobile width.
8. No link targets `/app/...`.

- [ ] **Step 7: Commit translations and acceptance contracts**

```bash
git add \
  stabler/translations/en.csv \
  stabler/translations/ru.csv \
  stabler/translations/uz.csv \
  stabler/translations/uzc.csv \
  stabler/translations/tr.csv \
  stabler/tests/test_tender_dashboard_i18n.py
git commit -m "test(tender): complete control tower acceptance"
```

---

## Final Verification Gate

- [ ] Run `git diff --check`.
- [ ] Confirm no focused test is skipped.
- [ ] Confirm `git status --short` contains no task-owned unstaged files.
- [ ] Re-run exact user-context dashboard and workspace API smoke tests.
- [ ] Verify GL and stock test data remain unchanged by read-only dashboard use.
- [ ] Record production bundle hash and deployment timestamp.
