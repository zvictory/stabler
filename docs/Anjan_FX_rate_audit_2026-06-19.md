# Anjan — FX Rate Audit (2026-06-19)

**Status: REPORT ONLY — no data was modified.**  
Prepared automatically from a read-only `bench console` scan on `anjan.erpstable.com`.

---

## Summary

A full scan of all non-cancelled GL entries on UZS-currency accounts at the
USD-base company **Anjan** found **3 vouchers / 24 lines** where the booked base-
currency (USD) amount deviates from the expected CBU-rate equivalent by more than 5×.

| # | Voucher | Type | Date | Lines | сўм total | Booked USD | Expected USD (CBU) | **Base error** |
|---|---|---|---|--:|--:|--:|--:|--:|
| 1 | ACC-SINV-2026-10146 | Sales Invoice | 2026-06-11 | 1 | 4,135,760 | $4,135,760.00 | $343.10 | **+$4,135,416.90** |
| 2 | ACC-JV-2026-07002 | Journal Entry | 2026-05-19 | 3 | 19,200,000 | $5.34 | $1,597.43 | **−$1,592.09** |
| 3 | ACC-JV-2026-00023 | Journal Entry | 2026-03-29 | 20 | 154,645 | $45.39 | $12.70 | **+$32.69** |
| | **NET** | | | **24** | | | | **+$4,133,857.50** |

Net overstatement of the USD GL book: **+$4,133,857.50**, almost entirely driven by
item 1 (SINV with conversion_rate = 1).

---

## Findings per voucher

### 1. ACC-SINV-2026-10146 — Sales Invoice · 2026-06-11

**Root cause:** A UZS-denominated Sales Invoice was submitted with `conversion_rate = 1.0`.
For a USD-base company, Frappe computes `base = amount × conversion_rate`, so the
4,135,760 сўм grand total was recorded as **$4,135,760 USD** in the GL instead of
≈$343.10 at the correct CBU rate of ≈12,052 UZS/USD.

**Effect:** `Debtors UZS - A` debit side is overstated by **≈$4,135,417** in the USD
book. The сўм track is unaffected (4,135,760 is correct in account currency).

---

### 2. ACC-JV-2026-07002 — Journal Entry · 2026-05-19

**Root cause:** All 3 GL lines of this JE carry `ex_rate ≈ 2.78 × 10⁻⁷` instead of the
correct rate of ≈8.32 × 10⁻⁵ (~300× too small). This is likely a data-entry error where
the rate was entered in the wrong unit or field (e.g. 1/3,600,000 instead of 1/12,000).

**Lines affected:**

| Account | Direction | сўм | Booked USD | Correct USD |
|---|---|--:|--:|--:|
| Qurilish - A | Debit | 6,000,000 | $1.67 | $498.60 |
| PODDON - A | Debit | 3,600,000 | $1.00 | $299.16 |
| KASSA SUM - A | Credit | 9,600,000 | $2.67 | $798.26 |

**Effect:** KASSA SUM - A's USD book is understated by ≈$796. Qurilish - A and PODDON - A
are each understated proportionally. This is the discrepancy the user first noticed in the
KASSA SUM - A ledger view.

---

### 3. ACC-JV-2026-00023 — Journal Entry · 2026-03-29

**Root cause:** 20 GL lines with an implied rate ~3.5× off the CBU rate on that date.
The total сўм is 154,645 and the base error is only **+$32.69** — negligible in absolute
terms. Logged for completeness.

---

## Methodology

1. Fetched all non-cancelled GL rows where `account_currency = 'UZS'` (Anjan's UZS
   accounts), excluding zero-amount lines.
2. For each row, looked up the CBU USD→UZS rate in `Currency Exchange` using the
   "latest on/before posting_date" cursor-walk pattern (same as `_accounts.py:63`).
3. Computed `expected_usd = сўм_amount / cbu_rate`.
4. Flagged rows where `booked_usd / expected_usd > 5` or `< 0.2` (5× plausibility band).
5. Grouped flagged rows by voucher; sorted by absolute base error descending.

**Scan scope:** all UZS-account GL entries, company Anjan, `is_cancelled = 0`.
**CBU rate source:** `Currency Exchange` doctype, populated by `stabler/tasks/cbu_rate_refresh.py`.

---

## No data correction performed

This report is investigative only. No documents were cancelled, amended, or reposted.
Any remediation requires explicit separate authorization and should be performed by
an accountant or system administrator who can verify the correct rates and amounts.

---

## Suggested remediation (requires authorization)

### Item 1 — ACC-SINV-2026-10146
1. Open the Sales Invoice in ERPNext.
2. Cancel the submitted invoice.
3. Amend it and set `Conversion Rate` to the correct CBU USD→UZS rate for 2026-06-11
   (≈12,052 — verify from `Currency Exchange`).
4. Re-submit.

### Item 2 — ACC-JV-2026-07002
1. Open the Journal Entry in ERPNext.
2. Cancel it.
3. Re-create with the correct exchange rate (≈12,036 UZS/USD for 2026-05-19 — verify
   from `Currency Exchange`; the `ex_rate` field on each GL line should be ≈8.32 × 10⁻⁵).
4. Submit.

### Item 3 — ACC-JV-2026-00023
Low financial impact ($32.69). Decision to correct is at the accountant's discretion.

---

*Scan run: 2026-06-19. Bench: `/home/frappe/frappe-bench`. Site: `anjan.erpstable.com`.*
