# Stabler SPA — Codebase Brief (context for LLM prompting)

> Paste this whole file at the top of a ChatGPT/Claude conversation when you want help
> with Stabler. It tells the model exactly what the app is, how it's built, and the
> non-negotiable rules, so its answers fit the real codebase instead of generic Frappe/Vue advice.

---

## 1. What Stabler is

Stabler is a **self-contained Vue 3 single-page application** that runs on top of
**ERPNext / Frappe** as a custom Frappe app (`apps/stabler`). It replaces the Frappe Desk UI
with a purpose-built business interface for **non-accountant SMB operators in Uzbekistan**.

- One codebase, multiple tenants (separate ERPNext sites): e.g. `anjan.erpstable.com`
  (distribution, company "ANJAN"), `horeca.erpstable.com` (HoReCa equipment service,
  company "HorecaGroup"). Each tenant enables only the modules it needs.
- 5 languages: **en, ru, uz (Latin), uzc (Cyrillic), tr**.
- The SPA is the entire UX. **It must never link out to the Frappe Desk (`/app/...`).**
- ERPNext is the system of record and the GL; the SPA is a thin, opinionated client over
  whitelisted Python endpoints. No separate database.

The app is served as a single HTML shell at route `/stabler` (Frappe
`website_route_rules` → `stabler/www/stabler.html`), which boots the Vue app and injects
`window.__STABLER__` (csrf token, current user, active company, translations).

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend framework | Vue 3 (Composition API, `<script setup>`) |
| Build | esbuild → single bundle in `stabler/public/dist/` (gitignored). `bench build --app stabler` |
| State | Pinia — one store: `stores/session.js` (user, companies, active company, module access) |
| Routing | vue-router, **hash history** (`/stabler#/...`) |
| Charts | apexcharts (via `ApexChart.vue`), apextree (org trees) |
| Diagrams | @vue-flow/* (BPM process editor) |
| CSS | Tabler (Bootstrap 5 based) + thin overrides in `stabler/public/css/stabler.css` |
| Icons | Tabler icons webfont (`ti ti-*`) |
| Backend | Python, Frappe framework. Whitelisted methods in `stabler/api/*.py` |
| Package manager | **npm only** (enforced; `yarn`/`pnpm` blocked via preinstall `only-allow npm`) |
| No build-time deps | dependencies only, no devDependencies; no TypeScript on the SPA |

There is **no REST/JSON:API usage from the SPA**. Every server call goes through one helper.

---

## 3. Frontend ↔ backend contract

`api/client.js` exposes `call(methodPath, args)`:

```js
import { call } from "../../api/client.js";
const rows = await call("stabler.api.sales.list_customers", { company: "ANJAN", limit: 100 });
```

- POSTs form-encoded to `/api/method/<dotted.path>`, sends `X-Frappe-CSRF-Token`,
  `credentials: same-origin`.
- Object args are JSON-stringified automatically.
- Frappe wraps returns in `{message: ...}`; the helper unwraps to the payload.
- 403 → dispatches `stabler:forbidden` event (global handler shows access UI).
- A second helper downloads binary responses (xlsx/pdf exports).

Backend endpoints are plain functions decorated `@frappe.whitelist()` in `stabler/api/<module>.py`.
They take `company` + filters, validate, run parametrized SQL or `frappe.get_doc`, return dicts/lists.

---

## 4. Directory map

```
apps/stabler/
├─ stabler/
│  ├─ api/                  # Python backend — one file per module (116 files, ~58k LOC)
│  │   ├─ _common.py        # SHARED guards: _require_company, _assert_can_read, _validate_money_overrides
│  │   ├─ _accounts.py      # resolve_party_account — per-currency AR/AP routing (multi-ccy integrity)
│  │   ├─ imports.py (7363) sales.py (4132)  tender.py (3331)  money.py (2980)
│  │   ├─ purchasing.py (2690)  reports.py (2460)  _imports_rules.py (1837)  inventory.py (1735)
│  │   ├─ hr.py  compliance.py  marketing.py  dashboard.py  organization.py  admin.py
│  │   ├─ remittance.py  pos.py  crm.py  bpm.py  search.py  marketing_equipment.py …
│  ├─ public/
│  │   ├─ js/
│  │   │   ├─ api/client.js          # the call() helper
│  │   │   ├─ router.js              # all routes, module-gated guard
│  │   │   ├─ stores/session.js      # Pinia: user, companies, canAccessModule()
│  │   │   ├─ composables/           # date.js i18n.js money.js status.js ledger.js modules.js
│  │   │   ├─ components/            # 45 shared components (see §6)
│  │   │   └─ pages/<module>/*.vue   # 227 page components, grouped by module
│  │   ├─ css/stabler.css            # global overrides (striped tables, etc.)
│  │   └─ dist/                      # built bundle (gitignored)
│  ├─ translations/<lang>.csv        # en ru uz uzc tr — source strings + translations
│  ├─ www/stabler.html               # SPA shell
│  ├─ patches/                       # idempotent migration patches
│  └─ hooks.py                       # website_route_rules, scheduler_events, doc_events
└─ docs/plans/                       # feature specs (the design docs)
```

---

## 5. Modules (SPA sections)

Each module = a sidebar entry, a parent route with `meta:{module:"<key>"}`, a `*Home.vue`
tab shell, an `api/<module>.py`. Visibility = company-enabled AND user-role-allowed
(admins see all). Map lives in `api/organization.py:_MODULE_ROLES` + `_MODULE_FIELDS`.

| Module | Route | Key pages | Backend |
|---|---|---|---|
| Dashboard | /dashboard | KPIs, charts | dashboard.py |
| POS | /pos | touch point-of-sale | pos.py |
| Money (accounting) | /money | Chart of Accounts, Journals, Payments, Expenses, Transfers, Reports | money.py |
| Sales | /sales | Customers, Quotations, Sales Orders, Invoices, Returns, AR Aging, Reserved Stock, Reports | sales.py |
| Purchasing | /purchasing | Suppliers, Purchase Orders, Receipts, Invoices, AP Aging | purchasing.py |
| Inventory | /inventory | Items, Warehouses, Material Staging, Stock Entries, Stock Ledger, Low-Stock Alerts | inventory.py |
| Manufacturing | /manufacturing | BOMs, Work Orders (+ /manufacturing/line operator kiosk) | manufacturing.py |
| People (HR) | /hr | Employees, Positions/Org, Attendance, Leave, Payroll | hr.py |
| Field Sales (SFA) | /sfa | Outlets, Routes, Visits, Field Users, Van Stock, Promos, Photos, Planograms, OSA, Receivables | sfa.py |
| Trade Marketing | /marketing | Promo Plans, Equipment, Packs, ROI | marketing*.py |
| CRM | /crm | Leads, Deals (kanban) | crm.py |
| Service | /service | Tickets (kanban), Calendar, Billing Queue (+ Equipment/Map planned) | service.py |
| Processes (BPM) | /bpm | Process editor (vue-flow), node palette | bpm.py |
| Imports | /imports | Import Orders, Proformas, PI Groups, Commercial Invoices, Containers, Vendor Category, HS/duty | imports.py, _imports_rules.py |
| Tender | /tender | Operations Desk, Portfolio, Tender Masters/Lots, Bid pricing + landed cost, Document Center, role queues | tender.py |
| Remittance | /remittance | Corridor transfers (3-leg JE) | remittance.py |
| Installment | /installment | Murabaha contracts, calendar | installment.py |
| Reports | /reports | cross-module report hub | (various) |
| Admin | /admin | Companies, Users, Roles, Compliance (EHF/ARCA/Asl Belgisi/1C/FX) | admin.py, organization.py, compliance.py |

**Measured 2026-08-07** (re-count from the tree, don't quote these from memory):
684 tracked `.py` / 126 389 lines · 281 `.vue` / 91 085 lines · 116 api modules / ~58k LOC ·
227 page components · 45 shared components · 190 test files · 247 routes (90 with `meta.module`).

`Stabler Company Modules` carries **23** `enable_*` flags and only **4** default to `1`
(`money`, `sales`, `purchasing`, `inventory`) — everything else is opt-in per tenant.

---

## 6. Shared components (reuse these — don't reinvent)

`components/`:
- **MoneyInput.vue** — every monetary input (required by rule).
- **DateInput.vue** — every date input; v-model is ISO `yyyy-mm-dd`, displays `dd.mm.yyyy`.
- **Select.vue / Typeahead.vue** — dropdowns; Typeahead for >20 options or async search.
- **ListToolbar.vue** — standard list-page toolbar (search + filters, auto-apply, no Apply button).
- **SkeletonRows.vue** — loading state inside table bodies (never a bare spinner).
- **ModuleHeader.vue** — compact module title + tab nav.
- **BalanceChip.vue** — operator-language balance ("Owes us …" / "Prepaid").
- **PartyAvatar.vue** — name-hashed colored initials.
- **KpiCard.vue, ApexChart.vue, AgingTable.vue, CalendarMonth.vue** — dashboard/report primitives.
- **PaymentModal.vue / PartyPaymentModal.vue** — take payment against invoice / on account.
- **VoucherDrawer.vue, RelatedDocuments.vue, CommandPalette.vue (⌘K), EmptyState.vue, PeriodSelect.vue**.

`composables/`:
- **i18n.js** → `t("source", {params})`; messages from `window.__STABLER__.translations`.
- **money.js** → `formatMoney`, `balanceState`.
- **date.js** → `formatDate` (dd.mm.yyyy), `formatDateTime`.
- **status.js** → `getStatusBadgeClass` (centralized — no per-page status maps).
- **ledger.js, modules.js**.

---

## 7. Hard rules (the model MUST follow these)

These live in `CLAUDE.md` / `AGENTS.md` at repo root and override defaults:

1. **No Frappe Desk links, ever.** No `/app/...` via href, window.open, or router. If a CRUD
   action is missing, build it inside Stabler.
2. **Money fields → MoneyInput**; never bare `<input type="number">` for amounts.
3. **Dates → DateInput + formatDate/formatDateTime**; never bare `<input type="date">` or raw
   ISO interpolation in templates.
4. **Currency display: original transaction/account currency only.** No converted/base-equivalent
   sub-lines; mixed currencies show per-currency breakdowns, never one summed number.
5. **Tables are striped globally** (CSS). Don't add `table-striped`. Currency cells use
   `font-monospace`. Numbers never truncate (names do).
6. **One `.btn-primary` per visual region.** Secondary actions = `.btn-outline-secondary` /
   `.btn-ghost-secondary`. Color is not a second primary.
7. **Module access**: SPA visibility = company-enabled AND user-role-allowed; register new
   modules in `_MODULE_ROLES` and put `meta:{module:"<key>"}` on the parent route. This is a UX
   layer only — real security is Frappe `has_permission`, enforced server-side regardless.
8. **Backend security**: `@frappe.whitelist()` gates method access only, NOT record access.
   Any `get_doc`/raw SQL that fetches a named record must call `_assert_can_read` first (IDOR guard).
   Use shared guards from `_common.py`; don't redefine them.
9. **List pages**: ListToolbar with auto-apply (no Apply/Refresh buttons); SkeletonRows while
   loading; search placeholder suffixed `⌘K`; statuses via central `status.js`.
10. **i18n**: every user-facing string through `t()` (Vue) / `_()` (Python), filled in all 5
    languages before merge. Harvest: `bench --site <site> execute stabler.translations.harvest.run`.
11. **Patches**: `patches.txt` has NO `[post_model_sync]` marker → patches run BEFORE doctype DDL
    sync. A patch touching a new column must guard with `frappe.db.has_column`. Every patch must be
    idempotent (`frappe.db.exists` guards). A patch that fails must abort loudly, never log success.
12. **Multi-currency GL integrity**: route party postings through `_accounts.resolve_party_account`
    (one AR/AP account per currency); cross-currency docs need a real exchange rate (never 1.0 for
    UZS↔USD). Company base currency matters — confirm per tenant.
13. **Git hygiene**: never `git add -A`; stage explicit paths; translations as the 5 CSVs;
    never stage `dist/`, build junk, `.tx_*.json` caches.

---

## 8. Deployment (prod)

- Prod is **rsync, not git** (`ice-production` SSH alias). Always confirm target site first:
  `bench --site <site> list-apps | grep stabler`.
- Procedure: commit locally → `bench build --app stabler` (proves it compiles) → backup tarball →
  rsync source (no `--delete`, excluding dist/.git/node_modules/etc.) → chown → `bench build` →
  `bench --site <site> migrate` (only if patches/doctypes changed) → `bench restart` (if any .py changed).
- `bench restart` restarts the whole shared bench (brief blip for all tenants).

---

## 9. How to phrase requests to an LLM about Stabler

Give the model this brief, then be specific about layer and file. Good prompt shape:

> "In Stabler (Vue 3 SPA over ERPNext, see brief). I want to add **X** to the **Sales** module.
> Backend: add a whitelisted function in `stabler/api/sales.py` following the existing pattern
> (`@frappe.whitelist()`, `_require_company`, parametrized SQL, `_assert_can_read` for named
> records). Frontend: a new page `pages/sales/Y.vue` using ListToolbar + SkeletonvRows, calling it
> via `call('stabler.api.sales.fn', {...})`, MoneyInput/DateInput, t() for all strings, no Desk
> links. Show me the function and the .vue, and the route + sidebar additions."

Things to always tell the model: which module, frontend vs backend vs both, that money/dates
use the shared components, that strings need `t()`, and that it must not invent Desk links or a
second database. For accounting work, mention the tenant's base currency and the per-currency
account rule. For new doctypes, note that schema changes need idempotent pre-sync-safe patches —
and prefer reusing native ERPNext doctypes over inventing new ones.

---

## 10. One-paragraph elevator pitch (for the top of a prompt)

> Stabler is a Vue 3 single-page app built on ERPNext/Frappe that gives Uzbek SMB operators a
> clean, fully self-contained business UI (sales, purchasing, inventory, accounting, HR, field
> sales, CRM, service, manufacturing, BPM, installment, remittance) in 5 languages, never linking
> out to the Frappe Desk. The Vue frontend (pages + shared components, Pinia session store,
> hash router with module-gated access) talks to whitelisted Python functions in
> `stabler/api/*.py` through a single `call()` helper; ERPNext remains the system of record and
> general ledger. Strict conventions: MoneyInput/DateInput everywhere, original-currency display,
> centralized status badges, server-side IDOR guards, idempotent pre-sync patches, and full
> en/ru/uz/uzc/tr i18n.
```
