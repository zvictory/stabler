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
- **A percent is in scope and it is not a MoneyInput amount.** Its approved shape is a
  `.form-control` inside an `.input-group` whose suffix is `<span class="input-group-text">%</span>`
  — either a bare `<input type="number" class="form-control">` (`BidPricing.vue:171`) or
  `MoneyInput` with `hide-currency` and an explicit `:max-fraction-digits`, which renders the same
  `.form-control` and adds locale grouping (`NewRemittance.vue:711`). A percent never gets currency
  precision and never calls `moneyFractionDigits`.
  **Not `ds-input`.** Measured 2026-09-01 in Chrome against the pinned Tabler: `ds-input` is outside
  Tabler's `.input-group > .form-control` flex contract and carries `width: 100%`, so the `%` wraps
  to a second row and the group renders 80px tall instead of 44.
- Name a percent field `*_pct`, `*_percent` or `*percentage`. That is not cosmetic: `make guards`
  exempts exactly those name shapes from the money check (`Makefile:508`), so a percent called
  `*_rate` is reported as a MoneyInput violation and the gate wins.
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
- Maximum of one primary button per visual region (card header, drawer/offcanvas footer, detail header).
- Color must never be used as a "second primary". Secondary/neutral actions use
  `.btn-outline-secondary` or `.btn-ghost-secondary`.
- **Which vocabulary you write is decided by the markup you are in, not by preference.** The
  bridge re-skins `.btn`, `.btn-sm`, `.btn-primary`, `.btn-icon`, `.btn-ghost-*` and `.btn-link`
  under `.stbl-ds` (`stabler-modernist.css:950-974`), so opting a screen into the design layer
  needs **no** button rewrite. `ds-btn` / `ds-btn--primary` are for markup the design layer owns
  outright — not a migration target for buttons that already work.
- A **shared** component is rendered in both scopes by different callers, so it keeps the
  Bootstrap vocabulary and lets the bridge cover it. Never migrate one to `ds-*`: `ListToolbar`
  hardcodes `btn btn-sm btn-primary` (`ListToolbar.vue:63`) and mandate 8 makes it compulsory on
  every list page — measured 2026-09-01, it has 46 consumers, most of them outside `.stbl-ds`.
- **`ds-btn` has no disabled state, so it is not yet safe for a button that can be disabled.**
  Measured 2026-09-01 in Chrome against the pinned Tabler (`www/stabler.html:1`): a disabled
  `.ds-btn` renders `opacity: 1` with `pointer-events: auto` — indistinguishable from enabled, and
  still taking clicks — while a bridged `.btn:disabled` fades to `.4` and stops taking them. The
  fix is drafted (`docs/design/2026-09-01-asama-a-delta.css`) and not yet in the layer.
- Nothing enforces this mechanically. `make guards` has no button check, and the per-screen source
  tests that assert button classes cover only the Bootstrap half. A guard is writable in the shape
  of the `type="date"` check (`Makefile:463-469`), but not while in-scope screens still mix both
  vocabularies — write it after they stop, not before.

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
- Loading a table: mount `SkeletonRows.vue` **in place of** the table body, never inside it. Its
  own root is a `<tbody>` (`SkeletonRows.vue:10`), so putting it inside one renders
  `<tbody><tbody>`. Two shapes are correct — `<SkeletonRows v-if="loading" />` as a sibling of
  `<tbody v-else>`, both direct children of `<table>`; or a whole-block `v-if`/`v-else` swap whose
  loading branch carries its own `<table>`. Measured 2026-09-01: 96 call sites, 16 nested wrongly.
  Correct one when you next edit that file for another reason — this is not a sweep.
- Loading something that is **not** a table (cards, panels, a drawer): `SkeletonRows` is still what
  the repo uses, and `test_tender_desk_spa.py:23` requires it in `OperationsDesk.vue`, whose two
  uses are panel-mounted. Do not "fix" such a site by deleting the component — that turns
  `make check` red. `ds-skel-stack` is drafted for this case
  (`docs/design/2026-09-01-asama-a-delta.css`) and the assertion moves with the markup when it lands.
- Never show a spinner in a void.
