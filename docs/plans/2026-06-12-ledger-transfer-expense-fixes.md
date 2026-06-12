# Fix Pack — Ledger Rows, Transfer Multi-Currency, Expense Account Search

Date: 2026-06-12 · Source: prod screenshots (anjan). Three bugs + one blocking decision.

## F0 — BLOCKING INVESTIGATION: company base currency (run first)

Evidence that ANJAN company `default_currency = USD`: (a) UZS→UZS transfer trips ERPNext's
multi-currency validation (fires only when a leg ≠ company currency); (b) expense modal renders
"Эквивалент в базовой валюте … $"; (c) customer Lifetime Sales (base sum) renders "$356.33".
Verify: `SELECT name, default_currency FROM tabCompany;`

If USD → decision memo for Zafar + accountant (separate from this fix pack):
- **Option A**: keep USD base; enforce CBU-rate guards (per GL-integrity spec) on every UZS doc.
- **Option B (likely correct for a 99% UZS business)**: new Company with UZS base, opening-balance
  cutover at period boundary; ERPNext cannot change company currency once GL exists.
The fixes below are correct under either option — they do not wait for the decision.

## F1 — Customer/supplier ledger: one line per row, one row per voucher

Backend (`sales.py::_fetch_party_ledger_rows` consumers — customer + supplier ledgers):
1. **Aggregate by voucher**: group GL rows by (voucher_type, voucher_no, posting_date); sum
   debit/credit (base + account currency). PE allocations (1 row per against_voucher) collapse
   into a single ledger line. Allocation detail remains visible in the existing voucher drawer.
2. **`display_remark` built server-side**, one line:
   - if `remarks` matches ERPNext auto-blob (`^Amount [A-Z]{3} \d` or contains "received from"
     boilerplate) → `against {distinct against_voucher names, comma-joined, max 3 + "+N"}`
   - else user remark verbatim (first line only)
   - else against_voucher / against fallback (existing getRowRemark logic moves server-side).
Frontend: remark cell `text-truncate` with full text in `title=`; row max height one text line +
voucher line. Remove client-side getRowRemark.

Acceptance: PE-09541 case renders as ONE row, credit 360 000, remark
"against ACC-JV-2026-00025-1, ACC-SINV-2026-02720, ACC-SINV-2026-02964"; no row wraps; running
balance unchanged vs pre-fix sums (assert in test: aggregation preserves totals).

## F2 — Journal Entry builders: correct multi_currency flag

Rule: `multi_currency = 1` when **any** leg's `account_currency != company default_currency`
(not from≠to). Fix every JE builder in `money.py`:
- transfers (`:1594`) — current `from != to` comparison replaced;
- payments (`:1401`) — checks pay account only; apply same any-leg rule;
- expenses + any other `frappe.new_doc("Journal Entry")` call sites (grep sweep), incl.
  remittance (already 3-leg aware — verify its flag logic matches the rule).
Acceptance: UZS→UZS transfer of 1 сўм submits on anjan (regardless of base currency);
cross-currency transfer still submits; expense in UZS from UZS kassa submits.

## F3 — Searchable account selectors

Replace plain `Select` with `Typeahead` (substring, case-insensitive, diacritic-tolerant) for:
- expense line СЧЁТ (`Expenses.vue:628`) — searches expense accounts by any part of name,
  shows account name + currency suffix;
- sweep: any account/item/party picker rendered as `Select` with >20 options anywhere in money/
  expense/transfer/journal forms → Typeahead (list pages already comply).
Acceptance: typing "oshxo" finds "Oshxona Xarajatlari (UZS)"; keyboard navigation works;
five languages render.

## F4 — Cross-currency payments with effective exchange rate

Case: USD-billed customer paid from a UZS kassa, or UZS invoice settled from a USD account
(both directions, receive and pay, customer and supplier).

Backend (`money.py` payment endpoints — `payment_defaults_for_invoice`, `party_payment_defaults`,
`create_payment_for_invoice`, `create_payment_entry`):
1. Defaults response gains: `account_currency`, `party_currency` (invoice/party account ccy),
   `needs_exchange` flag, `effective_rate` = CBU rate for posting date (from the Currency
   Exchange table fed by the daily CBU sync — dependency on GL-integrity Phase G4), `rate_date`.
