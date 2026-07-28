# Executive Tender Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Director overview into `/dashboard` as a six-KPI executive ribbon plus a conversion-only sales funnel, with no Tender table below it.

**Architecture:** Reuse the Director portfolio calculations through a private backend helper that can omit row serialization, and attach the resulting KPI object to the existing `tender_dashboard` response only for users who already have the Director view. Render the six KPIs in a focused Vue component and add a conversion-only mode to the existing funnel. Preserve non-Tender Dashboard branches and redirect the legacy Director route to `/dashboard`.

**Tech Stack:** Python/Frappe APIs, Vue 3 Composition API, Vue Router 4, Tabler CSS, existing money/i18n composables, Python `unittest`, Vitest, ESLint.

## Global Constraints

- Never link or redirect to Frappe Desk (`/app/...` or `/desk/...`).
- The Tender Dashboard contains no table, attention list, acquisition trend, execution panel, or portfolio preview.
- Existing financial and Imports Dashboard branches remain behaviorally unchanged.
- Director monetary KPIs remain behind the existing Director-view permission gate.
- Monetary values use shared money formatting and monospaced/tabular figures.
- New copy must be translated in `en`, `ru`, `uz`, `uzc`, and `tr`.
- Do not add `table-striped`; global table striping already applies.
- Use npm, ESLint, Prettier, and existing project test commands.

## File map

- `stabler/api/tender.py` — extract row-optional Director aggregation and expose its KPI result through `tender_dashboard`.
- `stabler/tests/test_tender_dashboard_behavior.py` — protect KPI parity, permission gating, and row-free aggregate payload.
- `stabler/public/js/pages/tender/TenderExecutiveKpis.vue` — render the six executive indicators.
- `stabler/public/js/pages/tender/TenderFunnel.vue` — support full and conversion-only presentations.
- `stabler/public/js/pages/Dashboard.vue` — compose the approved Executive ribbon layout.
- `stabler/public/js/pages/tender/TenderNav.vue` — compact Overview-first navigation.
- `stabler/public/js/router.js` — redirect the legacy Director route.
- `stabler/tests/test_tender_dashboard_spa.py` — static composition and no-table contract.
- `stabler/tests/test_tender_sidebar_navigation.py` — legacy-route and navigation contract.
- `stabler/tests/test_tender_dashboard_i18n.py` and translation CSVs — translated Dashboard copy.

---

### Task 1: Add a row-free executive KPI aggregate

**Files:**
- Modify: `stabler/api/tender.py:1844-1921`
- Modify: `stabler/api/tender.py:2375-2645`
- Test: `stabler/tests/test_tender_dashboard_behavior.py`

**Interfaces:**
- Produces: `_tender_director_payload(company: str, *, include_rows: bool) -> dict`
- Produces: `_dashboard_executive_payload(company: str, views: set[str]) -> dict`
- Produces in `tender_dashboard`: `executive_kpi: dict | None` and `executive_currency: str`
- Preserves: `tender_director_board(company)` response keys `currency`, `rows`, and `kpi`

- [ ] **Step 1: Write failing backend tests**

Add tests that prove the helper preserves Director totals while omitting rows and
that non-Director callers never receive executive monetary data:

```python
def test_director_payload_can_omit_rows_without_changing_kpis(self):
	payload_with_rows = tender._tender_director_payload("Test Company", include_rows=True)
	payload_without_rows = tender._tender_director_payload("Test Company", include_rows=False)

	self.assertEqual(payload_without_rows["kpi"], payload_with_rows["kpi"])
	self.assertEqual(payload_without_rows["currency"], payload_with_rows["currency"])
	self.assertNotIn("rows", payload_without_rows)


def test_dashboard_exposes_executive_kpis_only_to_director_view(self):
	with patch.object(
		tender,
		"_tender_director_payload",
		return_value={
			"currency": "UZS",
			"kpi": {"count": 35, "total_value": 3041273130},
		},
	) as director_payload:
		payload = tender._dashboard_executive_payload("Test Company", {"director"})

	self.assertEqual(payload["executive_kpi"]["count"], 35)
	self.assertEqual(payload["executive_currency"], "UZS")
	director_payload.assert_called_once_with("Test Company", include_rows=False)


def test_dashboard_hides_executive_kpis_without_director_view(self):
	with patch.object(tender, "_tender_director_payload") as director_payload:
		payload = tender._dashboard_executive_payload("Test Company", {"sourcing"})

	self.assertIsNone(payload["executive_kpi"])
	self.assertEqual(payload["executive_currency"], "")
	director_payload.assert_not_called()
```

