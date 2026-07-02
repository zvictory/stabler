# Stabler API Security Audit — 2026-07-02

**Scope:** the whitelisted Python API surface (`@frappe.whitelist()` endpoints) across
`stabler/api/*` and `stabler/integrations/*`. ~430 whitelisted endpoints in ~45 files
were enumerated; the finance, HR/payroll, integration/guest, and admin/CRM/service
groups were deep-audited. **Read-only audit — no code was changed.**

**Reviewer's note on the threat model.** Per `CLAUDE.md`, the SPA module gate is a *UX*
layer; the real security boundary is Frappe's `has_permission` on every backend
endpoint. That backstop holds *only* where an endpoint routes reads/writes through
`frappe.get_doc` / `save()` / `has_permission` / the `_assert_can_read/_assert_can_write`
helpers in `stabler/api/_common.py`. It does **not** hold where an endpoint (a) runs raw
`frappe.db.sql` filtered by a caller-supplied `company` argument, or (b) loads a named
record after only a `frappe.db.exists` check. Those two patterns are the source of nearly
every finding below.

---

## How to read the severity ratings

Two independent boundaries are at stake:

1. **Authentication boundary** — is the caller logged in at all? Broken here = anyone on
   the internet. These findings are severe unconditionally.
2. **Company (tenant) boundary** — a logged-in user passing a `company` they shouldn't
   see. Exploitable **when a site hosts more than one Company, or a user's
   `allowed_companies` is a non-empty subset**. On a strictly single-company site with no
   restricted users, the blast radius is smaller — but the machinery for multiple
   companies and restricted users already exists (`Stabler User Company`,
   `_user_allowed_companies`, the HoreCa tenant), so this is a latent break that becomes
   live the moment a second company or a scoped user is added. Rated on that basis.

---

## Critical

### C1 — Guest badge login issues a full session from a low-entropy card UID
`stabler/api/manufacturing.py: badge_login` (L578, `allow_guest=True`)

`badge_login(uid)` is callable with **no authentication**. It matches `uid` against every
active Employee's `attendance_device_id` and, on a hit, calls
`LoginManager().login_as(emp.user_id)` — handing the caller a full authenticated Frappe
session as that employee. The match (`match_employee_badge` → `get_hashes`) accepts the
**plaintext** UID, its SHA256, or a SHA256 salted with a constant hard-coded in the source
(`salt = "stabler_rfid_salt"`, L520) — so the "salt" adds zero secret entropy. Card UIDs
are short, printed on the physical card, and enumerable. The only throttle is 5 failures
per **IP** per 5 minutes (`badge_login_fail:{ip}`), defeated by rotating source IPs and
irrelevant once a valid UID is known. Comparison is Python `in` (not constant-time).

*Exploit:* `POST /api/method/stabler.api.manufacturing.badge_login` with a guessed/observed
card number → logged in as that employee, no password.

*Fix:* this is an authentication primitive, not a webhook — it should not be
`allow_guest`. If kiosk badge login is a genuine requirement, gate it behind a device-level
shared secret / HMAC (a registered kiosk token in a request header), store only
UID hashes salted with a **per-site random secret** from `site_config.json` (never a
source constant), compare with `hmac.compare_digest`, and rate-limit **per-UID** with
lockout, not just per-IP.

### C2 — Guest PIN login is brute-forceable to a full session
`stabler/api/manufacturing.py: pin_login` (L627, `allow_guest=True`)

Same shape as C1: `pin_login(employee, pin)` takes an enumerable Employee name and a short
numeric PIN (the `:`-suffix of `attendance_device_id`), matched via the same constant-salt
hash set, and on success calls `login_as`. PINs are low-entropy and the throttle is again
per-IP only, so a distributed attacker sprays PINs across rotating IPs and obtains a
session. *Fix:* as C1 — remove `allow_guest` or require a kiosk secret plus strict
per-employee lockout with exponential backoff, per-site random salt, and constant-time
compare. A short PIN over an open guest endpoint cannot be the sole factor.

### C3 — Record IDOR: credit/debit notes against any tenant's invoice
`stabler/api/sales.py: create_sales_return` (L835) · `stabler/api/purchasing.py: create_purchase_return` (L1004)

Both guard the source document with only `frappe.db.exists(...)`, then
`frappe.get_doc(...)` and `make_return_doc(...)`, optionally **submitting** the resulting
return. No `_assert_can_read` / `has_permission` on the source. An authenticated user who
guesses (invoice names are sequential, e.g. `ACC-SINV-2026-#####`) can issue — and with
`submit=1`, post to the GL — a credit note against another company's Sales Invoice or a
debit note against another company's Purchase Invoice.

