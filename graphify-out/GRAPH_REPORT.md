# Stabler Knowledge Graph — Report
Generated: 2026-06-01

## Summary

| Metric | Value |
|--------|-------|
| Total nodes | 1,190 |
| Total edges | 2,481 |
| Hyperedges | 59 |
| Communities (Louvain) | 142 |
| AST (structural) extraction | 1,674 raw nodes, 2,438 raw edges |
| Semantic chunks | 15 (245 files) |
| Deduplication | 782 nodes collapsed (706 exact, 76 fuzzy) |

---

## God Nodes — highest-degree hubs

These nodes connect the most other nodes. They are the architectural
load-bearers — touching them affects everything.

| Degree | Node ID | What it is |
|--------|---------|------------|
| 66 | `api_common_require_company` | `_require_company()` — mandatory entry gate on every API endpoint; guarantees company scoping |
| 47 | `api_sfa_company_filter` | `_company_filter()` — SFA multi-tenant WHERE clause; imported by sfa + marketing + marketing_equipment |
| 43 | `route_route_doctype` | Route doctype definition (JSON schema field cluster) |
| 38 | `component_emptystate` | `EmptyState.vue` — used as zero-state placeholder on every list page |
| 27 | `route_route_actions` | Route doctype action nodes |
| 27 | `route_route_creation` | Route doctype field cluster |

> **Implication:** Any change to `_require_company` in `stabler/api/_common.py`
> propagates to all 9 modules simultaneously. Always test across modules when
> touching this function.

---

## Top Communities

| ID | Nodes | Cohesion | Label |
|----|-------|----------|-------|
| 0 | 76 | 0.05 | Admin |
| 1 | 68 | 0.24 | Trade Marketing |
| 2 | 66 | 0.08 | Money / Accounting |
| 3 | 63 | 0.05 | Sales Module |
| 4 | 57 | 0.06 | Money / Accounting |
| 5 | 48 | 0.06 | Money / Accounting |
| 6 | 44 | 0.09 | Purchasing Module |
| 7 | 43 | 0.08 | Purchasing Module |
| 8 | 43 | 0.06 | EHF E-Invoice |
| 9 | 42 | 0.07 | Sales Module |
| 10 | 38 | 0.05 | Sales Module |
| 11 | 36 | 0.10 | Sales Module |
| 12 | 33 | 0.09 | Inventory |
| 13 | 33 | 0.09 | Money / Accounting |
| 14 | 32 | 0.09 | Money / Accounting |

Trade Marketing (community 1) has the **highest cohesion (0.24)** — tightly
coupled internal graph. Money/Accounting splits across 5 communities — expected
given the distinct sub-pages (accounts, journals, payments, expenses, transfers).

---

## Surprising Connections (cross-community edges)

These edges cross community boundaries — unexpected linkages that reveal
architectural coupling worth being aware of.

1. **ARCA webhook ↔ EHF Submission** (`semantically_similar_to`):  
   `handle_payment_webhook()` and the EHF Submission doctype are structurally
   unrelated but both handle Uzbekistan compliance event lifecycles.
   They should share error-handling and retry patterns.

2. **`execute()` (cbu_rate_refresh) shares_data_with ERPNext Currency Exchange**:  
   The scheduled CBU task writes directly into ERPNext's `Currency Exchange`
   doctype — not a Stabler doctype. Any ERPNext upgrade changing that schema
   will silently break the exchange rate refresh.

3. **`formatMoney()` ↔ MoneyInput component** (`semantically_similar_to`):  
   `money.js:formatMoney` and `MoneyInput.vue` solve the same problem at
   different layers. The graph correctly surfaces they must stay in sync.

4. **Patch v04 (uzs_default_currency) ↔ CBU Exchange Rates page**:  
   The migration that established UZS as default and the UI that displays
   live CBU rates are architecturally linked through the same business
   requirement. Changes to currency handling need both.

