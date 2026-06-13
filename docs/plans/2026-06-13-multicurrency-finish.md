# Multi-Currency Correctness — Finishing the Job

Date: 2026-06-13 · Follows `2026-06-12-multicurrency-gl-integrity.md` and the ledger fix pack.

## Where we actually are (audited 2026-06-13)

**DONE and deployed (better than originally specced):** the integrity guards run as doc-event
`validate` hooks — `validate_sales_invoice / validate_purchase_invoice / validate_payment_entry /
validate_journal_entry` in `_accounts.py`, registered in `hooks.py doc_events`. They fire on every
path (SPA, 1C sync, API), so `resolve_party_account` (per-currency AR/AP routing) and
`validate_exchange_rate` (hard floor USD→UZS > 1000, ±20% CBU band, 3-day staleness, 1:1-into-
foreign-account block) cannot be bypassed by entry point. CBU daily refresh is scheduled
(`tasks/cbu_rate_refresh.fetch_and_store`, real cbu.uz) and surfaced on Admin → Compliance →
ExchangeRates. **This stops all NEW corruption.**

**The catch:** guards prevent future mislabeling. They do **nothing** for GL rows posted *before*
the hooks existed — the historical wound (e.g. the customer whose UZS balance showed as "4 135 760 $")
is still on the books. And there is no monitor to catch a regression, no base-currency decision on
record, and the cross-currency payment UI is incomplete. Those four are this spec.

---

## R0 — Base-currency decision (BLOCKING, no code — answer first)
Run `SELECT name, default_currency FROM tabCompany;` per tenant. The whole repair shape depends on it.
- If ANJAN base = **UZS** (expected for a 99%-UZS business): repair is pure relabeling of misposted
  rows into correct per-currency accounts; proceed to R1.
- If base = **USD**: bigger decision (keep USD base + enforce rates everywhere, vs. new UZS-base
  company with opening-balance cutover — ERPNext can't change company currency once GL exists).
  Escalate to accountant before R1; the repair script differs.
Record the answer in this doc. **Do not run R1 until R0 is signed off.**

## R1 — Historical data repair (the unhealed wound)
Goal: move already-posted party balances out of wrong-currency accounts into the correct
per-currency AR/AP accounts, **preserving base-currency value exactly** (relabel, don't revalue).

Sequence (staging copy first, then prod, backup before each):
1. **Diagnose** — reuse the diagnostic SQL from the original GL-integrity spec (§2): D1 account
   currencies, D2 rows posted 1:1 into non-base accounts, D5 party-account bindings. Quantify the
   damage per account and per party; export to CSV for review.
2. **Create** correct per-currency accounts if missing (`Debtors (UZS)`, `Debtors (USD)`,
   `Creditors (UZS)`, `Creditors (USD)`) — account currency is immutable once posted to, so new
   accounts, not edits. Rebind Company defaults + Party Account rows.
3. **Repair script** `stabler/maintenance/fix_party_account_currency.py`, run via `bench execute`,
   **idempotent + `dry_run` default true**:
   - For each open item in a wrong-currency account, post a correcting Journal Entry
     (debit wrong / credit correct) carrying `party_type`, `party`, `against_voucher` per open
     invoice so reconciliation + aging stay intact. Never UPDATE GL rows in place (append-only).
   - Bulk/old balances → per-party transfer JEs; recent/few → prefer cancel-amend onto correct account.
   - Emit a results CSV (party, old acct, new acct, amount moved) for sign-off before `dry_run=false`.
4. **Disable** the emptied wrong-currency accounts.
5. **Verify**: D2 returns 0 rows; per-party base balance identical pre/post (assert in the script);
   AR/AP aging base totals unchanged. The repair moves labels, never value.

## R2 — Cross-currency payment UI (F4 frontend — backend validate already exists)
`validate_payment_entry` already enforces the rate server-side, but the payment modals don't
gather/show it (`PaymentModal.vue` / `PartyPaymentModal.vue` / `PaymentEntryForm.vue` have no
exchange-rate field — confirmed absent). Result: paying a USD invoice from a UZS account either
fails the guard with a cryptic message or can't be done in-SPA.
- Backend `payment_defaults_*` returns: `party_account_currency`, paying-account currency,
  `needs_exchange` flag, `effective_rate` (CBU for posting date), `rate_date`.
- Modal: when `needs_exchange`, show a rate row — "1 USD = 12 040 сўм · ЦБ {date}" (editable
  MoneyInput, prefilled effective rate) + live two-sided preview (enter either side → compute
  other). Amber warning when entered rate deviates >5% from CBU (server still hard-blocks >20%).
  Send `exchange_rate`; set source/target direction-aware. Same-currency payments: row hidden,
  zero change to the 99% UZS flow.
- Confirm each company has `exchange_gain_loss_account` set (FX settlement difference lands there);
  throw a clear message at payment time if missing.
- Acceptance: $100 invoice settled from UZS kassa at 12 040 → outstanding 0, JE balanced, FX diff
  to gain/loss; mirror direction works; cross-currency PE without rate blocked with a readable message.

## R3 — Integrity monitor (Phase M — catch regressions before customers do)
- `compliance.py::gl_integrity_scan(company)`: returns anomaly counts — (a) D2-style 1:1-into-
  foreign-account rows; (b) parties whose ledger spans >1 account currency; (c) cross-currency docs
  posted >5% off CBU that day; (d) any wrong-account-type party postings.
- Nightly scheduler job runs it per company; non-zero → red "GL integrity" card on Admin →
  Compliance + email to Accounts Manager.
- Acceptance: post-R1 the scan returns 0 on prod; a deliberately bad test posting (bypassing hooks
  via direct db) is detected on the next run.

---

## Sequencing
R0 (decision) → R2 + R3 (small, ship while R0 is being decided — both are forward-looking, safe) →
R1 (the repair, only after R0 sign-off, staging→prod with backups).

Rationale: R2/R3 don't depend on the base-currency answer and close the live UX gap (can't take a
cross-currency payment) plus give you eyes on the books. R1 is the high-care historical fix and
waits on the accountant. Guards already protect the present; this restores the past and watches the future.

## Out of scope
- Automatic period-end FX revaluation of genuinely-foreign accounts (native Exchange Rate
  Revaluation, separate effort; UZS accounts never revalue).
- Converting historical reporting aggregates (per-currency only, per standing rule).
