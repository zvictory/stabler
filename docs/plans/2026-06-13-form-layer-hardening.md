# Form Layer Hardening — Bulletproofing + Document-Form Engine

Date: 2026-06-13 · Priority: **P0 (data-loss + GL-corruption class)** before any per-form visual work.
Goal: bring transactional forms (SO, SI, PO, PI, PE, Quotation, Returns) to QuickBooks-grade
reliability — never lose work, never silently clobber, always confirm — and stop re-implementing
the same form spine in every page.

Bar: QuickBooks Enterprise feels trustworthy because (a) it never loses a half-typed transaction,
(b) two users can't overwrite each other unknowingly, (c) every action gives quiet feedback,
(d) data entry is keyboard-first with live totals. Stabler currently fails (a), (b), (c).

Evidence (audited 2026-06-13): 0 `beforeRouteLeave`/`beforeunload` in the SPA; save endpoints
(`update_sales_order` et al.) accept no `modified` token; 0 toast/notify infra; 23 `window.alert`/
`window.confirm`; `FormPage.vue` duplicates the status-badge map that `composables/status.js`
already owns; `FormPage` loading state is a spinner-in-void (violates the project skeleton rule).

---

## Phase 1 — Bulletproofing trio (ship first, ~1 week, no new forms)

### 1A. Unsaved-changes guard — `composables/useDirtyGuard.js`
- Takes a reactive model + a "pristine snapshot"; exposes `isDirty` (deep compare, or a hash on
  load + on every mutation).
- Registers `onBeforeRouteLeave` (vue-router) → if dirty, open the styled confirm dialog (§1C),
  not `window.confirm`. Also `window.addEventListener("beforeunload")` for tab close/refresh.
- Cleared on successful save/submit. Reset snapshot after each successful persist.
- Adopt in every create/edit form. Acceptance: typing a line then clicking a sidebar link or
  Back prompts "Discard unsaved changes?"; saving then leaving does not prompt.

### 1B. Concurrency control — optimistic locking on `modified`
- **Backend**: every `update_*` / `submit_*` / line-mutating endpoint accepts `modified` (the
  timestamp the client loaded). Before `doc.save()`, compare to current
  `frappe.db.get_value(dt, name, "modified")`; on mismatch raise a typed error
  `frappe.throw(_("This document was changed by someone else. Reload to see the latest."),
  exc=frappe.TimestampMismatchError)` (or reuse `doc.check_if_latest()`). Return the doctype +
  name so the client can offer reload.
- `*_detail` reads already return enough — add `modified` to every transactional detail payload.
- **Frontend**: store `modified` on load; send it on save; on conflict show a non-dismissable
  dialog "Document changed by {user} — Reload / Cancel". Never last-write-wins.
- Acceptance: two tabs open the same draft SO; tab A saves; tab B save is rejected with reload
  prompt, no data overwritten. Test covers SO, SI, PO, PI, PE.
- Note: submit/cancel of an already-changed doc must fail the same way (status drift).

### 1C. Notification + dialog system (replaces window.alert/confirm)
- `components/ToastHost.vue` (teleported, top-right, stacked, auto-dismiss) + `composables/useToast.js`
  → `toast.success(msg)`, `.error(msg)`, `.info(msg)`. Mounted once in `App.vue`.
- `composables/useConfirm.js` → `await confirm({title, body, danger, confirmLabel})` returns
  boolean; renders a styled modal (one component), i18n-driven, focus-trapped, Esc/Enter wired.
- Sweep: replace all 23 `window.alert`/`window.confirm` call sites. Success paths that today give
  no feedback (submit, pay, save) must emit `toast.success`.
- Error contract: the `call()` helper already throws typed errors; a top-level handler maps
  uncaught API errors to `toast.error` so no action ever fails silently. Conflict errors (1B)
  route to the reload dialog, not a toast.
- Acceptance: no `window.alert`/`window.confirm` remain (grep gate); submitting an invoice shows
  a success toast; a failed save shows an error toast with the server message.

### 1D. Fix the self-inflicted regressions (same PR, cheap)
- Delete `FormPage.STATUS_BADGE`; import `getStatusBadgeClass` from `composables/status.js`.
  Add a review/lint note: status colors come from one place only.
