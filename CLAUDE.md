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

### Tables / lists
- Lists of records use `.table` (or list-group) — striped by default.
- Currency cells use `font-monospace` for alignment.

### Button hierarchy
- Maximum of one `.btn-primary` per visual region (card header, drawer/offcanvas footer, detail header).
- Secondary/neutral actions must use `.btn-outline-secondary` or `.btn-ghost-secondary`. Color must never be used as a "second primary".

### Currency display
- Amounts must render in their original transaction/account currency only. Do not convert totals or display base-currency/USD equivalent sub-lines.

### Centralized status codes
- All status badges and labels must be resolved centrally using `getStatusBadgeClass` from `composables/status.js`. No per-page status mappings.

### Filter and loading guidelines
- Every list page must use `ListToolbar.vue` with auto-apply filtering on filter changes (no Apply/Refresh buttons). Suffix search placeholders with `⌘K`.
- Place animated skeleton rows (`SkeletonRows.vue`) inside the table body while loading data. Never show a spinner in a void.

## Production / Deployment

### Prod site
- **Primary prod = `anjan.erpstable.com`.** Stabler is actually installed on
  **6 sites** on the shared bench (`/home/frappe/frappe-bench`, ~22 tenants):
  `anjan`, `dts`, `horeca`, `laminor`, `mikas`, `smartbox` — verified via
  `bench --site <site> list-apps` across every tenant. `msa.erpstable.com` and
  the remaining tenants do NOT have stabler installed.
- A code change under `apps/stabler/` (shared app code, not per-site) plus
  `bench restart` takes effect on ALL 6 stabler sites at once — no per-site
  redeploy needed. Backend fixes should be spot-checked on at least one
  secondary site (not just anjan) before calling a deploy done.
- Before ANY `migrate` / `restart` / data command aimed at "prod", confirm the
  target: `bench --site <site> list-apps | grep stabler`. Never assume the site.
- SSH alias: `ice-production`. Prod is **NOT a git repo** — deploy is rsync.

### Deploy procedure (rsync + on-server build)
1. Commit locally (specific paths) and `bench build --app stabler` to prove it compiles.
2. Backup first: `ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler'`.
3. rsync source → `ice-production:/home/frappe/frappe-bench/apps/stabler/` with
   `-rltz --no-owner --no-group` (NO `--delete`), excluding `.git node_modules
   dist __pycache__ *.pyc .claude .tx_*.json graphify-out .smoke tests *.tgz .DS_Store`.
   Then `chown -R frappe:frappe …/apps/stabler`.
4. `bench build --app stabler` on prod.
5. `bench --site anjan.erpstable.com migrate` (only if patches.txt / doctypes changed).
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

## Commit hygiene
- **Never `git add -A`.** Stage explicit paths only.
- Never stage dev/build junk: `graphify-out/`, `stabler/translations/.tx_*.json`,
  `.smoke/`, `tests/` (untracked scratch), stray heredoc files. `dist/` is gitignored.
- Stage translations as the five CSVs explicitly (`en/ru/uz/uzc/tr.csv`), never the
  whole `translations/` dir (it pulls the `.tx_*.json` caches).
- Commit message trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## i18n workflow
- Five languages: **en, ru, uz, uzc, tr**. Source strings live in `t()` (Vue) / `__()` (py).
- Harvest new keys: `bench --site <site> execute stabler.translations.harvest.run`
  (scans .vue/.js/.py, appends missing keys to `{lang}.csv`, sorted). `en` target =
  source; `ru/uz/uzc` are filled in manually.
- Reviewers reject PRs that leave new user-facing strings untranslated in any of
  the five languages.