Reuse the existing `_FakeDB`, permission patches, and dashboard fixtures in the
test class rather than creating a second Frappe stub.

- [ ] **Step 2: Run the focused backend tests and confirm RED**

Run:

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_behavior.TestTenderDashboardBehaviour.test_director_payload_can_omit_rows_without_changing_kpis \
  stabler.tests.test_tender_dashboard_behavior.TestTenderDashboardBehaviour.test_dashboard_exposes_executive_kpis_only_to_director_view \
  stabler.tests.test_tender_dashboard_behavior.TestTenderDashboardBehaviour.test_dashboard_hides_executive_kpis_without_director_view -v
```

Expected: failures because `_tender_director_payload` and the new response keys
do not exist.

- [ ] **Step 3: Extract the Director calculation**

Move the body currently inside `tender_director_board` into:

```python
def _tender_director_payload(company: str, *, include_rows: bool) -> dict:
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	rows = []
	visible_count = 0
	total_value = 0.0
	total_ost = 0.0
	at_risk = 0
	margins = []
	won = lost = pending = 0
	unverified_history = 0

	for deal in _tender_deal_names(company):
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		visible_count += 1

	kpi = {
		"count": visible_count,
		"total_value": total_value,
		"avg_margin": round(sum(margins) / len(margins), 1) if margins else 0,
		"at_risk": at_risk,
		"total_ostatok": total_ost,
		"won": won,
		"lost": lost,
		"pending": pending,
		"unverified_history": unverified_history,
		"win_rate": round(won / (won + lost) * 100, 1) if (won + lost) else 0,
	}
	payload = {"currency": base_ccy, "kpi": kpi}
	if include_rows:
		rows.sort(key=lambda row: (_RISK_ORDER.get(row["risk"], 3), row["delivery"] or "9999-99-99"))
		payload["rows"] = rows
	return payload
```

Move the existing statements from `_read_intake(deal)` through the total and
result counters into the loop immediately after `visible_count += 1` without
changing their expressions. Wrap only the existing `rows.append({...})` block
in `if include_rows:`; deadline and P&L calculations remain outside that branch
because the KPI totals consume them.

Keep the public endpoint as:

```python
@frappe.whitelist()
def tender_director_board(company: str) -> dict:
	"""Director portfolio: every tender with value, margin, Остаток, deadline risk."""
	_require_tender_view("director", company)
	return _tender_director_payload(company, include_rows=True)
```

- [ ] **Step 4: Attach KPIs to the existing Dashboard response**

Add this permission-preserving adapter beside the Director helper:

```python
def _dashboard_executive_payload(company: str, views: set[str]) -> dict:
	if "director" not in views:
		return {"executive_kpi": None, "executive_currency": ""}
	executive = _tender_director_payload(company, include_rows=False)
	return {
		"executive_kpi": executive["kpi"],
		"executive_currency": executive["currency"],
	}
```

Immediately after the existing `out` dictionary is constructed and before the
finance block, add:

```python
out.update(_dashboard_executive_payload(company, views))
if out["executive_kpi"] is not None:
	period_decisions = acquisition["won"] + acquisition["lost"]
	out["executive_kpi"]["win_rate"] = (
		round(acquisition["won"] / period_decisions * 100, 1)
		if period_decisions
		else 0
	)
```

Do not add a `rows` or `portfolio_preview` alias to `executive_kpi`.

- [ ] **Step 5: Run focused and surrounding backend tests**

Run:

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_behavior \
  stabler.tests.test_tender_dashboard -v
```

Expected: all tests pass with no skips.

- [ ] **Step 6: Commit the backend aggregate**

```bash
git add stabler/api/tender.py stabler/tests/test_tender_dashboard_behavior.py
git commit -m "feat: expose director KPIs on tender dashboard"
```

