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