*Fix:* `_assert_can_read("Sales Invoice", sales_invoice)` (resp. `"Purchase Invoice"`)
immediately after the existence check, before `get_doc`.

### C4 — Cross-tenant money movement in the salary/advance payout endpoints
`stabler/api/salary_payment.py: pay_salaries` (L271), `accrue_payroll_period` (L118) · `stabler/api/employee_advance.py: pay_employee_advance` (L235)

These create and **submit** Journal / Bank / Payment Entries, taking `company` and (for
`pay_salaries`) `paid_from` directly from the caller. Guards are `_require_pay_role()` (a
**global**, non-company-scoped role) and `_require_company(company)` (existence check
only). There is **no `_assert_company_scope`**, and `paid_from` is not validated to belong
to `company`. A user holding a payroll role in one tenant can post payroll accruals and pay
out employees from another tenant's cash/bank account. The maker-checker approval engine
(`money.py`) enforces a second approver but **not** tenant isolation, so it does not close
this boundary. *Fix:* `_assert_company_scope(company)` at the top of each, and validate
`paid_from`/accounts belong to `company`.

### C5 — Cross-tenant stock movement / warehouse creation
`stabler/api/inventory.py: create_stock_entry` (L580), `create_warehouse` (L451)

`_require_company`-only on the header company; `create_stock_entry` posts (and can submit)
stock movements and `create_warehouse` creates a warehouse under an arbitrary company.
*Fix:* `_assert_company_scope(company)`; for stock entries also confirm every referenced
warehouse resolves to `company`.

---

## High

### H1 — ARCA payment webhook auto-submits attacker-shaped payments
`stabler/integrations/arca/webhook.py: handle_payment_webhook` (L54 → `_create_payment_entry` L126)

The HMAC-SHA256 signature check is **correctly implemented** (raw-body HMAC,
`hmac.compare_digest`, empty signature rejected, missing secret → 503) and does gate the
work — no bypass. The residual risk: once the signature passes, the handler creates and
**submits** a Payment Entry for an **attacker-chosen `sales_invoice` and `amount`** with
`ignore_permissions=True` and `pe.flags.ignore_approval_gate = True` (L139) — deliberately
skipping the maker-checker gate the rest of the app enforces — and never validates `amount`
against the invoice's outstanding. All GL-posting safety rests on the confidentiality of
`arca_webhook_secret`; if it leaks (shared vendor, log line, commit), an attacker mints
arbitrary payments and marks receivables paid. *Fix:* validate `amount` ≤ invoice
outstanding, restrict to the expected company/currency, and land these held-for-review
rather than auto-submitting.

### H2 — Systemic cross-company data leak on finance list/report/cockpit endpoints
`stabler/api/reports.py` (all 15 endpoints) · `stabler/api/money.py` (~14) · `stabler/api/sales.py` (~16) · `stabler/api/purchasing.py` (~10) · `stabler/api/inventory.py` (~13)

None of these files import `_assert_company_scope`. Each endpoint takes `company`, guards
only with `_require_company` (existence), and runs company-filtered GL/invoice/bill/stock
SQL — which also bypasses Frappe User-Permission row filters. A user in company A calls,
e.g., `money.gl_entries(company="B", ...)`, `reports.gross_margin_by_customer(company="B")`,
`sales.receivables_cockpit(company="B")`, or `purchasing.payables_cockpit(company="B")` and
reads B's general ledger, margins, receivables, and payables. *Fix (systemic):* add
`from stabler.api.approvals import _assert_company_scope` and call
`_assert_company_scope(company)` immediately after each `_require_company(company)`. For
`warehouse`-only endpoints, resolve `Warehouse.company` and scope-check that.

Representative highest-sensitivity endpoints: `money.gl_entries` / `chart_balances` /
`account_balance` / `list_payment_entries` / `list_bank_entries`; `sales.customer_ledger` /
`ar_aging` / `list_customers_with_balances` / `receivables_cockpit` / the six
`sales_report_*`; `purchasing.supplier_ledger` / `ap_aging` / `payables_cockpit`;
`reports.*` customer/supplier balance & margin reports; `inventory.stock_ledger` /
`item_valuation_history`.