---

### Task 2: Isolate the KPI ribbon and conversion-only funnel mode

**Files:**
- Create: `stabler/public/js/pages/tender/TenderExecutiveKpis.vue`
- Modify: `stabler/public/js/pages/tender/TenderFunnel.vue`
- Test: `stabler/tests/test_tender_dashboard_spa.py`

**Interfaces:**
- `TenderExecutiveKpis` consumes props `kpi`, `currency`, and `language`
- `TenderFunnel` consumes props `mode` and `days`
- `TenderFunnel` default remains `"full"` for compatibility

- [ ] **Step 1: Replace obsolete composition assertions with failing executive assertions**

Update `test_p1_dashboard_composes_accessible_visuals` so it reads both new
component contracts:

```python
def test_dashboard_composes_executive_kpis_and_conversion_only_funnel(self):
	dashboard = _read(_DASHBOARD)
	kpis = _read(_EXECUTIVE_KPIS)
	funnel = _read(_FUNNEL)

	self.assertIn("TenderExecutiveKpis", dashboard)
	self.assertIn('mode="conversion"', dashboard)
	self.assertNotIn("TenderPortfolioPreview", dashboard)
	self.assertNotIn("TenderExecutionFlow", dashboard)
	self.assertNotIn("TenderTrendChart", dashboard)
	for label in (
		"Active tenders",
		"Portfolio value",
		"Avg margin",
		"At risk",
		"Win rate",
		"Net remaining",
	):
		self.assertIn(f't(\"{label}\")', kpis)
	self.assertIn('mode: { type: String, default: "full" }', funnel)
	self.assertIn('days: { type: Number, default: 90 }', funnel)
	self.assertIn('v-if="props.mode === \\'full\\'"', funnel)
```

Add `_EXECUTIVE_KPIS` and `_FUNNEL` path constants at the top of the test.

- [ ] **Step 2: Run the SPA contract test and confirm RED**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_spa.TestTenderDashboardSpaContract.test_dashboard_composes_executive_kpis_and_conversion_only_funnel -v
```

Expected: failure because the KPI component and funnel mode do not exist.

- [ ] **Step 3: Create `TenderExecutiveKpis.vue`**

Use this component boundary:

```vue
<script setup>
import { computed } from "vue";
import { formatMoney, formatCompactMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	kpi: { type: Object, default: () => ({}) },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
});

const items = computed(() => [
	{ key: "count", label: t("Active tenders"), value: props.kpi.count || 0, tone: "" },
	{ key: "value", label: t("Portfolio value"), value: formatCompactMoney(props.kpi.total_value || 0, props.currency, props.language), exact: formatMoney(props.kpi.total_value || 0, props.currency, props.language), tone: "" },
	{ key: "margin", label: t("Avg margin"), value: `${props.kpi.avg_margin || 0}%`, tone: "text-green" },
	{ key: "risk", label: t("At risk"), value: props.kpi.at_risk || 0, tone: props.kpi.at_risk ? "text-red" : "" },
	{ key: "win", label: t("Win rate"), value: `${props.kpi.win_rate || 0}%`, tone: "text-green" },
	{ key: "remaining", label: t("Net remaining"), value: formatCompactMoney(props.kpi.total_ostatok || 0, props.currency, props.language), exact: formatMoney(props.kpi.total_ostatok || 0, props.currency, props.language), tone: "" },
]);
</script>
```

Render a semantic list with six responsive cards. Each numeric value uses
`font-monospace`; compact money values use `:title="item.exact"` and an
`aria-label` containing the exact amount. Use component-scoped responsive CSS
for 6/3/2 columns and a visible `:focus-visible` style only if cards are
interactive.

- [ ] **Step 4: Add conversion-only mode to `TenderFunnel.vue`**

Add:

```javascript
const props = defineProps({
	mode: { type: String, default: "full" },
	days: { type: Number, default: 90 },
});
```

Insert `<template v-if="props.mode === 'full'">` immediately before the current
`<!-- KPI cards -->` comment and close that template immediately after the
horizontal pipeline card, before the conversion funnel card. Do not change the
markup inside the moved boundary.

Keep the existing conversion funnel card outside that template. Do not duplicate
its SVG, legend, stage navigation, loading, or error behavior. Pass
`days: props.days` to `stabler.api.tender.tender_funnel`, and replace the current
company-only watcher with:

```javascript
watch([activeCompany, () => props.days], load);
```

- [ ] **Step 5: Run the focused SPA contract**

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
```

