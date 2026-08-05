# Stabler SPA — Project Rules

## Hard rules (never violate)

### No Frappe Desk redirects, ever
- The Vue 3 SPA at `/stabler/#/...` must NEVER link out to the Frappe
  Desk (`/app/...`) — not via `<a href>`, not via `window.open`, not via
  router meta. Stabler is a fully self-contained UX; sending users to the
  Desk breaks that promise.
- If a CRUD action is missing in Stabler, build it inside Stabler. Do not
  paper over the gap with an "Open in Desk" link.
- Applies to: customers, suppliers, items, employees, accounts, invoices,
  payments — every doctype surfaced in the SPA.

### Striped tables
- Global rule shipped from `stabler/public/css/stabler.css` makes every
  `<table>` striped by default. Do NOT add `class="table-striped"`
  manually — it's already on. To opt out for a specific table, use
  `class="table-no-stripe"`.

### Money fields
- Every numeric monetary input MUST use the shared MoneyInput component.
  Never use bare `<input type="number">` for amounts, rates, or balances.

### Date fields
- Every date displayed in a table or detail view MUST use `formatDate(value)`
  (renders `dd.mm.yyyy`) or `formatDateTime(value)` (renders `dd.mm.yyyy HH:mm`).
  Never interpolate raw ISO strings like `{{ r.posting_date }}`.
- Every date input MUST use the `DateInput` component. Never use bare
  `<input type="date">` — it cannot display `dd.mm.yyyy` and the OS controls
  its locale.
- Both live at: `composables/date.js` and `components/DateInput.vue`.
- `DateInput` v-model is an ISO `yyyy-mm-dd` string (identical to native date
  inputs) — it's a 1:1 drop-in; backend payloads are unaffected.
- Reviewers must reject PRs that introduce bare `<input type="date">` or raw
  date interpolation for any of the four languages (en, ru, uz, uzc).

### Module access
- SPA page visibility = `company-enabled AND user-role-allowed`. Admins (System Manager
  / Stabler Admin) always see every module.
- The role→module map lives in `stabler/api/organization.py:_MODULE_ROLES`. When adding
  a new module, register it there.
- Every module's parent route in `router.js` MUST carry `meta: { module: "<key>" }`.
  Without it the route guard can't block direct-URL access.
- This is a **UX access layer**, not a security boundary. Real data security lives in
  Frappe's `has_permission`, which runs on every backend endpoint regardless of what
  the SPA shows.

### Tenant & feature ownership (multi-tenant discipline)
- Stabler is ONE shared app across **7 tenants with different businesses**. Code is
  shared (one `bench restart` hits all 7); DBs are per-site. A feature built for one
  tenant ships to all — so **every tenant-specific feature MUST be module-gated**
  (`enable_*` + role + route `meta.module`) and MUST NOT change shared-core behavior
  for tenants that don't use it.
