# Form Layer Hardening — Close-out Brief (for Antigravity)

Date: 2026-06-13 · Follows `2026-06-13-form-layer-hardening.md`. Phase 1 + 2 landed and the
high-risk parts are correct (typed `check_concurrency`, ToastHost/ConfirmHost mounted, 0
`window.alert`, 7 forms on `useDocumentForm`, engine sends `modified` on save/submit/cancel).
This brief closes the remaining gaps so the work is **actually** bulletproof, not mostly.

Do these as separate, logically-scoped commits. Use the AGENTS.md commit trailer. Stage explicit
paths only (never `git add -A`; never stage `graphify-out/`, `dist/`).

---

## T1 — COMMIT THE WORK FIRST (urgent)
Everything from the hardening effort is uncommitted working-tree state right now. One crash or
stray `git checkout` loses it all. Before any further edits:
- Commit in logical chunks: (a) `_common.py check_concurrency` + backend `modified` params;
  (b) composables (`useDocumentForm`, `useDirtyGuard`, `useToast`, `useConfirm`);
  (c) hosts + App.vue wiring + `window.alert` sweep; (d) form refactors; (e) FormPage status dedup.
- Do NOT stage `graphify-out/*` (currently shows as modified — it's build output).
- Confirm `bench build --app stabler` passes before committing the JS.

## T2 — Close the fail-open hole in `check_concurrency` (correctness)
`_common.py:46` returns silently when `modified` is missing → any mutation that omits the token
gets zero protection (last-write-wins, invisibly). The engine always sends it, but endpoints
called outside the engine don't necessarily.
- **Audit** every mutating endpoint (update/submit/cancel/delete + inline actions like
  PaymentModal, list-page quick actions, stage moves) — confirm the caller passes `modified`.
  Make a list of any that don't.
- **Policy decision (implement):** for mutations of an **existing, already-loaded** document,
  a missing `modified` token should be **rejected**, not waved through —
  `frappe.throw(_("Stale request: reload the document."))`. Keep the silent-return ONLY for
  genuinely create-time paths where no prior version exists (those don't call check_concurrency
  anyway). Net: an existing-doc mutation with no token must never silently win.
- Keep the typed `TimestampMismatchError` for the mismatch case (already correct).

## T3 — Regression tests for the bug you just fixed (bulletproofing)
The spec's acceptance gate required conflict-path tests; none exist (only money/service helpers).
Without them the concurrency guard will be refactored away unnoticed.
- Add `stabler/tests/test_concurrency.py`: for each of Sales Order, Sales Invoice, Purchase Order,
  Purchase Invoice, Payment Entry — load a doc, capture `modified`, mutate it once (bump modified),
  then assert a second save with the **stale** token raises `TimestampMismatchError` (or the
  configured exc) and that `frappe.local.response` carries doctype+name.
- Add one test asserting **missing** token on an existing-doc update is rejected (T2 policy).
- Add a frontend note (or lightweight test) that `useDirtyGuard` blocks navigation when dirty —
  at minimum a manual QA checklist item, ideally a component test.

## T4 — Finish the two consistency loose ends (verify, then fix)
- **SalesInvoiceForm** uses `useDocumentForm` but hand-rolls its own `<tr>` item table instead of
  `LineItemsEditor` (confirmed). Decide: if SI item lines are genuinely read-only/derived-from-SO,
  document that with a comment and leave it; if they're editable, migrate to `LineItemsEditor` so
  validation/keyboard/totals behave identically to the other forms. No third state.
- **SalesOrderForm is still 909 lines** (spec target <400). The engine absorbed the lifecycle but
  SO-specific logic remains. Review for duplication the abstraction was meant to remove (totals,
  currency, item-search, availability) — push reusable parts into `LineItemsEditor`/composable
  scoped slots. Acceptance: SOForm meaningfully smaller, no logic that also lives in the engine.

## T5 — Two smaller items from the original spec to confirm
- **FormPage loading skeleton** (spec 1D): confirm loading state renders a field-grid skeleton,
  not a centered spinner-in-void. Fix if still a spinner.
- **Conflict reload UX**: confirm the frontend catches `TimestampMismatchError` distinctly from a
  generic error and shows a non-dismissable "Document changed — Reload" dialog (not just a toast).
  A stale-save and a validation error must produce different UI.

---

## Acceptance (close-out)
- All hardening work committed; `bench build` green.
- No existing-document mutation can succeed without a valid `modified` token.
- `test_concurrency.py` passes for SO/SI/PO/PI/PE; stale and missing-token cases both covered.
- SalesInvoiceForm line-editing decision made and consistent; SOForm reduced.
- Conflict path shows a reload dialog, not a silent failure or a generic toast.

Out of scope (unchanged): autosave-to-server, real-time presence, dark mode, Phase 3 visual retouch
(starts only after this close-out passes).