2. Create endpoints accept `exchange_rate`; validation: required when `needs_exchange`;
   must be within ±5% of CBU (outside → require `confirm_rate=1`, log deviation); rate ≤ sanity
   floor rejected (no more 1.0 cross-currency postings). Set PE `source_exchange_rate` /
   `target_exchange_rate` direction-aware; `paid_amount` in paying-account currency,
   `received_amount` = computed; allocation against the invoice stays in invoice currency.
3. FX settlement difference (invoice booked at rate R1, paid at R2) posts to the company's
   Exchange Gain/Loss account — ERPNext native; **verify `exchange_gain_loss_account` is set on
   each company**, throw a clear message if missing.

Frontend (`PaymentModal.vue` + `PartyPaymentModal.vue`):
- When `needs_exchange`: show rate row — "1 USD = 12 040 сўм · ЦБ 12.06.2026" (editable
  MoneyInput, prefilled with effective rate) + live two-sided preview: entering either side
  computes the other ("1 204 000 сўм → $100.00"). Amber warning when rate deviates >5% from CBU
  with explicit confirm.
- "Settle fully" button: computes paying-currency amount from outstanding × rate; sub-1-unit
  residual from rounding goes to FX gain/loss, not left as 0.01 outstanding.

Acceptance:
- $100 invoice paid 1 204 000 сўм at 12 040 → outstanding 0, JE balanced, FX diff (if booked
  rate differed) lands in Exchange Gain/Loss; mirrored direction (UZS invoice, USD account) works.
- Cross-currency PE without a rate → blocked with message; rate 1 → blocked.
- Rate row never shows for same-currency payments (zero UI change for the 99% UZS case).
- On-account party payment (no invoice) cross-currency works via PartyPaymentModal with same rate UX.

## F5 — Ledger shows ORIGINAL document amounts; FX legs as labeled lines

Rule (Zafar, global): every ledger row displays the source document's originally entered amount.
- Voucher aggregation (F1) must sum **allocation rows only**; party-tagged exchange-gain/loss /
  rounding rows belonging to the same voucher are excluded from the voucher's row and rendered as
  their own line: voucher link + label `t("Exchange difference")`, amount in its own row.
- PE row amount = `paid_amount`/`received_amount` (document value), cross-checked vs summed
  allocations (mismatch beyond the FX rows → log warning, show GL sum — never silently lie).
- Running balance must still foot to closing balance (FX lines included in the running sum) —
  assert in test with the PE-09541 fixture: row 360 000 + "Exchange difference" 121 → balance
  matches pre-fix closing exactly.
- Same treatment in supplier ledger. Note: these 121-type legs are artifacts of the F0 rate
  regime; expect their volume to collapse after the base-currency decision is executed.

## F6 — Balance vs Overdue divergence: surface unallocated credits + reconciliation

Cause (not a bug): payments/credits allocated against Journal Entries (e.g. opening-balance JVs)
or sitting on account don't reduce invoice `outstanding_amount`. Balance (net GL) and Overdue
(Σ outstanding of past-due invoices) legitimately diverge by the unallocated amount.
1. `customer_detail`/`supplier_detail` gain `unallocated_credit` = Σ outstanding-credit GL not
   tied to open invoices (= overdue+not-yet-due outstanding − net balance, floor 0).
2. KPI strip: when divergence > 0, third chip "Unallocated 3 260 121 сўм" with tooltip explaining
   the two metrics (i18n ×5).
3. New money-module surface **Reconciliation**: wraps ERPNext Payment Reconciliation
   (`erpnext.accounts.doctypes.payment_reconciliation` API) — pick party → list unallocated
   credits vs open invoices → match (FIFO suggestion) → submit. Accounts Manager role.
   This is the structural fix for tenants whose collections post against JVs.
4. Root-cause hygiene: PaymentModal defaults must allocate to **open invoices first** (oldest
   due first), never to JVs unless explicitly chosen — audit `create_payment_for_invoice` /
   party payment allocation order.

## Sequencing

F2 (one-line conditions — ship today, unblocks cashiers) → F3 (small) → F1+F5 (one PR — same
code path) → F4 (depends on CBU daily sync from GL-integrity Phase G; ship the sync first or
together) → F6 (reconciliation surface) → F0 memo to accountant in parallel.
Standard deploy; `.py` changes → bench restart; no migrate.