- `FormPage` loading → render a field-grid skeleton (reuse/extend `SkeletonRows` pattern), not a
  centered spinner.

---

## Phase 2 — Document-form engine (stop re-implementing forms)

Problem: `SalesInvoiceForm` (468 L) and `SalesOrderForm` (1197 L) share only `FormPage` and
re-build load/dirty/save/submit/cancel/amend, line add/remove, totals, currency, item search,
availability. N divergent forms = the ERPNext maintenance wall, rebuilt in Vue. Extract the spine.

### 2A. `composables/useDocumentForm.js`
Config-driven lifecycle for any transactional doctype:
```
useDocumentForm({
  doctype, detailApi, createApi, updateApi, submitApi, cancelApi, amendApi, deleteApi,
  blankModel, toPayload(model), fromDetail(detail),
})
→ { model, loading, saving, error, isDirty, isCreate, editable, docstatus, status, modified,
    load(name), save(), submit(), cancel(), amend(), remove(),
    can: { save, submit, cancel, amend, delete, pay } }
```
- Wraps 1A (dirty), 1B (modified token), 1C (toasts + confirm + conflict reload) so every form
  gets the bulletproofing for free — no form re-implements them.
- `can.*` permission flags computed from docstatus centrally (today each form hand-rolls these).

### 2B. `components/LineItemsEditor.vue`
The shared line-item grid (the biggest copy-paste source):
- add / remove / **reorder** rows; item Typeahead search; UOM select + conversion; rate
  (MoneyInput); qty; per-line amount; **live running total** (per currency); optional per-line
  slot for domain extras (warehouse + availability for SO, tax for SI, etc.) via scoped slots.
- **Keyboard-first** (the QuickBooks feel): Enter on last row adds a row; Tab cycles fields;
  Esc cancels row edit; arrow keys move between rows. No mouse required for data entry.
- **Inline validation**: invalid cells (qty ≤ 0, negative rate, over-available) get a red border
  and message *as you type*, not a throw on save. Save button disabled while any row invalid.
- Emits a clean items array; parent maps to payload.

### 2C. Refactor existing forms onto the engine
SalesOrderForm + SalesInvoiceForm first (prove the abstraction on the two hardest), then PO, PI,
PaymentEntry, Quotation, Returns. Each should shrink to: config + domain-specific slots +
field grid. Target: SOForm well under 400 lines, no duplicated lifecycle logic.
- Acceptance: feature parity (availability, UOM, reserve-on-submit, partials) preserved; both
  forms pass the same dirty/conflict/toast tests; a new doctype form is <150 lines of config.

---

## Phase 3 — Per-form visual retouch (the original ask — AFTER 1 & 2)

Only once forms are safe and unified. Apply the design grammar to SO/SI/PE/customer-center views:
- QuickBooks-grade entry: sticky running total, inline validation, keyboard flow (from 2B).
- Customer-center embedded views (PE/SI/SO drawers): consistent header, original-currency
  amounts only, document timeline, one primary action per region (existing hard rules).
- Status via `status.js`; dates via DateInput/formatDate; money via MoneyInput (audit, don't assume).
- Detailed visual spec to follow per form once the engine lands — small once 2B owns the grid.

---

## Sequencing & rationale
1 (trio + regressions) → 2A/2B (engine) → 2C (refactor SO/SI) → 3 (retouch).
**Do not start Phase 3 first** — polishing 40 hand-built forms is a treadmill; the data-loss and
concurrency holes are live now. Brakes before paint.

## Acceptance gate (whole effort)
- No code path can lose unsaved form input without an explicit user choice.
- No two users can silently overwrite the same document.
- No `window.alert`/`window.confirm` in `public/js`; every action gives feedback.
- One status-color source; one form lifecycle; one line-item grid.
- A brand-new transactional form is a thin config, not a 1000-line rewrite.

## Out of scope
- Offline form drafts / autosave-to-server (revisit after Phase 1 — local dirty-guard covers the
  acute risk).
- Real-time multi-user presence (locking via `modified` is sufficient; presence is a nicety).
- Dark mode.
