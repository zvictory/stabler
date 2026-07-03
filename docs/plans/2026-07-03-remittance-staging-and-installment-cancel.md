# Remittance staging + Installment same-day cancel (2026-07-03)

Backend implementation of two Phase-4 items. **Both add custom fields via patches, so
`bench migrate` is required on deploy** (unlike the security PR, which was code-only).

## 1. Installment — same-day cashier cancel/restore

**Problem.** Collections allocate a payment across schedule rows, then throw the
allocation away (only `paid_amount`/`outstanding` are written back). A cancel couldn't
know which rows a specific Payment Entry covered — fatal with partial rows and multiple
same-day collections.

**Fix.**
- `patch v32` adds a hidden `stabler_installment_alloc` (Long Text) on Payment Entry.
- `collect_payment` now writes a JSON snapshot of the exact rows it covered.
- New endpoint `cancel_collection(payment_entry, modified=None)`:
  - Restricted to collections dated **today** (cashier correction, not historical unwind).
  - Verifies it's an installment collection; concurrency-checked; company-scoped;
    `_assert_can_write(..., "cancel")`.
  - Cancels the PE (ERPNext reverses its GL + invoice outstanding), then un-applies the
    schedule writeback via `_reverse_allocations` — **newest-covered row first**.
- `_reverse_allocations` is a pure function: it **subtracts** each covered amount from the
  row's *current* value (not restoring the snapshot's absolutes), so a later same-day
  collection on the same row is preserved, not clobbered; `paid_amount` is clamped ≥ 0.
- Unit tests: `stabler/tests/test_installment_cancel.py` (partial rows, two PEs on
  different rows, two PEs on the same row, clamp, missing row).

## 2. Remittance — register → payout → refund staging

Kept the **JE-only** model (no new doctype, per decision). `patch v33` adds custom fields
on Journal Entry: `stabler_remittance_id`, `stabler_remittance_stage`
(Register/Payout/Refund), `stabler_pickup_code` (hidden), `stabler_sender_name`,
`stabler_receiver_name`. Stage JEs of one transfer share the remittance id.

**Accounting (single company, in-transit liability):**

```
REGISTER   Dr cash_in        send_ccy     Cr intransit(liability) receive_ccy   Cr commission
PAYOUT     Dr intransit      receive_ccy  Cr payout(cash/bank)    receive_ccy
REFUND     Dr intransit + Dr commission                          Cr cash_in     send_ccy
```

Register anchors `commission_base = cash_in_base − payout_base`, so all three stages
balance exactly in base and per-currency (verified same- and cross-currency).

**Decisions applied:** refund = full make-whole (principal + commission clawed back);
pickup = **code only**, constant-time compare, never returned by any read endpoint (the
code is disclosed once, in the `create_remittance` response). Single-company in-transit
account is resolved per company (passed in, or derived from a Liability leaf named like
remittance/in-transit/payable), leaving room for a cross-company due-to/due-from later.

**Endpoints:** `create_remittance` (now register-only; returns `remittance_id` +
`pickup_code`), `payout_remittance(remittance_id, pickup_code, payout_account, …)`,
`refund_remittance(remittance_id, reason?, …)`. `list_remittances`/`remittance_detail`
now surface a derived status (Registered / Paid Out / Refunded) and the linked stage
entries; neither returns the pickup code. Both guard against acting on an
already-paid-out/refunded transfer.

## Follow-up (frontend, not in this change)
- `NewRemittance.vue`: add the in-transit account selector; show the returned pickup code
  once on success. Add Payout and Refund actions on the transfer detail (payout collects
  the code + payout account).
- Installment collection UI: add a "Cancel (today)" action calling `cancel_collection`.
- `create_remittance` no longer needs `payout_account` at register (kept as an ignored
  optional param for back-compat); the payout account is chosen at payout time.

## Verify before deploy
- `python -m unittest stabler.tests.test_installment_cancel stabler.tests.test_company_scope_guard`
- `bench --site <site> migrate` (patches v32, v33 add the custom fields), then `bench build`.