5. **`fetch_and_store()` calls `refresh_cbu_rates()`**:  
   AST-confirmed direct call chain in the scheduled task — not surprising,
   but confirms the CBU task is the only writer to exchange rate records.

---

## Key Architectural Patterns (from semantic extraction)

### Core UI Conventions Hyperedge
Five nodes form the mandatory convention set every page component must use:
- `MoneyInput.vue` — all monetary fields (rates, amounts, balances)
- `DateInput.vue` — all date inputs (dd.mm.yyyy display, ISO v-model)
- `composables/date.js:formatDate` — all date display in tables
- `composables/i18n.js:t()` — all user-facing strings (en/ru/uz/uzc)
- `stores/session.js:canAccessModule` — module visibility gate

### Module Access Control Hyperedge
Three doctypes implement per-user/per-company module gating:
- `StablerCompanyModules` — which modules are enabled per company
- `StablerUserCompany` — which companies a user can access
- `StablerUserModule` — per-user module override (additive/restrictive)

### SFA Transaction Flow
`Route → RouteOutlet → Outlet → Visit → VisitStep`  
Each visit is a structured workflow: GREET / MERCHANDISING / ORDER / PHOTO / PAYMENT / SURVEY / FAREWELL.

### SO↔PO Mirror
`SalesOrders.vue` and `PurchaseOrders.vue` are structural twins:
- Same `?open=<name>` deep-link pattern
- Same submit/cancel/amend/create-invoice action flow
- `purchasing.supplier_ledger` internally calls `sales._fetch_party_ledger_rows` (AP reuses AR code)
- `purchasing` cross-calls `sales.list_price_lists` and `sales.list_currencies` for buying-side lookups

### Uzbekistan Compliance Cluster
Four compliance pages form a coherent group (Admin → Compliance tab):
ARCA + AslBelgisi + EHFStatus + OneCSyncLog — all Uzbek regulatory requirements.

### EHF Pipeline (hyperedge)
`build_payload → sign (EIMZO) → client → submit` — sequential e-invoice flow.
Sales Invoice `on_submit` triggers this via `frappe.enqueue`.

---

## Known Issues Flagged by Graph

### MoneyInput Violation
- **`Outlets.vue:305-311`** uses `<input type="number">` for `credit_limit` field.
  This violates the MoneyInput rule. Should be `<MoneyInput v-model="form.credit_limit" />`.

### Ambiguous Nodes
- `api_organization_MODULE_KEYS` node is missing `source_file` — extraction
  warning during build. Low severity.

---

## Suggested Queries

Use `graphify query "<question>"` against this graph:

1. *"What endpoint does PurchaseOrders.vue call to amend a PO?"*
2. *"Which pages use MoneyInput?"*
3. *"What happens when a Sales Invoice is submitted?"*
4. *"How does module access gating work end-to-end?"*
5. *"Which SFA pages call the same API endpoint?"*
6. *"What is the relationship between Route, Outlet, and Visit?"*
7. *"How does Stabler block access to the Frappe Desk?"*

---

## Files

| File | Description |
|------|-------------|
| `graphify-out/graph.json` | Machine-readable graph (NetworkX node_link format + hyperedges) |
| `graphify-out/graph.html` | Interactive visual explorer |
| `graphify-out/GRAPH_REPORT.md` | This file |
| `graphify-out/.graphify_python` | Interpreter path for future runs |
| `graphify-out/.graphify_root` | Scan root for `--update` runs |
| `graphify-out/.graphify_detect.json` | Corpus detection result |
| `graphify-out/.graphify_ast.json` | AST structural extraction |
| `graphify-out/.graphify_chunk_NN.json` | Semantic extraction per chunk |

## Updating

```bash
# Re-extract only changed files (no LLM cost for code-only changes):
cd /Users/zafar/frappe-bench-local/apps/stabler
$(cat graphify-out/.graphify_python) -m graphify stabler/ --update
```

Or trigger via the post-commit hook (installed automatically).
