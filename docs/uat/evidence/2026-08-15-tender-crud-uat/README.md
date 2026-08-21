# Tender CRM full CRUD — live UAT on production mikas

- **Date:** 2026-08-15
- **Target:** `https://mikas.erpstable.com/stabler#/tender/crm` (company `Mikas`)
- **Bead:** `stabler-cm5` (Tender CRM full CRUD: wire edit mode + delete action)
- **Script:** [`docs/uat/scripts/live_mikas_tender_crud_uat.js`](../../scripts/live_mikas_tender_crud_uat.js)
- **Raw result:** [`tender_crud_results_1786806602121.json`](./tender_crud_results_1786806602121.json)
- **Run #1 (pre-fix):** **11 passed, 3 failed**, exit 1 — the failures are the point.

This is run #1, executed against the *already deployed* feature to find out whether it
actually works in production. It does not. Two independent defects are proven below.
The script asserts correct behaviour unconditionally; there is no flag that turns a red
step green.

## Why the handoff's own 4-step UAT would have passed and proved nothing

The create payload in `TenderMasterDrawer.vue:228-295` carries no `status`, so a freshly
created deal has **no stage history**. Scenario A (the handoff's literal four steps)
therefore deletes cleanly — and never touches the code path real users hit. Scenario B
was added to create a deal, move it one lane, and only then delete it. That is the case
that fails.

## Scenario A — create → read → edit → delete (fresh deal)

| Step | Assertion | Result |
|---|---|---|
| `UAT-A1-CREATE` | New tender lands on the board | PASS — `CRM-DEAL-2026-00107` |
| `UAT-A1-LANE` | Lands in the first lane (Intake) | PASS — column index 0 |
| `UAT-A2-READ` | `?deal=<name>` deep link opens that exact deal | PASS |
| `UAT-A3-EDIT-OPEN` | Edit form restores the stored intake | **FAIL — defect 2** |
| `UAT-A3-EDIT-SAVE` | Edited title is persisted and read back | **FAIL — defect 2** |
| `UAT-A3-EDIT-CARD` | Edited tender still holds exactly one card | PASS |
| `UAT-A4-DELETE` | Fresh tender deletes cleanly | PASS — count 0 |
| `UAT-A4-BOARD` | Deleted card is gone from the board | PASS |

## Scenario B — a deal that carries its own stage history

| Step | Assertion | Result |
|---|---|---|
| `UAT-B1-CREATE` | Second tender created | PASS |
| `UAT-B2-HISTORY` | Lane move records a `CRM Stage Event` | PASS — `move_deal_stage` HTTP 200, stage events = 1 |
| `UAT-B3-DELETE` | Tender carrying only its own stage history deletes cleanly | **FAIL — defect 1** |

---

## Defect 1 — a deal that was ever moved between lanes cannot be deleted

Verbatim server response captured by the run (`delete_api_responses[1]`, HTTP 417):

```
exc_type: LinkExistsError
Cannot delete or cancel because CRM Deal CRM-DEAL-2026-00107
is linked with CRM Stage Event STAGE-EVT-2026-000151
```

The SPA surfaces this as “Could not delete the tender.”

**Root cause**

1. `stabler/api/crm.py:526` → `frappe.delete_doc("CRM Deal", name)` with `force=0`.
2. `CRM Stage Event` links the deal twice: `deal` (reqd Link) and
   `reference_doctype`/`reference_name` (Dynamic Link).
3. Stabler registers no `ignore_links_on_delete`, so `CRM Stage Event` is not exempt.
4. `doc_events["CRM Deal"]` has no `on_trash` handler to drop the deal's own history.

Every deal in real use has been moved at least once, so in practice **delete is broken
for every deal a user would want to delete**. Unit coverage missed it because
`test_crm_company_scope.py:152` stubs `frappe.delete_doc` with a recorder — the delete
never runs, only the permission gate is measured.

**Fix (approved, this session):** an `on_trash` handler that drops only the deal's own
`CRM Stage Event` rows. `frappe/model/delete_doc.py` runs `on_trash` at line 165 and the
link checks at 172-173, so rows dropped in `on_trash` are not caught. `delete_deal`
itself is left untouched, so a deal referenced by a Tender Sourcing Decision, quotation,
RFQ or order is **still refused** — that is the deliberate semantic Zafar chose.

## Defect 2 — the tender title is never persisted (found during this UAT)

Not part of the approved scope. Filed as bead **`stabler-ac0`** (P1).

`TenderMasterDrawer.vue:257` sends `title` inside `intakePayload` to
`stabler.api.tender.save_deal_intake`. That endpoint runs `_clean_intake`
(`tender.py:1280-1300`, applied at `:1366`), which rebuilds a fresh dict from
`_INTAKE_KEYS_STR` / `_INTAKE_KEYS_NUM`. Neither whitelist contains `title` — nor
`tender_no`, `source`, `publication_date`, `submission_deadline`, `currency`,
`estimated_total`. All seven are silently discarded.

Live probe against production during this run:

```
GET /api/method/stabler.api.tender.deal_intake?deal=CRM-DEAL-2026-00107&company=Mikas
→ HTTP 200, intake object returned with no "title" key at all
```

**User-visible consequence:** `TenderMasterDrawer.vue:147` seeds `form.title` from
`val.organization` and `:166` only overwrites it when `intake.title` exists. Re-opening
*Edit tender* shows the **customer name** in the required *Tender Title* field
(`title field="Metro"` in the results JSON), and saving writes the customer name over
the real tender title. This is a data-loss round-trip, not a cosmetic glitch.

It stayed invisible because the board card and the drawer heading both render
`_deal_label()` (`tender.py:1895-1900`) — the **organization**, never the title. Any UAT
that keys on the card text reads the customer back and looks green. This script keys
every identity assertion on the deal name (`.ds-card-id`, `.crm-dw-src`,
`.ds-drawer-kicker`) for exactly that reason.

## Screenshots

| File | Shows |
|---|---|
| `01_board_initial.png` | Empty board before the run |
| `02_a_card_created.png` | Scenario A card on the Intake lane |
| `03_a_read_drawer.png` | Detail drawer opened via `?deal=` deep link |
| `04_a_edit_drawer.png` | **Defect 2** — Edit form showing the customer name as the title |
| `05_a_edit_readback.png` | **Defect 2** — the same wrong value after save + reload |
| `06_a_delete_confirm.png` | Delete confirmation modal (scenario A) |
| `07_a_board_after_delete.png` | Card gone — fresh deal deletes cleanly |
| `08_b_card_created.png` | Scenario B card |
| `09_b_after_lane_move.png` | After the lane move that creates the stage event |
| `10_b_delete_confirm.png` | Delete confirmation modal (scenario B) |
| `11_b_after_delete_attempt.png` | **Defect 1** — deal still present, delete refused |
| `12_final_board.png` | Board at end of run |

## Production hygiene

The run left `CRM-DEAL-2026-00107` behind (defect 1 blocked its own teardown). It was
removed afterwards; mikas was verified back to **0 `CRM Deal` / 0 `CRM Stage Event`**
via `frappe.client.get_count` before this evidence was written. No test data remains on
production.

Run #2 (post-fix, post-redeploy) belongs in this same folder and must be fully green
with scenario B self-cleaning.
