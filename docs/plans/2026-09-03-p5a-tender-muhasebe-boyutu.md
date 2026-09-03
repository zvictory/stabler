# P5a — Tender accounting dimension (ADR-609, slice A: schema, writers, guards)

Frozen contract, 2026-09-03 (evening). Branch `feat/adr-609-tender-dimension`.
Decision record: `docs/plans/2026-09-03-tender-ve-is-emri-tasarim-denetimi-tasarim-kurulu-karari.md`
§8 (ADR-609, all five questions decided by Zafar). Slice B (P5b: GL-based tender P&L with
reconciliation against `_actual_block`, and the charge-type → expense-account mapping) is a
separate contract that opens after P5a is merged and the test site is migrated.

Everything below marked *measured* was read from the code or the test site on 2026-09-03.
Implement the contract literally; where the code contradicts a line here, stop and report
the measurement instead of inventing behaviour.

## Objective and business reason

Every profit-and-loss posting of a tender-enabled company must be attributed, at the
General Ledger level, to exactly one tender or to general overhead ("GENEL GİDER"). That is
QuickBooks "Class" in ERPNext terms: an **Accounting Dimension**. Today the tender link is a
document-level custom field (`custom_crm_deal`) that never reaches the ledger, so the tender
P&L is assembled from documents and misses PI-borne costs, COGS and untagged journal entries.
P5a puts the dimension in place, fills it from every writer Stabler owns, and guarantees no
P&L row on a tender company is left unattributed. P5b reads it.

## Owner tenant and owner module

Module `tender` — per-company flag `enable_tender` on `Stabler Company Modules`, read through
`module_map_for(company)` (`stabler/stabler/doctype/stabler_settings/stabler_settings.py:230`);
user gate `_can_access_module(user, "tender")` (`stabler/api/organization.py`, already imported
by `stabler/api/tender.py`). The tender flow runs on mikas. **Never branch on a tenant or site
name; gate on the company flag.** A company without the flag must see zero behaviour change:
no dimension detail row, no defaulting, no mandatory check, GL rows byte-identical.

## Current architecture (measured)

- Stabler uses no Accounting Dimension anywhere (grep empty); the test site has none.
- `custom_crm_deal` (Link → CRM Deal) exists on Sales Order (patch v28), Purchase Order (v34),
  Supplier Quotation (v30), Request for Quotation (v68), Journal Entry **parent** (v52),
  Customs Declaration / Freight Booking / Import Container (v81), Proforma Invoice. It does
  NOT exist on Sales Invoice, Delivery Note, Purchase Invoice (`has_column` false on the test
  site).