### H3 — Cross-company PII/financial leak in HR salary & advance endpoints
`stabler/api/hr.py: list_salary_slips` (L1055) · `stabler/api/hr_pay.py` (all 5: `preview_payroll_pay` L133, `set_kpi_performance` L146, `set_advance_deduction` L173, `preview_payroll_period` L217, `payroll_xlsx` L252) · `stabler/api/salary_payment.py: accrue_employee_salary` (L168), `salary_payable_balances` (L231) · `stabler/api/employee_advance.py: employee_advance_balances` (L119), `employee_advance_detail` (L194) · `stabler/api/hr_finance.py: employee_financials` (L91), `employee_net_balances` (L222)

`hr_pay.py`, `salary_payment.py`, `employee_advance.py`, and `hr_finance.py` never import
`_assert_company_scope`. They gate on the global payroll role + `_require_company`, then read
per-employee gross/net pay, base salary, and outstanding advances (or mutate KPI/advance
figures that change pay) for any `company` passed in, via raw GL SQL that also bypasses
User-Permission filters. Any payroll-role user in one tenant reads or edits another tenant's
salary data. *Fix:* `_assert_company_scope(company)` after each `_require_company`; for the
`hr_pay.py` summary-name endpoints, scope-check the company resolved from the summary before
`get_doc`. (Note: `hr_payroll.py`, `hr_payroll_calc.py`, and `hr_corrections.py` **were**
retrofitted with `_assert_company_scope` and are clean — the fix pattern is already in the
codebase, just unevenly applied.)

### H4 — Missing company scope + record IDOR across the Service module
`stabler/api/service.py` (13 findings)

`_require_service(company)` enforces module visibility but not `_user_allowed_companies`, so
9 endpoints leak cross-company data when called with a foreign `company`
(`list_tickets` L218, `create_ticket` L289, `ticket_board_meta` L376 — also leaks the user
roster, `list_visits` L497, `calendar_feed` L555, `map_feed` L687 — leaks outlet
GPS/addresses, `unbilled_visits` L896, `list_equipment` L944, `dashboard_summary` L1043).
Three are record IDORs: `create_invoice_from_visit` (L812) and
`create_material_issue_from_visit` (L851) load a caller-named Maintenance Visit behind only
`frappe.db.exists` and generate a **submitted** Sales Invoice / Stock Entry;
`equipment_detail` (L998) reads any `Serial No` by enumeration. `assign_ticket` (L351) lets
any Service-role user assign arbitrary users with no manager gate. *Fix:* wire
`_assert_company_scope` into `_require_service` (closes all 9 at once), add
`_assert_can_write`/`_assert_can_read` to the three IDOR paths, and gate `assign_ticket`.

### H5 — Cross-company financial leak in CRM analytics
`stabler/api/crm.py: crm_analytics` (L427), `crm_report` (L512), `crm_metrics` (L381)

These aggregate `CRM Deal` joined to `Sales Invoice` with no company filter, leaking
lifetime sales, invoice totals, and freezer-asset costs across all tenants to any CRM-module
user. (Named-record CRM reads and all CRM SQL params are otherwise correctly guarded/
parametrized.) *Fix:* scope the deal/customer selection to `_user_allowed_companies` and add
`AND company IN %(companies)s` to the invoice aggregates.

---

## Medium

### M1 — Non-constant-time secret comparison on payment webhooks
`stabler/integrations/uzpay/click.py` (L146, MD5 `sign_string` compared with `==`) ·
`stabler/integrations/uzpay/uzum.py` (L207) and `payme.py` (L272) (Basic-auth secret
compared with `!=`/`==`)

Each check *does* run before any handler work (so these are not open bypasses — hence
Medium), but the digest/secret comparisons are not constant-time, leaking a timing side
channel on the shared secret. The MD5 scheme in Click is provider-mandated. *Fix:* use
`hmac.compare_digest` for all three. `payme.GetStatement` (L225) additionally returns
site-wide Payme session history unscoped by company behind that Basic-auth — scope it to the
merchant/company if a site hosts multiple.

### M2 — `create_payroll_entry` runs payroll for any company with no role gate
`stabler/api/hr.py: create_payroll_entry` (L1130) — `_require_company` only; generate/submit
slips for any company. *Fix:* `_assert_company_scope` + payroll-role gate.

### M3 — Intake-lead token travels in the URL/body
`stabler/integrations/intake/lead.py: intake_lead` (L62) — the `_check_token` comparison is
correct constant-time and rejects empty tokens (not bypassable), but the shared token is
passed as a request parameter, so it lands in access logs / referer / history. *Fix:* accept
it via an `Authorization`/custom header.