Expected: all updated contracts pass.

- [ ] **Step 6: Commit the presentation components**

```bash
git add \
  stabler/public/js/pages/tender/TenderExecutiveKpis.vue \
  stabler/public/js/pages/tender/TenderFunnel.vue \
  stabler/tests/test_tender_dashboard_spa.py
git commit -m "feat: add executive KPI ribbon and sales funnel mode"
```

---

### Task 3: Replace the Tender Dashboard branch with Executive ribbon

**Files:**
- Modify: `stabler/public/js/pages/Dashboard.vue`
- Test: `stabler/tests/test_tender_dashboard_spa.py`
- Test: `stabler/tests/test_tender_dashboard_i18n.py`

**Interfaces:**
- Consumes: `tenderData.executive_kpi`, `tenderData.executive_currency`
- Consumes: `<TenderExecutiveKpis :kpi :currency :language />`
- Consumes: `<TenderFunnel mode="conversion" :days="tenderDays" />`

- [ ] **Step 1: Write the failing no-table and compact-header contract**

Add or replace assertions with:

```python
def test_tender_dashboard_is_executive_ribbon_without_tables(self):
	source = _read(_DASHBOARD)

	self.assertIn("tenderData.value.executive_kpi", source)
	self.assertIn("<TenderExecutiveKpis", source)
	self.assertIn('<TenderFunnel mode="conversion"', source)
	self.assertIn(':days="tenderDays"', source)
	self.assertIn('t(\"Tender operations\")', source)
	self.assertIn('t(\"Dashboard\")', source)
	for removed in (
		"TenderTrendChart",
		"TenderExecutionFlow",
		"TenderPortfolioPreview",
		"portfolio_preview",
		"attention.value",
	):
		self.assertNotIn(removed, source)
```

Retain the existing tests that prove Imports and financial fallback branches
still exist.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_spa.TestTenderDashboardSpaContract.test_tender_dashboard_is_executive_ribbon_without_tables -v
```

Expected: failure on the old Tender components and markup.

- [ ] **Step 3: Simplify the Tender state and imports**

In `Dashboard.vue`:

- remove `TenderTrendChart`, `TenderExecutionFlow`, and
  `TenderPortfolioPreview` imports;
- import `TenderExecutiveKpis`, `TenderFunnel`, and `TenderNav`;
- remove Tender-only computed values for acquisition, execution, attention,
  my-work, trend, and portfolio rows when no longer used;
- retain financial/imports state and functions untouched;
- add:

```javascript
const executiveKpi = computed(() => tenderData.value.executive_kpi || null);
const executiveCurrency = computed(() => tenderData.value.executive_currency || currency.value || "");
const tenderDays = ref(Number(route.query.days) || 90);
```

Do not change the `tenderEnabled` capability gate or `loadFinancial()` fallback.
Replace the Tender request's month range with dates calculated from
`tenderDays`; keep its existing three-month trend range only while that trend is
still consumed by a non-Tender branch.

- [ ] **Step 4: Render the approved layout**

For `tenderEnabled`, render:

```vue
<div class="tender-dashboard">
	<TenderNav overview />
	<TenderExecutiveKpis
		v-if="executiveKpi"
		:kpi="executiveKpi"
		:currency="executiveCurrency"
		:language="user.language"
	/>
	<TenderFunnel mode="conversion" :days="tenderDays" />
</div>
```

Keep the existing empty, loading, error, Retry, and no-company states. Replace
the Tender month input with a 30/90/180-day selector bound to `tenderDays`.
Changing it updates `route.query.days`, calls `loadTender()`, and causes
`TenderFunnel` to reload through its prop watcher. Label the five snapshot KPIs
`Current portfolio`; label win rate and the funnel with the selected day count.

- [ ] **Step 5: Run Dashboard and translation contracts**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard_spa \
  stabler.tests.test_tender_dashboard_i18n -v
```

