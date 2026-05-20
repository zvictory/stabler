# SFA + Marketing Create/Edit Drawers — Design

**Date:** 2026-05-20
**Author:** zvictory + Claude
**Status:** Validated, ready to implement
**Scope:** Phase 3 follow-up — 11 list pages get Create + Edit drawers

---

## 1. Goal & Scope

Add Create + Edit drawers across 11 list pages so users can manage SFA and
Marketing entities without leaving the Vue SPA.

**In scope (11 drawers):**

| Page | Doctype | CRUD shape |
|---|---|---|
| Outlets | Outlet | Create + Edit |
| Routes | Route | Create + Edit (child: RouteOutlet) |
| Visits | Visit | Create + Edit (child: VisitStep) |
| FieldUsers | Field User | Create + Edit |
| VanStock | Van Stock | Create + Edit (child: VanStockItem) |
| Promos | Promo Scheme | Create + Edit |
| Photos | Photo Report | Create + Edit + file upload |
| Planograms | Planogram | Create + Edit (child: PlanogramItem) |
| OSA | OSA Audit | Create + Edit (child: OSAAuditLine) |
| PromoPlans | Promo Plan | **Edit only** (create exists) |
| Claims | Marketing Claim | **Workflow drawer** (Approve/Reject/Settle) |

**Out of scope:**

- Receivables.vue, ROI.vue (read-only by design)
- Equipment.vue, RepairRequests.vue (drawers already shipped)
- Shared `<Drawer>` component refactor (deferred — re-evaluate after seeing
  11 duplications)
- Automated tests (no existing test pattern for these pages — separate task)
- Mobile viewport (Phase 1.5)

---

## 2. Architecture

**Drawer component pattern:** per-page inline Tabler modal matching
`Customers.vue:342-410`. No shared abstraction yet (Rule 2).

```js
const drawerOpen = ref(false)
const drawerMode = ref<'create' | 'edit'>('create')
const form = ref(blankEntity())
const submitting = ref(false)
const submitError = ref('')

function openCreate() { form.value = blankEntity(); drawerMode.value = 'create'; drawerOpen.value = true }
function openEdit(row) { form.value = JSON.parse(JSON.stringify(row)); drawerMode.value = 'edit'; drawerOpen.value = true }
function submitDrawer() {
  // imperative validation
  if (!form.value.name1?.trim()) return (submitError.value = t('Name is required.'))
  submitting.value = true
  const fn = drawerMode.value === 'create' ? api.createEntity : api.updateEntity
  fn(form.value).then(...).finally(() => submitting.value = false)
}
```

**Validation:** imperative `submitError` ref + button
`:disabled="submitting || !form.required.trim()"`. No Zod (Rule 11).

**API contract:** per-entity `update_<entity>(name, payload) -> dict`:

1. `_require_write(company)` — permission gate
2. `doc = frappe.get_doc(DOCTYPE, name)` — load
3. tenant-isolation check (`doc.company == company`)
4. `doc.update(payload).save()` — Frappe cascades to child tables
5. return serialized doc

**Child rows:** nested arrays in `form.value`. Save sends full child array
(replace-all semantics, not diff — see R2).

**File upload (Photos only):** FormData POST to `/api/method/upload_file`,
set `form.photo_url` from response.

**Claims workflow drawer:** read-only grid + notes textarea + Approve /
Reject / Settle buttons. No `update_claim` endpoint.

---

## 3. Backend Changes

**`stabler/api/sfa.py` — 9 new endpoints:**

| Function | Doctype | Child |
|---|---|---|
| `update_outlet` | Outlet | — |
| `update_route` | Route | RouteOutlet (`outlets`) |
| `update_visit` | Visit | VisitStep (`steps`) |
| `update_field_user` | Field User | — |
| `update_van_stock` | Van Stock | VanStockItem (`items`) |
| `update_promo_scheme` | Promo Scheme | — |
| `update_photo_report` | Photo Report | — |
| `update_planogram` | Planogram | PlanogramItem (`items`) |
| `update_osa_audit` | OSA Audit | OSAAuditLine (`lines`) |

**`stabler/api/marketing.py` — 1 new endpoint:**

- `update_promo_plan(name, payload)` — Promo Plan, no child

