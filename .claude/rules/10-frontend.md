---
description: Stabler frontend invariants — Vue SPA, money/date inputs, tables, buttons, filters, currency display, status codes.
paths:
  - "**/*.vue"
  - "**/*.js"
  - "**/public/**"
  - "**/www/**"
---

# Frontend hard rules (never violate)

Moved verbatim out of CLAUDE.md on 2026-08-15 so they cost nothing on backend-only
sessions. Original: `docs/archive/CLAUDE.md.2026-08-15.bak`.

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
- **How many decimals a currency has is decided in `composables/money.js` and
  nowhere else** — call `moneyFractionDigits(currency)`. Do not write
  `cur === "UZS" ? 0 : 2` in a page. Three files had each grown their own copy
  of that ternary; `c7607d9` corrected one on 2026-08-20 and the other two kept
  showing whole so'm over a ledger that stores kopecks. `make guards` now
  rejects a fourth.

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
- **Documented exception:** the Journal Entry form shows one base-currency residual line
  beside the balance badge, and only when the entry is out of tolerance *and* the auto-filled
  counter-amount landed on a foreign line. It exists because that is the state in which Save
  is disabled and the transaction-currency figures alone cannot explain why: the residual is
  measured in the company base, so a line reading `100.09 USD` and one reading `1 234 567 сўм`
  look reconcilable and are not. Same conditions as the Sales Order exception — a single line,
  a live rate, never a replacement for the transaction-currency totals — plus one more: it
  renders only while the form refuses to save, and disappears the moment it balances. It is an
  error explanation, not a display convenience. The per-row `→ base` hints it replaced are not
  covered by either exception and must not come back.

### Centralized status codes
- All status badges and labels must be resolved centrally using `getStatusBadgeClass` from `composables/status.js`. No per-page status mappings.

### Filter and loading guidelines
- Every list page must use `ListToolbar.vue` with auto-apply filtering on filter changes (no Apply/Refresh buttons). Suffix search placeholders with `⌘K`.
- Place animated skeleton rows (`SkeletonRows.vue`) inside the table body while loading data. Never show a spinner in a void.