- **Feature → owner-module → owner-tenant** (know who you're changing things for):

  | Tenant | Business | Owns (primary modules) |
  |--------|----------|------------------------|
  | anjan | Ice-cream **manufacturing** (main prod) | manufacturing, inventory, sales, money |
  | msa | Meat **import**/distribution | imports (PI, PI Groups, Vendor Category, CI, containers), money, purchasing |
  | mikas | **Tender** / kassa | tender, money (kassa bot), purchasing, crm |
  | dts | Industrial belting **sales** | sales, inventory, money |
  | horeca | **HoReCa** services | service, sales, field_sales, money |
  | laminor | *(confirm with owner)* | *(confirm)* |
  | smartbox | *(confirm with owner)* | *(confirm)* |

  So: PI/PI-Groups/Vendor-Category = `imports` = **msa**. Tender boards/bid/landed +
  kassa bot = `tender`/`money` = **mikas**. These must be invisible where the module is off.
- **Caveat — module defaults are opt-OUT today:** 14/17 `enable_*` fields default to `1`
  in `Stabler Company Modules`, so a new company gets almost everything ON. Prefer
  gating a new module OFF by default and enabling it per owner-tenant. Don't add a
  **reqd** field to a doctype a non-owner tenant also carries.
- **Never branch on tenant name** (`if company == "mikas"`). Parametrize by module +
  company-setting (`Stabler Company Modules`), the way currency precision is read as
  metadata. Tenant variance lives in config/data, never in code constants.
- Full rationale + the professional playbook (opt-in defaults, blast-radius / release
  governance, leakage tests, fork criteria): `docs/plans/2026-07-18-multitenant-governance.md`.

### Tables / lists
- Lists of records use `.table` (or list-group) — striped by default.
- Currency cells use `font-monospace` for alignment.

### Button hierarchy
- Maximum of one `.btn-primary` per visual region (card header, drawer/offcanvas footer, detail header).
- Secondary/neutral actions must use `.btn-outline-secondary` or `.btn-ghost-secondary`. Color must never be used as a "second primary".

### Currency display
- Amounts must render in their original transaction/account currency only. Do not convert totals or display base-currency/USD equivalent sub-lines.
- **Documented exception:** the Sales Order form's sticky footer shows one `≈ {amount}` line —
  the order total converted to the counter-currency (base ↔ reference), derived live from
  `exchangeRatePair`/`activeRate` (never a hardcoded rate or currency literal). This exists
  because Sales Order is the one screen where a user routinely needs to eyeball "what is this in
  USD/UZS" before submitting. It stays a single line, never replaces the transaction-currency
  total, and renders nothing when no live rate is available (see the FX guard note above). Do
  not copy this pattern to other screens without the same justification — see
  `equivalentAmount` in `SalesOrderForm.vue` for the implementation.

### Centralized status codes
- All status badges and labels must be resolved centrally using `getStatusBadgeClass` from `composables/status.js`. No per-page status mappings.

### Filter and loading guidelines
- Every list page must use `ListToolbar.vue` with auto-apply filtering on filter changes (no Apply/Refresh buttons). Suffix search placeholders with `⌘K`.
- Place animated skeleton rows (`SkeletonRows.vue`) inside the table body while loading data. Never show a spinner in a void.

## Production / Deployment

### Prod site
- **Primary prod = `anjan.erpstable.com`.** Stabler is actually installed on
  **7 sites** on the shared bench (`/home/frappe/frappe-bench`, ~22 tenants):
  `anjan`, `dts`, `horeca`, `laminor`, `mikas`, `msa`, `smartbox` — verified via
  `bench --site <site> list-apps` across every tenant (corrected 2026-07-18: an
  earlier note wrongly excluded `msa`; it DOES carry stabler and the PI / imports
  feature lives there). The remaining tenants do NOT have stabler installed.
- A code change under `apps/stabler/` (shared app code, not per-site) plus
  `bench restart` takes effect on ALL 7 stabler sites at once — no per-site
  redeploy needed. Backend fixes should be spot-checked on at least one
  secondary site (not just anjan) before calling a deploy done.
- Before ANY `migrate` / `restart` / data command aimed at "prod", confirm the
  target: `bench --site <site> list-apps | grep stabler`. Never assume the site.
- SSH alias: `ice-production`. Prod is **NOT a git repo** — deploy is rsync.

### Deploy procedure (rsync + on-server build)
1. Commit locally (specific paths) and `bench build --app stabler` to prove it compiles.
2. Backup first: `ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler'`.
3. rsync source → `ice-production:/home/frappe/frappe-bench/apps/stabler/` with
   `-rltz --no-owner --no-group` (NO `--delete`) and
   `--exclude-from=apps/stabler/.rsync-exclude`. **The exclude list lives in that
   file, not here** — it used to be copy-pasted into three deploy scripts plus this
   doc, and the four copies drifted. Add new excludes there only.
   Then `chown -R frappe:frappe …/apps/stabler`.
   **cwd trap (near-miss 2026-07-17):** run rsync from the bench **`apps/`** dir so
   the relative source `stabler/` = the whole app `apps/stabler/`. Running it from
   inside `apps/stabler/` makes `stabler/` resolve to the inner Python module
   (`apps/stabler/stabler/`) while the remote is the whole app — rsync then shows a
   bogus 1500+ deletions and (with `--delete*`) would wipe the sibling
   `stable-erp-website/`. **ALWAYS `-rltzvn` dry-run first and abort if any sibling
   dir or `stable-erp-website/` appears in the delete list.** The `-v` is not
   optional: `rsync -n` without it prints nothing, so an empty dry-run reads as
   "clean" when it actually verified nothing (this cost us a bogus 2026-07-24
   verification).
4. `bench build --app stabler` on prod.
5. `bench --site anjan.erpstable.com migrate` (only if patches.txt / doctypes changed)
   — **run for ALL 7 sites, not just anjan.** `migrate` is per-site; rsync+restart
   are bench-wide, so a doctype/patch change reaches every site's code but only the
   sites you migrate get the DDL. (Near-miss 2026-07-18: `msa` was skipped and its
   new `Import PI Group` columns were missing until a follow-up migrate.)
6. `bench restart` if any `.py` changed.
- **`bench restart` restarts the whole bench → brief blip for ALL tenants**, not
  just anjan. Schedule for low traffic, or accept the blip explicitly.
- Rollback = restore the step-2 tar, `chown`, `bench build`, `bench restart`.

### Post-deploy smoke checks (run every release)
- **Direct-URL / refresh load of a record form.** Open an existing record by
  pasting its URL (not by clicking from the list) and hit refresh, e.g.
  `…/stabler#/purchasing/invoices/<an existing PINV>`. It MUST open populated and
  in the correct view/edit state — NOT a blank "New …" form. Repeat for one
  Sales Invoice, Purchase Order, Quotation and Payment Entry. (Regression class:
  record forms must branch on the **route param**, not the document engine's
  `isCreate`, which is null-based until `load()` runs — so direct loads/refreshes
  would otherwise render blank. See the `if (docName.value)` guard in the
  `*Form.vue` `onMounted`.)
- **Money/GL log is flowing.** After recording one payment, confirm a line lands
  in `sites/anjan.erpstable.com/logs/stabler.payments.log`.

## Migrations / patches
- `patches.txt` has **NO `[post_model_sync]` marker** → every patch runs BEFORE
  the doctype DDL sync. A patch that reads or writes a **new** column/field must
  guard with `frappe.db.has_column(...)` (or be placed under a `[post_model_sync]`
  line), otherwise migrate aborts on "unknown column".
- A new module's enable-default at go-live comes from the **doctype field
  `default`** (e.g. `enable_*` Check = `"1"`), NOT from a backfill patch — the
  backfill skips when it runs pre-sync. Set the field default to the intended state.
- Every patch must be **idempotent**: guard with `frappe.db.exists` /
  `has_column` / `db.exists("Custom Field", …)` so re-running is safe.
- **Verifying a DDL landed: `has_column` alone lies on sites without the app.**
  `frappe.db.has_column("<DT>", …)` raises `TableMissingError` — it does not return
  `False` — when the doctype's table does not exist at all. So "run has_column on
  every site; anything not `True` means migrate was skipped" reports a failure on
  every tenant that simply lacks the optional app. Measured 2026-08-01: `crm` is
  installed on 4 of the 7 stabler sites, so a v66 `CRM Deal` probe threw on dts,
  horeca and msa — where the patch had correctly guarded itself and skipped.
  Probe the table first, and read a missing table as *not applicable*, not as a
  failed migrate:
  `bench --site <s> execute frappe.db.table_exists --args '["<DT>"]'` → if `False`,
  the site does not carry that doctype and there is nothing to verify; only when
  it is `True` does `has_column` returning `False` mean the migrate really was missed.

## Commit hygiene
- **Never `git add -A`.** Stage explicit paths only.
- Never stage dev/build junk: `graphify-out/`, `stabler/translations/.tx_*.json`,
  `.smoke/`, `tests/` (untracked scratch), stray heredoc files. `dist/` is gitignored.
- Stage translations as the five CSVs explicitly (`en/ru/uz/uzc/tr.csv`), never the
  whole `translations/` dir (it pulls the `.tx_*.json` caches).
- Commit message trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`.
  Deliberately unversioned — a pinned model name (`Opus 4.8`, `(1M context)`) goes
  stale and silently conflicts with whatever the harness injects, producing
  trailers that match neither convention.

## i18n workflow
- Five languages: **en, ru, uz, uzc, tr**. Source strings live in `t()` (Vue) / `__()` (py).
- Harvest new keys: `bench --site <site> execute stabler.translations.harvest.run`
  (scans .vue/.js/.py, appends missing keys to `{lang}.csv`, sorted). `en` target =
  source; `ru/uz/uzc` are filled in manually.
- Reviewers reject PRs that leave new user-facing strings untranslated in any of
  the five languages.