Expected: all tests pass; translation test may identify exact new keys for the
next task.

- [ ] **Step 6: Commit the Dashboard composition**

```bash
git add \
  stabler/public/js/pages/Dashboard.vue \
  stabler/tests/test_tender_dashboard_spa.py
git commit -m "feat: consolidate director overview into dashboard"
```

---

### Task 4: Trim navigation, preserve bookmarks, and translate copy

**Files:**
- Modify: `stabler/public/js/pages/tender/TenderNav.vue`
- Modify: `stabler/public/js/router.js`
- Modify: `stabler/tests/test_tender_sidebar_navigation.py`
- Modify: `stabler/tests/test_tender_dashboard_i18n.py`
- Modify: `stabler/translations/en.csv`
- Modify: `stabler/translations/ru.csv`
- Modify: `stabler/translations/uz.csv`
- Modify: `stabler/translations/uzc.csv`
- Modify: `stabler/translations/tr.csv`

**Interfaces:**
- Produces: `/tender/director` compatibility redirect to `/dashboard`
- Produces: Overview-first Tender sub-navigation

- [ ] **Step 1: Write failing navigation tests**

Add:

```python
def test_tender_director_bookmark_redirects_to_dashboard(self):
	with open(_ROUTER, encoding="utf-8") as source:
		router = source.read()
	self.assertIn(
		'{ path: "/tender/director", redirect: "/dashboard"',
		router,
	)
	self.assertNotIn(
		'{ path: "/tender/director", name: "tender-director", component: DirectorBoard',
		router,
	)


def test_tender_subnav_is_overview_first_without_director_button(self):
	with open(_TENDER_NAV, encoding="utf-8") as source:
		nav = source.read()
	self.assertIn('to="/dashboard"', nav)
	self.assertIn('t("Overview")', nav)
	self.assertNotIn('t("Director board")', nav)
	self.assertNotIn('to="/tender/director"', nav)
```

Declare `_ROUTER` and `_TENDER_NAV` beside the existing `_SIDEBAR` constant.

- [ ] **Step 2: Run the navigation test and confirm RED**

```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_sidebar_navigation -v
```

Expected: failures because the Director route and link still exist.

- [ ] **Step 3: Implement redirect and compact nav**

Remove the unused `DirectorBoard` import from `router.js` and replace its route
with:

```javascript
{ path: "/tender/director", redirect: "/dashboard", meta: { module: "tender" } },
```

In `TenderNav.vue`, replace the Director button with:

```vue
<router-link to="/dashboard" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
	<i class="ti ti-layout-dashboard me-1"></i>{{ t("Overview") }}
</router-link>
```

Retain role gating on My tenders, PO control, Customs, and Logistics. Rename
`Contract board` to `Contracts` only if every locale receives the new key in the
same change.

- [ ] **Step 4: Add exact translations**

Add non-empty rows for all new literal `t()` keys identified by
`test_tender_dashboard_i18n.py`, including:

```text
Overview
Current portfolio
Last 90 days
Active tenders
Portfolio value
Avg margin
At risk
Win rate
Net remaining
Sales funnel
```

Use natural locale-specific copy; do not copy English into `ru`, `uz`, `uzc`, or
`tr`.

- [ ] **Step 5: Run focused and full verification**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_sidebar_navigation \
  stabler.tests.test_tender_dashboard_spa \
  stabler.tests.test_tender_dashboard_i18n \
  stabler.tests.test_tender_dashboard_behavior \
  stabler.tests.test_tender_dashboard -v
npm run test:js
npm run lint:js
bench build --app stabler
```

Expected: every command exits `0`; no tests are skipped.

- [ ] **Step 6: Commit navigation and translations**

```bash
git add \
  stabler/public/js/pages/tender/TenderNav.vue \
  stabler/public/js/router.js \
  stabler/tests/test_tender_sidebar_navigation.py \
  stabler/tests/test_tender_dashboard_i18n.py \
  stabler/translations/en.csv \
  stabler/translations/ru.csv \
  stabler/translations/uz.csv \
  stabler/translations/uzc.csv \
  stabler/translations/tr.csv
git commit -m "feat: make dashboard the tender executive overview"
```