**Shared helper (extract first, in agent A's initial commit):**

```python
def _update_doc(doctype, name, payload, company, serializer):
    _require_write(company)
    doc = frappe.get_doc(doctype, name)
    if not _is_admin() and doc.company != company:
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    doc.update(payload)
    # defense in depth — payload could try to change company
    if not _is_admin() and doc.company != company:
        frappe.throw(_("Cannot move row across companies"), frappe.PermissionError)
    doc.save()
    return serializer(doc)
```

Each `update_<entity>` becomes a 3-line wrapper picking the right serializer.

**No changes to:** `marketing_equipment.py`, workflow endpoints
(`review_claim`, `settle_claim`, `update_promo_plan_status`).

---

## 4. Frontend Changes

**`api/sfa.js`:** add 9 `update*` methods.
**`api/marketing.js`:** add `updatePromoPlan`.

**Page-by-page (LoC current → estimated):**

| Page | LoC | Drawer | Child rows |
|---|---|---|---|
| Outlets.vue | 109 → ~280 | Create+Edit | — |
| Routes.vue | 83 → ~320 | Create+Edit | outlets[] |
| Visits.vue | 111 → ~340 | Create+Edit | steps[] |
| FieldUsers.vue | 83 → ~240 | Create+Edit | — |
| VanStock.vue | 103 → ~320 | Create+Edit | items[] |
| Promos.vue | 107 → ~280 | Create+Edit | — |
| Photos.vue | 103 → ~300 | Create+Edit+upload | — |
| Planograms.vue | 83 → ~310 | Create+Edit | items[] |
| OSA.vue | 90 → ~310 | Create+Edit | lines[] |
| Claims.vue | 267 → ~400 | Workflow | — |
| PromoPlans.vue | 313 → ~430 | Edit only | — |

**Child-row UX:** `<table>` inside drawer, `+ Add` button appends blank row,
`×` button per row splices. Quantity inputs use
`<input type="number" inputMode="decimal">` (qty ≠ money — Money Input Rule
N/A for these child tables).

**Photos upload:** disable submit while `uploading=true`, preview via
`<img :src="form.photo_url">`.

**Claims workflow:** buttons gated by `claim.workflow_state`. Refetch row
from server after each action (avoids workflow-state desync — see R4).

**i18n:** every label wrapped in `t()`. Harvest run in verification.

---

## 5. Parallelization

**4 worktree agents, sequential merge A → B → C → D.**

| Agent | Endpoints | Pages |
|---|---|---|
| A | update_outlet, update_route, update_field_user | Outlets, Routes, FieldUsers |
| B | update_visit, update_van_stock | Visits, VanStock |
| C | update_photo_report, update_planogram, update_osa_audit | Photos, Planograms, OSA |
| D | update_promo_scheme, update_promo_plan | Promos, Claims, PromoPlans |

**Spawn:** single message with 4 `Agent` calls using `isolation: "worktree"`.

**Merge order:** A first (lands `_update_doc` helper) → B → C → D. After
each merge: `npm run build` + smoke-test that page.

**Agent contract (per agent prompt):**

- This design doc as ground truth
- `Customers.vue:342-410` as precedent
- Money Input Rule, Rule 2 (no new abstractions), Rule 3 (surgical),
  Rule 11 (match conventions), Rule 12 (fail loud)
- "Send full child array on save, never partial"
- "Do not add doctype fields, patches, or migrate steps — STOP and surface"
- `npm run build` must exit 0 in worktree before reporting done

---

## 6. Verification

**Per-agent (in worktree):**

1. `npm run build` exits 0
2. `npm run lint` clean on touched files
3. Manual smoke: open page, New → validate empty submit, submit valid form,
   Edit a row, change field, save, verify list reflects change
4. Child-table pages: add row, remove row, save, verify persistence
5. Photos: upload file, verify preview + `photo_url` saved
6. Claims: Approve → workflow_state advances

**Main session (after each merge):**

7. Re-build, no compile errors
8. Smoke-test 2 unrelated pages (Customers, SalesOrders) — no regressions
9. Browser-console `frappe.call` to each new endpoint — returns updated row

**Post-all-merges:**

10. `bench --site stabler execute stabler.translations.harvest.run` — key
    count grew (~80-120 expected)
11. `bench --site stabler migrate` — no-op, confirms schema unchanged
12. Final `npm run build`
13. Commit per-file (never `git add -A`)

**Acceptance (binary):**

- All 11 drawers open, validate, submit (create + edit)
- All 10 new endpoints persist + return updated row
- `npm run build` exits 0 on main
- i18n harvest pulled new keys with no errors

---

## 7. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | `sfa.py` merge conflicts | HIGH | LOW | A commits helper first; B/C rebase |
| R2 | Child-table replace-all semantics | MED | MED | Frontend always sends full array; documented in docstrings |
| R3 | Photos upload race | LOW | MED | Disable submit while `uploading=true` |
| R4 | Claims workflow desync | LOW | HIGH | Refetch claim after each action |
| R5 | i18n drift (harvest forgotten) | HIGH | LOW | Mandatory verification step 10 |
| R6 | Permission bypass via payload | LOW | HIGH | Double tenant-check in `_update_doc` (before + after `.update()`) |
| R7 | Drawer state leak between create+edit | MED | LOW | `openCreate()` resets form; `closeDrawer()` clears errors |
| R8 | Scope creep (shared component extraction) | MED | MED | Agent prompts cite Rule 2 + Rule 3 |
| R9 | Hidden schema needs surface | MED | MED | Agent prompts say STOP-and-surface, no patches |

---

## Carry-over (deferred — not this pass)

- ru/uz/uzc translations for new keys (Phase 3 carry-over)
- Shared `<Drawer>` component refactor (post-mortem after 11 drawers ship)
- Vitest specs for drawer behavior
- Mobile viewport (Phase 1.5)