- CRM Deal custom fields (test site): `company` (Link Company), `deal_type` (Select
  `Standard\nTender`, default Standard — created by `stabler/patches/v60_crm_daily_work.py:15-19`),
  `custom_tender_stage` (Select ``/seen/go/sourcing/priced/submitted/won/lost`),
  `custom_parent_tender` (Link Tender Master), `custom_tender_intake`, `custom_bid_pricing`.
  `status` is a Link to `CRM Deal Status` (rows: Qualification pos 1 type Open, …, Won pos 6,
  Lost pos 7). CRM Deal `title_field = organization`, so a Link shows the organization.
- ERPNext 16 `Accounting Dimension`: autoname `field:label`; `validate_doctype`
  (`accounting_dimension.py:48-69`) forbids core doctypes, Project, Cost Center, Company,
  Account, Finance Book and a second dimension on the same `document_type` — CRM Deal is
  allowed. `on_update` (`:85-91`) creates the Link custom fields synchronously **only under
  `frappe.in_test`**; otherwise it `frappe.enqueue`s `make_dimension_in_accounting_doctypes`
  after commit. **A patch must call `make_dimension_in_accounting_doctypes(doc=dim)` itself**
  (`:107-141`; idempotent — it skips a fieldname the doctype meta already has, and clears the
  meta cache per doctype). Fields land on the 52 doctypes of the `accounting_dimension_doctypes`
  hook (GL Entry, Sales Invoice, Purchase Invoice, Purchase Order, Sales Order, Delivery Note,
  Purchase Receipt, Supplier Quotation, Request for Quotation, Stock Entry, Landed Cost Item,
  Journal Entry **Account**, and their item tables, among others). The Journal Entry PARENT is
  not in the list; its account rows are.
- Mandatory check: `erpnext/accounts/doctype/gl_entry/gl_entry.py:188-215
  validate_dimensions_for_pl_and_bs`, called from `GLEntry.validate` (`:101`): for a row on a
  `Profit and Loss` account of a company whose `Accounting Dimension Detail` has
  `mandatory_for_pl`, throws when the row's field is empty (skips `is_cancelled`). It reads
  `get_checks_for_pl_and_bs_accounts()` (`accounting_dimension.py:253-260`, plain SQL, not
  cached). `default_dimension` is applied server-side ONLY to the round-off GL row
  (`erpnext/accounts/general_ledger.py:635-645`); nothing else defaults it — the SPA and the
  hooks below must.
- GL rows are inserted one by one as documents: `general_ledger.py:426-434 make_entry` →
  `frappe.new_doc("GL Entry")`, `update(args)`, `submit()`. So `doc_events` on `GL Entry` fire,
  and `before_validate` runs before `validate` (Frappe `run_before_save_methods` calls
  `before_validate` for both the save and the submit action).
- Dimension values reach the GL row from the voucher: `erpnext/controllers/accounts_controller.py
  :1337-1345 get_gl_dict` copies `self.get(fieldname)` and, when an item row is passed and has
  a value, `item.get(fieldname)`. Journal Entry builds its GL map row by row from `Journal
  Entry Account`.
- Mappers copy same-named fields that are not `no_copy`: SO→DN `field_no_map`
  `["payment_terms_template"]` (`sales_order.py:1460`), SO→SI (`:1455-1465`), PO→PI
  (`purchase_order.py make_purchase_invoice`, no parent `field_no_map`). The dimension custom
  fields are created without `no_copy`, so the mappers carry `tender` along. Stabler builds SI
  from SO through ERPNext's `make_sales_invoice` (`stabler/api/sales.py:2275`); direct SIs
  without an SO at `sales.py:1979`, `sales.py:2467`, `stabler/api/pos.py:300`,
  `stabler/api/service.py:833`; DNs come only from ERPNext's `make_delivery_note`
  (`stabler/maintenance/backfill_so_delivery.py:265`, `backfill_so_forced.py:80`; no
  `new_doc("Delivery Note")` in `stabler/api`). PI from PO: `stabler/api/purchasing.py:2274
  create_purchase_invoice_from_po` (ERPNext mapper); from PR `:2668`.
- Expenses form: `stabler/public/js/pages/money/Expenses.vue` — `tenderOn` (`:32`,
  `session.canAccessModule("tender")`), Typeahead picker (`:475-507`: `searchDeals` →
  `stabler.api.crm.list_deals`, `pickDeal`, `clearDeal`, `loadDealLabel` →
  `stabler.api.crm.get_deal`), form field `deal`. Server: `stabler/api/money.py:3213
  submit_expense_entry(company, posting_date, payment_from, lines, ..., deal=None, ...)`;
  `:3359-3366` validates only `frappe.db.exists("CRM Deal", deal)` and sets
  `doc.custom_crm_deal`.
- Purchase Invoice form: `stabler/public/js/pages/purchasing/PurchaseInvoiceForm.vue`
  (imports `Typeahead` `:20`, `MoneyInput` `:13`, `DateInput` `:14`, `useSession` `:5`; no
  tender or PO reference today). Server: `purchasing.py:1374 create_purchase_invoice(...)`,
  `:1459 update_purchase_invoice(...)`, `:1264 _apply_invoice_payload(doc, cleaned, ...)`,
  `:728 purchase_invoice_detail(name)` (items carry `purchase_order`, `:51`).
- `list_deals` (`stabler/api/crm.py:370`; args `company, search, status, deal_owner,
  deal_type, page_length, start`) → `_crm_list` (`crm.py:187`; `filters = {"company":
  company}` plus status / owner / `extra_filters`; three callers). Tender boards enumerate
  deals through SO `custom_crm_deal` and through `custom_tender_intake` /
  `custom_bid_pricing` / `custom_parent_tender` "is set" (`tender.py:2313-2320`) and
  `deal_type = "Tender"` (`tender.py:2325`, `stabler/api/tender_master.py:451`).
- `stabler/hooks.py doc_events` blocks exist for CRM Deal, Sales Invoice, Purchase Invoice
  (`:172`), Purchase Order (`:187`), Sales Order (`:197`), Delivery Note (`:214`), Purchase
  Receipt (`:233`), Journal Entry (`:269`); none for GL Entry, Supplier Quotation, Request for
  Quotation, Stabler Company Modules. `stabler_company_modules.py` has no controller methods.
- Patch conventions: `stabler/patches/v<N>_<topic>.py` + a line in `stabler/patches.txt` (last:
  `stabler.patches.v102_work_order_multi_level_bom_default`); `patches.txt` carries a
  `[post_model_sync]` marker at line 41 (measured 2026-09-03; the first draft of this
  contract said "NO marker", copied unmeasured from the orchestrator skill — see Log);
  v103 is appended below it and runs after the doctype sync — guard anyway with
  `frappe.db.has_column` / `frappe.db.exists`; idempotent; the docstring states WHY with
  measurements (read `v102_work_order_multi_level_bom_default.py` for the style). Patch tests:
  a frappe-free source-reading module (`stabler/tests/test_crm_deal_company_scope_patch.py`)
  plus bench behaviour tests.
- Test site `genesis-test.local`: one Company `_Test Company` (abbr `_TC`, UZS) with
  `enable_tender 1`, `enable_money 1`, `enable_purchasing 1`, `enable_crm 0`; 552 CRM Deals
  (551 Standard, 1 Tender, all status Qualification); zero rows carrying `custom_crm_deal` in
  Sales Order, Purchase Order, Journal Entry.

## Files to inspect first (read before writing)

`stabler/api/money.py:3213-3420`, `stabler/api/purchasing.py:728-830, 1264-1300, 1374-1530,
2274-2300`, `stabler/api/crm.py:187-260, 370-430`, `stabler/api/tender.py:1-120, 2300-2330`,
`stabler/api/tender_master.py:400-460`, `stabler/hooks.py:120-330`,
`stabler/stabler/doctype/stabler_settings/stabler_settings.py:200-260`,
`stabler/patches/v52_je_tender_deal.py`, `v60_crm_daily_work.py`, `v102_...py`,
`stabler/tests/test_crm_deal_company_scope_patch.py`, `stabler/tests/test_money_je_guards.py`,
`stabler/tests/test_tender_prewin_landed_bench.py` (IntegrationTestCase fixture style:
`_Test Company`, warehouses `Stores - _TC`), `stabler/public/js/pages/money/Expenses.vue:1-60,
150-210, 470-520, 600-700`, `stabler/public/js/pages/purchasing/PurchaseInvoiceForm.vue`,
`stabler/public/js/tests/landedChargeTypes.spec.js` (source-reading spec style, `code_only`
stripper), `.github/frappe-free-tests.txt`, ERPNext `accounting_dimension.py:40-141, 253-262`,
`gl_entry.py:83-215`, `general_ledger.py:420-445, 600-650`, `accounts_controller.py:1296-1350`.

## Allowed files

- new `stabler/patches/v103_tender_accounting_dimension.py`; one line in `stabler/patches.txt`
- new `stabler/api/tender_dimension.py` — ALL P5a server logic lives here: fieldname helper,
  overhead-deal helper, active-tender rule, the document hook, the GL hook, the company-modules
  hook, the backfill functions the patch calls
- `stabler/hooks.py` — `doc_events` additions only
- `stabler/api/crm.py` — `list_deals` gains `active_tenders`; `_crm_list` excludes Overhead
- `stabler/api/money.py` — `submit_expense_entry`: the `deal` check
- `stabler/api/purchasing.py` — `create_purchase_invoice`, `update_purchase_invoice`,
  `_apply_invoice_payload`, `purchase_invoice_detail`
- `stabler/public/js/pages/money/Expenses.vue`, `stabler/public/js/pages/purchasing/PurchaseInvoiceForm.vue`
- tests: `stabler/tests/test_tender_dimension.py` (frappe-free), `stabler/tests/test_tender_dimension_bench.py`
  (bench), `stabler/public/js/tests/tenderDimension.spec.js`; `.github/frappe-free-tests.txt`
- translations: `stabler/translations/{en,ru,uz,uzc,tr}.csv`

Forbidden / out of scope: `stabler/api/lcv.py`, `stabler/stabler/imports_module/lcv_math.py`,
`stabler/api/_landed*.py`, the P&L code in `tender.py` (`_actual_block`, `_deal_revenue_actual`,
`_deal_kassa_actual` — P5b), any doctype JSON, `stabler_company_modules.json`, any Desk link
(`/app/...`), tenant-name branching, deploy scripts, production, SSH, `bench migrate`, any
other patch file, `git merge`/`push`/history rewriting. Do not touch Stock Entry, Landed Cost
Voucher, Payment Entry or Expense Claim writers — the GL hook (B5) is their safety net in P5a.

## Backend behaviour

### B1 — Names and helpers (`stabler/api/tender_dimension.py`)

- `DIMENSION_LABEL = "Tender"`, `DIMENSION_DOCTYPE = "CRM Deal"`, `OVERHEAD_DEAL_TYPE = "Overhead"`,
  `OVERHEAD_ORGANIZATION = "GENEL GİDER"`.
- `dimension_fieldname() -> str | None`: the `fieldname` of the enabled Accounting Dimension
  whose `document_type` is CRM Deal (`frappe.db.get_value("Accounting Dimension",
  {"document_type": "CRM Deal", "disabled": 0}, "fieldname")`), cached per request in
  `frappe.local`; `None` when there is no such dimension. **No other module may hardcode
  `"tender"`** — every reader and writer goes through this helper, so a site whose dimension
  was created by hand under another fieldname keeps working.
- `tender_enabled(company) -> bool`: `bool(module_map_for(company).get("tender"))`, the
  existing rule (`kassa/bot.py:210-216`).
- `overhead_deal(company, create=False) -> str | None`: the CRM Deal with
  `{"company": company, "deal_type": "Overhead"}` (query, never a hardcoded name). With
  `create=True` and none found: insert `{"doctype": "CRM Deal", "organization": "GENEL GİDER",
  "deal_type": "Overhead", "company": company, "status": <the CRM Deal Status with the lowest
  position>, "deal_owner": "Administrator"}` with `flags.ignore_permissions = 1` and
  `insert(ignore_mandatory=True)`; leave every tender field empty. Exactly one per company.
- `ensure_company_setup(company)`: when `tender_enabled(company)` and the dimension exists:
  the overhead deal (create) and an `Accounting Dimension Detail` row for the company on the
  dimension with `reference_document "CRM Deal"`, `mandatory_for_pl 1`, `mandatory_for_bs 0`,
  `default_dimension` = the overhead deal. Existing row: fill `default_dimension` if empty;
  never turn `mandatory_for_pl` off. Returns what it created (dict of booleans) for the log.

### B2 — Patch `v103_tender_accounting_dimension.execute()` (idempotent on every site)

1. `deal_type` on CRM Deal (only if `has_column("CRM Deal", "deal_type")`): if the Custom
   Field's `options` lack `Overhead`, set them to `Standard\nTender\nOverhead` and
   `frappe.clear_cache(doctype="CRM Deal")`; backfill `deal_type = 'Standard'` where NULL or ''
   (raw SQL, no doc events, `update_modified` semantics not needed for SQL).
2. If NO company on the site has `tender_enabled`, stop here (log it). The dimension and its
   52 Link fields are created only where a tender company exists — a non-tender tenant gets
   no new fields on its forms.
3. Dimension: if `frappe.db.exists("Accounting Dimension", {"document_type": "CRM Deal"})`
   reuse it; else insert `{"doctype": "Accounting Dimension", "document_type": "CRM Deal",
   "label": "Tender", "fieldname": "tender"}` with `ignore_permissions`. Then call
   `make_dimension_in_accounting_doctypes(doc=dim)` DIRECTLY (import from
   `erpnext.accounts.doctype.accounting_dimension.accounting_dimension`) — measured: outside
   tests the model only enqueues. Afterwards assert `frappe.get_meta("GL Entry",
   cached=False).has_field(fieldname)` and the same for `Journal Entry Account`, `Sales
   Invoice`, `Purchase Invoice`, `Sales Order`, `Purchase Order`; if any is missing,
   `frappe.throw` — a patch that half-installs must fail loudly, not print OK.
4. `ensure_company_setup(company)` for every tender-enabled company.
5. Backfill (B6).
6. Log counts per step with `frappe.logger("stabler").info(...)` AND `print` (patch output
   is what the deploy reads). A second run must report zeros everywhere.

### B3 — Active-tender rule

`is_active_tender(deal, company) -> bool`: the deal exists, its `company` equals `company`,
`deal_type == "Tender"`, `custom_tender_stage != "lost"`, and NOT (stage `== "won"` AND at
least one submitted Sales Order with `custom_crm_deal = deal` exists AND every such SO has
`status in ("Closed", "Cancelled")`). This mirrors the board, which hides Closed/Cancelled
SOs (`tender.py:139`). The overhead deal is never an "active tender" but is always an
acceptable value.

`assert_selectable_tender(deal, company)`: passes when `deal` is the company's overhead deal
or `is_active_tender`; else `frappe.throw(_("Only an active tender or GENEL GİDER can be
selected."))`. Used by every writer below. Existing documents carrying an inactive tender are
never re-validated on read or on unrelated saves — the check runs only when the caller SENDS
a value that differs from what the document already holds.

`list_deals(..., active_tenders=0)` (`crm.py`): when `1`, requires the tender module
(`_require_crm_or_tender` already runs; add `tender_enabled(company)` or throw), ignores
`status`/`deal_type`/`deal_owner`, and returns `deals` = the overhead deal first (with
`is_overhead: 1`, `organization: "GENEL GİDER"`) followed by active tenders (same row shape as
today; `search` applies to `organization`/`lead_name`). Page size as today.

`_crm_list` (`crm.py:187`): when `doctype == "CRM Deal"` and `has_column("CRM Deal",
"deal_type")` and the caller's `extra_filters` carry no `deal_type`, add `filters["deal_type"]
= ["!=", "Overhead"]`. (Step 1 of the patch guarantees no NULL `deal_type`, which `!=` would
otherwise drop.)

### B4 — Document hook `stamp_tender(doc, method=None)` — `before_validate`

Registered in `hooks.py doc_events` for: Sales Order, Purchase Order, Supplier Quotation,
Request for Quotation, Journal Entry, Sales Invoice, Purchase Invoice, Delivery Note,
Purchase Receipt (append to the existing `before_validate` lists AFTER the desk-write guard
where one exists; new blocks for SQ, RFQ). Rules, in order, never overwriting a non-empty
value and never writing the overhead deal at document level:

1. Return immediately unless `tender_enabled(doc.company)` and `dimension_fieldname()` is set
   and `frappe.get_meta(doc.doctype).has_field(fieldname)` (parent) or the item table has it.
2. Parent value: if empty and the doctype has `custom_crm_deal` with a value → copy it.
   If still empty and the document has item rows linking a source (`sales_order` on SI/DN
   items — DN items use `against_sales_order`; `purchase_order` on PI/PR items) and the
   non-empty tender values of those sources (the source's own dimension field, else its
   `custom_crm_deal`) all agree → copy that one value. If they disagree, leave the parent
   empty and stamp rows individually.
3. Item rows (when the item table has the field): a row lacking the value gets the parent's
   value, else its own linked source's value.
4. Journal Entry: rows (`accounts`) lacking the value get the parent's `custom_crm_deal`.
5. Any lookup of a source document is cached per request (`frappe.local`), at most one read
   per source name.

### B5 — GL hook `default_gl_tender(doc, method=None)` — `before_validate` on GL Entry

Only when `tender_enabled(doc.company)`, the fieldname exists, the row's field is empty,
`not doc.is_cancelled`, and `frappe.get_cached_value("Account", doc.account, "report_type")
== "Profit and Loss"`:
1. the voucher parent's field value (`frappe.db.get_value(doc.voucher_type, doc.voucher_no,
   fieldname)` when that doctype has the field), else
2. the single non-empty value across the voucher's item rows when the voucher's item table
   has the field (unique only; several distinct values → skip to 3), else
3. `overhead_deal(doc.company)`; if it does not exist,
   `frappe.throw(_("GENEL GİDER deal is missing for {0}; save Stabler Company Modules or run
   patch v103.").format(doc.company))` — never create a CRM Deal inside a GL transaction.
Cache voucher lookups per request. Balance-sheet rows are left alone (decision 2).

### B6 — Backfill (called by the patch; tender-enabled companies only; idempotent; raw SQL;
no doc events; `modified` untouched)

- Sales Order, Purchase Order, Supplier Quotation, Request for Quotation parents: `tender =
  custom_crm_deal` where `tender` is empty and `custom_crm_deal` set; their item rows from
  the parent.
- `Journal Entry Account` rows from the parent Journal Entry's `custom_crm_deal`.
- Sales Invoice parents and items via `Sales Invoice Item.sales_order` → SO value, when the
  invoice's linked SOs yield exactly one value; Delivery Note via `Delivery Note
  Item.against_sales_order`; Purchase Invoice via `Purchase Invoice Item.purchase_order` →
  PO value; same uniqueness rule.
- GL Entry rows of vouchers (Journal Entry, Sales Invoice, Purchase Invoice, Delivery Note)
  whose document-level value was set above: set the row's field where empty. Do NOT backfill
  the overhead deal onto historical rows — pre-P5 rows stay empty and P5b reports them as
  "unassigned before P5".
- Return `{table: rows_updated}`; the patch prints it.

### B7 — Writers

- `submit_expense_entry` (`money.py:3359-3366`): replace the existence-only check with
  `assert_selectable_tender(deal, company)`; keep writing `doc.custom_crm_deal` (B4 stamps the
  rows). Unknown deal still throws `Unknown deal.`.
- `create_purchase_invoice(..., tender=None)`, `update_purchase_invoice(..., tender=None)`,
  `_apply_invoice_payload(..., tender=None)`: when `tender` is given and differs from the
  document's current value → `assert_selectable_tender`, then set the parent field and every
  item row; when `None` → leave it to B4/B5 (PO-linked items derive; a PI without PO ends on
  the overhead deal at GL time). `purchase_invoice_detail` returns `tender` (name or ""),
  `tender_label` (`organization` of the deal, "GENEL GİDER" for the overhead deal, "" when
  empty) and `tender_locked` (1 when any item has `purchase_order` and the value is set).
- `Stabler Company Modules` `on_update` → `on_company_modules_update(doc, method=None)`:
  if `enable_tender` is on and the dimension exists → `ensure_company_setup(doc.company)`.
  Never removes anything when the flag is turned off.

## Frontend states

- `Expenses.vue`: the picker calls `list_deals` with `active_tenders: 1`; the overhead row
  renders first as "GENEL GİDER"; on a tender company a NEW entry defaults `form.deal` to the
  overhead deal (the server would default the GL anyway — the screen must show what the
  ledger will say); an existing entry keeps whatever it holds and `loadDealLabel` still
  resolves it (no rewrite on load — the same rule as `charge_type` in ADR-606). Loading,
  empty ("No active tenders"), error (toast + picker stays usable with GENEL GİDER) and
  permission-denied (picker hidden, as today) states.
- `PurchaseInvoiceForm.vue`: a "Tender" `Typeahead` in the header, rendered only when
  `session.canAccessModule("tender")`; loads `tender`/`tender_label`/`tender_locked` from
  `purchase_invoice_detail`; disabled with the hint "Set by the purchase order" when locked;
  a new invoice without PO defaults to GENEL GİDER; sends `tender` on create/update. Same
  four states as above. No new `.btn-primary`; `MoneyInput`/`DateInput` untouched; no Desk
  link.
- Strings (English source) in all five catalogs: "GENEL GİDER" is a proper name and is not
  translated; the others are: "Tender", "Only an active tender or GENEL GİDER can be
  selected.", "Set by the purchase order", "No active tenders", "General overhead" (label for
  the overhead row's helper text), and whatever else you add — harvest, do not guess.

## Migration and compatibility

- Runs on 8 sites; on a site with no tender company it changes only `deal_type` options and
  NULL backfill. On a tender site it creates the dimension and its fields and the per-company
  setup. Idempotent, verified by running twice.
- `make test-bench` needs the migrated test site; that is the orchestrator's step after the
  merge. You may run the patch against the test site from the worktree exactly as written in
  "Verification commands" — nothing else touches the site's data.

## Accounting and currency invariants

- No amount, account, cost center, currency or exchange rate changes anywhere. Test: build the
  same JE and the same PI before and after the hooks are registered (or with the flag off and
  on) and compare every GL row minus the dimension field — byte-identical.
- A company without the flag: zero rows stamped, no throw, no detail row.

## Tenant-isolation requirements

- Every endpoint that lists tenders checks `_can_access_module(user, "tender")` AND
  `tender_enabled(company)`; the overhead deal is company-scoped; `assert_selectable_tender`
  rejects a deal of another company.

## Edge cases and failure behaviour

- Deal of another company → throw. Lost tender / won-and-closed tender → throw on write; an
  already stored one stays readable.
- Cancel/amend: ERPNext copies the GL row for the reversal, so the value follows.
- Repost of stock vouchers re-inserts GL rows → B5 runs again, derives the same value.
- Period Closing Voucher rows: B5 fills only empties; it must never throw on a voucher type
  that has no item table (guard `has_field` before reading rows).
- The dimension exists but the company's overhead deal was deleted by hand → B5 throws the
  message above naming the action.

## Measurable acceptance criteria

1. Patch run twice on the test site: second run reports zero changes; `Accounting Dimension`
   for CRM Deal exists; `GL Entry`, `Journal Entry Account`, `Sales Invoice`, `Purchase
   Invoice`, `Sales Order`, `Purchase Order` carry the field; `_Test Company` has a detail row
   (`mandatory_for_pl 1`, `default_dimension` = its overhead deal); a company created in a
   test with `enable_tender 0` gets no detail row and no overhead deal.
2. `submit_expense_entry(deal=<active tender>)` → every `Journal Entry Account` row and every
   GL row of the JE carries the deal; `deal=None` → the P&L GL rows carry the overhead deal
   and the cash/bank row is untouched; `deal=<lost tender>` → throws; `deal=<other company's
   tender>` → throws.
3. `create_purchase_invoice` without `tender` on the tender company → expense GL rows carry
   the overhead deal; with an active tender → that tender on parent, items and GL rows;
   `create_purchase_invoice_from_po` on a PO with `custom_crm_deal` → the PI carries the deal
   without the SPA sending it and `purchase_invoice_detail` reports `tender_locked 1`.
4. A submitted SO with `custom_crm_deal` → `make_sales_invoice` (ERPNext's, as
   `sales.py:2275` uses) → the SI parent and items carry the deal and its income GL rows
   carry it; `make_delivery_note` on a stock item with valuation → the DN and its COGS GL
   rows carry it.
5. The same JE built on a company with `enable_tender 0` → no GL row carries the field, no
   throw, and its GL rows equal the tender company's rows minus the field.
6. `list_deals(active_tenders=1)` returns the overhead deal first, excludes Standard deals,
   lost tenders and won tenders whose every submitted SO is Closed/Cancelled, includes a won
   tender with an open SO.
7. `_crm_list` never returns the overhead deal; a source test pins the three board
   enumeration sites (`tender.py:2313-2325`, `tender_master.py:451`) to their tender-only
   filters.
8. Source specs: Expenses picker sends `active_tenders: 1` and defaults a new entry to the
   overhead deal on tender companies; PI form renders the Typeahead behind
   `canAccessModule("tender")`, disables it on `tender_locked`, sends `tender`; every new
   `t()` key exists in all five catalogs; no Desk link, no `table-striped`, guards green.
9. Every new test was seen RED for the right reason before the code (mutate the fix away;
   paste the failing assertion); `make check` green with the vitest `Test Files` line visible.

## Exact verification commands (from the worktree)

```
make check                      # Test Files line must be visible in the report
make guards && git diff --check
# schema for the bench loop — the ONLY writes to the test site you may make:
PYTHONPATH=$PWD bench --site genesis-test.local execute stabler.patches.v103_tender_accounting_dimension.execute
PYTHONPATH=$PWD bench --site genesis-test.local execute stabler.patches.v103_tender_accounting_dimension.execute   # second run: all zeros
PYTHONPATH=$PWD bench --site genesis-test.local run-tests --module stabler.tests.test_tender_dimension_bench
```
Run the three bench lines from `/Users/zafar/frappe-bench-local` with `PYTHONPATH` set to the
worktree root (measured: the bench venv resolves `stabler` to the MAIN tree otherwise, and a
worktree-only field is dropped silently). Check that `.stabler-test-bench.lock` does not exist
in `apps/stabler` before each bench call. Never run `make test-bench`, `bench migrate`, or any
other data command against the site.

## Required completion report

Commit SHAs on the branch (leave nothing uncommitted); per-test red evidence (the failing
assertion line, verbatim); the `make check` tail with `ruff`, `eslint`, `sfc`, `Ran`, `Test
Files`, `Tests`, `pre-push gate` lines; the patch's printed counts from both runs; the list of
everything you created on the test site (dimension name and fieldname, custom-field count,
overhead deal name, detail row); files touched; every deviation from this contract with the
measurement that forced it; anything you could not verify, stated as such.

---

## Log

- 2026-09-03 evening: contract frozen by the orchestrator after measuring every path above.
- 2026-09-03 evening, correction (orchestrator's own error): the contract stated as *measured* that `patches.txt` has no `[post_model_sync]` marker. It has one at line 41 since 2026-07-08 (`22f70e7`); 38 patches sit above it, 64 below. The sentence was copied from `.claude/skills/stabler-orchestrator/SKILL.md:316`, which was wrong and contradicted `.claude/rules/20-backend-migrations.md:15`. The implementer found the truth independently and wrote it into v103's docstring. Both texts corrected in this commit. Consequence for P5a: none — the guards are required either way.

### Round 1 review — 2026-09-04

Fourteen adjudicated findings, all landed on `feat/adr-609-tender-dimension`, one commit each
(R2 and R4 share `2abccf0`: both rewrote the same gate in `default_gl_tender`). Every item was
proved by watching the test fail first, or — where the test came after the code — by mutating
the fix away and watching that exact assertion go red.

**Two lines of this contract were wrong, and the code follows the measurement, not the text:**

1. **B7, last bullet** — "`Stabler Company Modules` `on_update` → `on_company_modules_update`".
   `Stabler Company Modules` is a CHILD table, and Frappe persists child rows with `db_update()`
   inside `Document.update_child_table` (`document.py:616-648`); their document methods are never
   run. The handler fired **zero** times, so turning `enable_tender` on through the SPA set no
   company up. The hook belongs on the `Stabler Settings` SINGLE, as
   `on_settings_update(doc, method=None)`, with a re-entry guard: `get_company_module_row` saves
   the single when a company has no row, which re-enters the same `on_update`. (R1, `06e0ed6`)
2. **Line 55** — Request for Quotation is listed among the doctypes that receive the dimension
   field. It is absent from erpnext's `accounting_dimension_doctypes`
   (`erpnext/hooks.py:529`); Supplier Quotation is there, RFQ never was. Its `before_validate`
   block set a value on a field that does not exist and Frappe dropped it on save, and its
   `_LEGACY_PARENTS` entry pointed the backfill at a column `_column_exists` then silently
   refused. Both removed. (R10, `5a5ec2b`)

**The findings, in the order they were fixed:**

| # | P | What was wrong | Commit |
|---|---|---|---|
| R1 | P0 | the module-toggle hook was on a child table and fired zero times | `06e0ed6` |
| R2 | P0 | the GL hook gated on the stabler flag while erpnext reads the detail row | `2abccf0` |
| R4 | P1 | that gate cost 7.0 uncached queries per ledger row | `2abccf0` |
| R3 | P1 | the patch asserted a fieldname it had not created | `622413d` |
| R5 | P1 | Period Closing Voucher booked every tender's P&L onto GENEL GİDER | `6678a00` |
| R6 | P2 | a `frappe.throw` string was in no catalogue | `226299e` |
| R7 | P2 | both screens kept the previous company's overhead deal after a switch | `be98ada` |
| R8 | P2 | `save_deal` accepted the reserved `Overhead` type; the bucket was read unordered | `45ce6a1` |
| R9 | P2 | the manager cockpit counted the bucket as a deal | `5a056ab` |
| R10 | P3 | Request for Quotation was stamped and backfilled for nothing | `5a5ec2b` |
| R11 | P3 | the tender picker paged in SQL and filtered in Python | `f546a00` |
| R12 | P3 | "balance-sheet rows are left alone" was true of the hook, not of the ledger | `342b2a1` |
| R13 | P2 | a bill's tender could be replaced but never cleared | `7cd8fc9` |
| R14 | P3 | `ensure_company_setup` left a stale "not mandatory" behind the row it wrote | `2230a5d` |

**Measurements worth keeping.**

- The ledger DOES carry tender values on balance-sheet accounts. `default_gl_tender` never adds
  one, but erpnext copies a document-level dimension onto EVERY GL row a tagged voucher posts:
  measured on `genesis-test.local`, a tagged Purchase Invoice tags Creditors as well as the
  expense account, and a Sales Invoice made from a tagged Sales Order tags Debtors as well as
  Sales. **P5b must sum profit-and-loss accounts only**, or every tagged document is counted
  twice. Now pinned by a bench test rather than by prose. (R12)
- `list_active_tenders` cannot page in SQL: `is_active_tender` reads the deal's stage and its
  lot, which the query cannot express. Measured with four tenders, one lost: page 2 of size 2
  returned `['T-3']` where it owed `['T-2', 'T-3']` — a live tender fell off the end of the
  picker, and its cost would have gone to GENEL GİDER. (R11)
- `stabler.tests.test_crm_analytics` was bench-only because `stabler.api.crm` reaches the real
  `organization` → `www.stabler` → `frappe.sessions`. One stubbed module put it in `make check`,
  where the cockpit regression can actually be caught. (R9)

### Round 2 review — 2026-09-04

No P0. One P1 and three P2, all measured live, all landed on
`feat/adr-609-tender-dimension`, one commit each. Round 2 was the last
correction cycle.

| # | P | What was wrong | Commit |
|---|---|---|---|
| R15 | P1 | correcting an expense re-sent its own tender and was refused for it | `835f141` |
| R16 | P2 | "shared by every CRM Deal reader" was true of two readers out of five | `78dccc8` |
| R17 | P2 | the operations desk counted the bucket as somebody's open lot | `4712f07` |
| R18 | P2 | a failed tender lookup left the purchase invoice with an empty menu | `5c72077` |

**The P1 is the one worth remembering.** `Expenses.vue` puts the STORED deal into every
edit payload, so an amendment arrives naming the tender the voucher already carries.
`submit_expense_entry` asserted it as a fresh choice, which made the ONE operation that
corrects a posted expense impossible the moment its tender was finished — and the throw
lands AFTER `amend_expense_entry` has cancelled the source, so only the HTTP rollback saved
the user from a cancelled voucher with no replacement. The rule is now the same one
`purchasing._apply_tender` already followed: **assert a value that is CHANGING, never a value
that is being re-sent**. Any future writer that accepts a tender inherits that rule.

**What R16 says about testing.** The claim "shared by every CRM Deal reader" had been pinned
by `assertIn("exclude_overhead_deals(filters)", crm.py)`. One caller satisfied the string for
all of them, so the assertion stayed green while `crm_metrics` and
`crm_automation.run_crm_automation_rules` had never called the helper — and `crm_metrics`
answered `deal_count` 553 beside a board answering 552. A declaration-satisfiable assertion is
not coverage. Each reader is now DRIVEN in `stabler/tests/test_overhead_deal_readers.py`, with
a per-module call count so a new reader cannot appear without the filter.

**Test-site hygiene.** Six `ADR-609 bench` Journal Entries had accumulated on
`genesis-test.local` across this task's runs; the naming series then reissued a name one
leftover still pointed at, and an amendment test died on "This entry has already been amended"
instead of the tender check it was about. The six were removed by hand.

*Corrected in Round 3 (R20).* The explanation written here — "submitting a voucher commits
from inside frappe" — was wrong: `money.py` has no `db.commit` on any write path, and a
submitted voucher disappears on `frappe.db.rollback()`. What made the leftovers durable was the
class-level `addClassCleanup(frappe.db.commit)`, which commits whatever the per-test cleanups
failed to erase. The `frappe.db.commit()` this paragraph credited in `_erase_voucher` was
therefore both unnecessary and harmful, and has been removed — see the Round 3 entry.

"Two consecutive full runs leave the site empty" was also false. Eight of nine measured doctype
counts are unchanged by a green run; `Stock Ledger Entry` grows by 2 (6416 -> 6418 -> 6420 ->
6422 across four runs), because `_erase_voucher` deletes the voucher's GL rows and not the
stock ledger rows the Delivery Note fixture writes. Recorded, not fixed: Round 3 was scoped to
R19-R21 exactly.

**Verified clean by the reviewer this round, unchanged here:** both P0 fixes live (the hook
fires once per save; flag-off posting lands on GENEL GİDER with the cash leg NULL), the GL hook
costs 4 queries on row 1 and 0 on rows 2–20, every round-1 and round-2 mutation killed, the
money invariant (29 GL columns identical flag-on vs flag-off), tenant isolation, the patch
re-running all zeros, and the catalogues LF-only with no existing row changed.

### Round 3 review — 2026-09-04

One P0, one P2, one P3. The last correction cycle the orchestration rules allow.

| # | P | What was wrong | Commit |
|---|---|---|---|
| R19 | P0 | the operations desk was narrowed by `deal_type`, which is not what a lot is | `ebafc19` |
| R20 | P2 | the bench cleanup committed, on a claim that was not true | `8e741bc` |
| R21 | P3 | "this is an amendment" was something the caller could assert | `38d9599` |

**R19 was the orchestrator's own instruction, not the implementer's invention.** Round 2's R17
said to filter `{"deal_type": "Tender"}` "as `tender.py` and `tender_master.py` already do".
They do not: `_tender_deal_names` (`tender.py:2295`) UNIONS five criteria — a tagged
SO/PO/quotation, `custom_tender_intake`, `custom_bid_pricing`, `custom_parent_tender`, and only
then `deal_type == "Tender"` — because `save_deal_intake` never sets `deal_type` and v103
stamped every NULL to `Standard` for good. Measured on `genesis-test.local`: **484 deals carry
`custom_tender_intake` and not one of them is typed Tender**; exactly one deal on the site is.
So the instruction took `operations_desk` `team_load` from 553 to 1, and `deals_raw` feeds the
whole desk — orphan_lots, bid_due, delivery_due, won_without_po, sq_counts, the plan, the
decisions and the calendar would all have emptied out with it, silently, on a tender tenant.

The rule the code now carries: **narrow this reader by what is NOT a lot (the GENEL GİDER
bucket), never by what a lot is said to be.** `exclude_overhead_deals`'s docstring names the
five readers that count or list deals as work, and says why the other twelve `CRM Deal` list
sites in `stabler/api` need nothing — they resolve deals the caller already named, or are
already narrowed by a filter the bucket cannot satisfy.

**R20 — a suite must not change the site it measures.** Round 2 added `frappe.db.commit()` to
`_erase_voucher` on the claim that submitting a voucher commits. It does not: `money.py` has no
`db.commit` on any write path. The cleanup stack is LIFO, so that commit ran BEFORE
`_set_flag(1)` in `TestModuleFlagOff` and persisted `enable_tender = 0` on the real
`_Test Company` row. Removed, and the invariant is now pinned by
`TestSuiteHygiene.test_a_per_test_cleanup_never_commits` rather than described in a comment.
The one commit the suite still makes is the class-level one, which is needed because creating a
Company commits from inside ERPNext's chart of accounts.

**R21 — a client can set any parameter a whitelisted signature declares.** R15's relaxation
keyed off `amended_from`, so naming a cancelled voucher that carried a finished tender bought a
new expense against it. The relaxation is now carried on `frappe.local`, raised by
`amend_expense_entry` alone. The general rule: *permission to skip a check may never travel in
the payload that the check is protecting against.*