---

## Low / informational

- **`hr.py` attendance & leave endpoints** (`list_attendance`, `attendance_matrix`,
  `mark_attendance`, `set_attendance`, `get_attendance_cell`, `bulk_set_attendance`,
  `clear_attendance`, `attendance_matrix_xlsx`, `list_leave_applications`,
  `create_leave_application`, `hr_overview`, `create_employee`, `list_employees`) — missing
  company scope; roster/attendance metadata rather than money. Add `_assert_company_scope`.
- **`sfa.py: bulk_set_outlet_gps`** (L199) writes via `frappe.db.set_value` (skips
  per-record `has_permission`) but is confined by `_company_filter` to the caller's own
  company — Low. `check_in`/`check_out` (L411/L442) are effectively bound by
  `_company_filter` + owner check + `save()`; adding `_assert_can_write` is defense-in-depth.
- **No SQL injection found.** The f-string SQL in `crm.py`, `money.py`, and
  `reconcile_api.py` interpolates only **static, server-chosen** fragments (column names,
  fixed WHERE literals); every user value is a `%(name)s` bind parameter. Not exploitable.
- **Clean modules (0 findings):** `admin.py`, `organization.py`, `backup.py`, `export.py`,
  `access_review.py`, `approvals.py`. Every privileged mutator — user/role/permission
  management (`set_user_allowed_companies`, `set_user_allowed_modules`,
  `update_company_modules`, `apply_role_template`, `reset_password`), backups, and exports —
  is `_require_admin()`-gated on line 1, with SoD checks on role changes and path-traversal
  guards on backup filenames. **No privilege-escalation path was found.** The bank-statement
  import/reconcile APIs are login + module + `has_permission` + IDOR guarded. The timepay
  `manual_sync`/`manual_process` endpoints reject Guest and check `has_permission`.

---

## Systemic root cause & recommended remediation order

The overwhelming majority of findings are **one bug repeated**: `_require_company()` checks
only that a company *exists*, and many files never adopted the `_assert_company_scope()`
helper that already exists in `approvals.py` and is already used correctly in
`approvals.py`, `hr_payroll.py`, `hr_payroll_calc.py`, `hr_corrections.py`, `sfa.py`, `pos.py`,
`search.py`, `bpm.py`, `audit.py`, and `bank_statement/import_api.py`. The fix is mechanical
and consistent.

Suggested order:

1. **C1/C2 (guest auth)** — highest impact, unconditional. Remove `allow_guest` from
   `badge_login`/`pin_login` or re-architect behind a per-site kiosk secret. Do this first.
2. **C3/C5 record IDORs** (`create_sales_return`, `create_purchase_return`,
   `create_stock_entry`, `create_warehouse`, service `*_from_visit`, `equipment_detail`) —
   add `_assert_can_read`/`_assert_can_write` on the source record; exploitable regardless of
   company count.
3. **C4 + H2/H3/H4/H5 company scope** — add `_assert_company_scope(company)` after every
   `_require_company(company)` across `reports.py`, `money.py`, `sales.py`, `purchasing.py`,
   `inventory.py`, `hr.py`, `hr_pay.py`, `salary_payment.py`, `employee_advance.py`,
   `hr_finance.py`, and wire it into `service._require_service` and `crm` aggregates. Also
   validate that `paid_from`/accounts/warehouses belong to `company` on the write paths.
4. **H1** — add amount-vs-invoice validation and reconsider the auto-submit/approval-gate
   bypass in the ARCA handler.
5. **M1–M3** — swap the three uzpay comparisons to `hmac.compare_digest`; move the intake
   token to a header.

**Suggested regression guard:** add a test that asserts every `@frappe.whitelist()` function
taking a `company` parameter calls `_assert_company_scope` (AST scan), and a review checklist
item rejecting new `_require_company`-without-`_assert_company_scope` and
`frappe.db.exists`-without-`_assert_can_read` patterns — mirroring the existing striped-table
and bare-`<input type="date">` review rules in `CLAUDE.md`.

---

## Remediation applied — 2026-07-02 (PR 1: unconditional Criticals)

Fixed in this pass (the findings exploitable regardless of company count, plus C4):

- **C1/C2 — kiosk guest auth** (`manufacturing.py`): `badge_login`/`pin_login` now call
  `_verify_kiosk_token()` first — a device-level shared secret read from
  `site_config.json` (`stabler_kiosk_token`) and sent by the kiosk in the
  `X-Stabler-Kiosk-Token` **header** (not a body/query param, so it isn't logged),
  compared with `hmac.compare_digest`, failing **closed** if unset. The hard-coded source
  salt is replaced by a per-site salt (`_kiosk_salt()` → `site_config.stabler_rfid_salt`,
  legacy constant kept only as a fallback so existing badge records still match). Added
  per-UID and per-employee lockout alongside the existing per-IP throttle.
- **C3 — return IDORs**: `_assert_can_read(...)` added on the source invoice in
  `sales.create_sales_return` and `purchasing.create_purchase_return`.
- **C4 — payout tenant isolation**: `_assert_company_scope(company)` added after every
  `_require_company` in `salary_payment.py` (6 sites) and `employee_advance.py` (5 sites).
- **C5 — inventory writes**: `_assert_company_scope(company)` added to
  `inventory.create_warehouse` and `create_stock_entry`.

All six touched files pass `python -m py_compile`; no new import cycles.

> **⚠ Deployment requirement (breaking):** kiosk badge/PIN login now **fails closed**. Before
> deploying, set on every site that uses the kiosk (`bench --site <site> set-config`):
> `stabler_kiosk_token` (a long random string, also configured on the kiosk device/header)
> and, recommended, a random `stabler_rfid_salt`. Without `stabler_kiosk_token`, `badge_login`
> and `pin_login` return "Kiosk login is not configured on this site."

## Remediation applied — 2026-07-02 (PR 2: company-scope sweep + webhook hardening)

- **H2/H3 + the wider class — company scope everywhere**: `_assert_company_scope(company)`
  is now called on **every** whitelisted endpoint that accepts a `company` argument. This
  went beyond the originally-audited files: a full AST scan surfaced 47 more such endpoints
  in modules the deep-audit hadn't individually covered (`installment`, `remittance`, `pos`,
  `fx_revaluation`, `budget`, `dashboard`, `tender`, `hr_attendance`, `hr_calendar`,
  `hr_overview`, `manufacturing`, and the bank-statement import/reconcile APIs) — several of
  them money-movement paths — and those were closed too. The guard is a no-op for admins and
  unrestricted users, so behavior is unchanged for the default single-company setup.
- **H4 — Service module**: one change to `service._require_service` now calls
  `_assert_company_scope`, covering all 19 Service endpoints at once; added
  `_assert_can_read("Maintenance Visit", …)` to the two `*_from_visit` builders.
- **H5 — CRM aggregates**: `crm_metrics` / `crm_analytics` / `crm_report` now filter
  `CRM Deal` (and the joined `Sales Invoice` aggregates) by the caller's allowed companies.
- **H1 — ARCA webhook**: `_create_payment_entry` now rejects a non-submitted invoice, a
  non-positive `amount`, or an `amount` exceeding the invoice's `outstanding_amount`
  (0.01 tolerance) before creating the Payment Entry.
- **M1/M2 — uzpay**: the MD5 sign compare (`click.py`) and the Basic-auth secret compares
  (`uzum.py`, `payme.py`) now use `hmac.compare_digest`.
- **Regression guard**: `stabler/tests/test_company_scope_guard.py` statically asserts (via
  `ast`, no Frappe runtime) that every whitelisted `company`-taking endpoint enforces a
  scope guard. It currently passes with **zero** violations; any new unscoped endpoint fails
  the suite. This is the automated form of the CLAUDE.md review rule.

All touched files pass `python -m py_compile`; the regression test passes.

### Also closed (M3)
- **`intake_lead`**: now reads the shared secret from the `X-Intake-Token` header
  (kept out of logs/referer/history), falling back to the body param for existing callers.
- **`payme.GetStatement`**: confines the statement to `site_config.payme_company` when set
  (opt-in, so single-merchant sites are unaffected). `POS Payment Session` carries a
  `company` field, making this a clean filter.

### Accepted as-is (documented, no change)
- **`sfa.bulk_set_outlet_gps`** (Low): already role-gated (`_require_write`) and
  `_company_filter(company)`-scoped, and the outlet set is fetched with
  `filters={"company": company}`, so a write can only ever touch the caller's own permitted
  company — cross-company mutation is structurally impossible. Per-record `has_permission`
  on up to 5,000 rows was judged not worth the cost. No Critical/High/Medium items remain.

*Prepared from a read-only static review. No exploit was executed against any live site.
Line numbers reflect the working tree at audit time and may drift.*
