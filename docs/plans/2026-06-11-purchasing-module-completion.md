# Purchasing Module — Completion Spec

Date: 2026-06-11 · Status: approved scope, ready for implementation
Decisions made by Zafar: **dual receiving model** (PI-with-stock default, Purchase Receipt for import suppliers) and **full scope** (receiving + landed costs, returns, PI multi-currency + taxes, reports + supplier detail).

---

## 1. Current state (audited 2026-06-11)

### Backend — `stabler/api/purchasing.py` (970 lines)

| Area | Endpoints | State |
|---|---|---|
| Suppliers | `list_suppliers`, `list_suppliers_with_balances` (multi-ccy, PE-drift corrected), `supplier_ledger`, `supplier_detail`, `create/get/update/delete_supplier`, `list_supplier_groups` | ✅ done (`supplier_detail` exists but **unused by UI**) |
| Purchase Orders | `list/detail/create/submit/cancel/amend_purchase_order`, `create_purchase_invoice_from_po` (ERPNext mapper, partial billing) | ✅ done |
| Purchase Invoices | `list/detail/create/submit/cancel_purchase_invoice` | ⚠️ create lacks currency, taxes, warehouse; `update_stock` param exists but UI never sends it |
| AP Aging | `ap_aging` (buckets per supplier×currency) | ✅ done |

### Frontend — `stabler/public/js/pages/purchasing/`

| Page | State |
|---|---|
| `PurchasingHome.vue` | Tab shell: Suppliers / Orders / Invoices / AP Aging |
| `Suppliers.vue` (1003 L) | List + balances, CRUD drawer, ledger drawer, PartyPaymentModal (on-account supplier payments) |
| `PurchaseOrders.vue` (909 L) | List + filters, create drawer (warehouse, currency, price list, line discounts, buy-price autolookup), detail drawer (received %/billed %, linked PIs), submit/cancel/amend, "Create Bill" |
| `PurchaseInvoices.vue` (677 L) | List + per-currency totals, detail drawer (items, taxes, base amounts), create modal (supplier, dates, bill_no, lines), PaymentModal |
| `Aging.vue` | Wraps shared `AgingTable` |

### Hard gaps

1. **Stock never arrives via purchasing.** No Purchase Receipt anywhere; PI create UI doesn't expose `update_stock`/warehouse. PO `per_received` stays 0 % forever. Goods currently only enter stock via Inventory → Stock Entry (Material Receipt), disconnected from PO/PI/valuation.
2. **No Landed Cost Voucher** — customs, freight, certification costs are not capitalised into item valuation. Critical for UZ importers.
3. **No purchase returns.** PI statuses "Return"/"Debit Note Issued" filterable but uncreatable.
4. **PI create is base-currency only, tax-free** — but USD supplier bills are the norm; QQS (VAT) lines can't be entered.
5. No purchasing reports; supplier 360° endpoint unused.

---

## 2. Architecture decision: dual receiving model

**Default path (most suppliers):** Purchase Invoice with `update_stock = 1` is simultaneously the bill and the goods receipt. One document, one mental model for non-accountants. LCV attaches to the PI.

**Import path (cargo ≠ invoice timing, or warehouse staff ≠ accounting):** PO → **Purchase Receipt** (goods arrive, stock in, valuation provisional) → PI (bill arrives later, links to PR). LCV attaches to the PR.

**Rule enforced in UI, not schema:** a PI created *from a PO that already has receipts* must have `update_stock = 0` (ERPNext double-stock guard exists server-side anyway; we surface it pre-submit). The bill form shows a "Goods already received via {PR}" hint and locks the toggle.

ERPNext supports LCV against both `Purchase Receipt` and `Purchase Invoice (update_stock=1)` — both paths get landed costs.

---

## 3. Workstream A — Receiving

### A1. PI-with-stock (UI only; API already supports it)

`PurchaseInvoices.vue` create modal gains:

- `update_stock` toggle, default **ON** (label: "Receive goods into stock") — most bills are cash-and-carry.
- `set_warehouse` Select (required when toggle ON; reuse `list_stock_warehouses` loader from PurchaseOrders.vue).
- API change: `create_purchase_invoice` accepts `set_warehouse: str | None`; when `update_stock` and no warehouse → throw. Apply to doc + every item row.

### A2. Purchase Receipt (new doctype surface)

**New endpoints** (`purchasing.py`):

```
list_purchase_receipts(company, from_date?, to_date?, supplier?, status?, limit=100)
  → name, posting_date, supplier, supplier_name, grand_total, status, per_billed,
    currency, docstatus, set_warehouse

purchase_receipt_detail(name)
  → header (incl. currency, conversion_rate, base totals, lcv_total — see C3),
    items[{item_code, item_name, qty, rejected_qty, uom, rate, amount, warehouse,
           purchase_order, landed_cost_voucher_amount}],
    linked purchase_invoices[], landed_cost_vouchers[]

create_purchase_receipt_from_po(name, items?)
  → ERPNext mapper erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt;
    optional items=[{po_detail_name, qty}] for partial receipt (cap qty at pending);
    insert as draft, return {name}

create_purchase_receipt(company, supplier, items, set_warehouse, posting_date?,
                        currency?, remarks?)   # direct PR without PO (rare, allowed)

submit_purchase_receipt(name) / cancel_purchase_receipt(name)

create_purchase_invoice_from_pr(name)
  → erpnext...purchase_receipt.make_purchase_invoice; draft PI, update_stock=0
```

Validation mirrors existing style: `_require_company`, `_assert_can_read`, qty > 0, warehouse exists, partial-qty ≤ pending qty.

**New page** `pages/purchasing/PurchaseReceipts.vue` — clone the PurchaseOrders.vue list+drawer pattern:

- Filters: dates, supplier (Typeahead), status (`To Bill`, `Completed`, `Return Issued`, `Draft`).
- Detail drawer: items with qty/warehouse, per-item landed cost, linked PO/PI/LCV chips (use `RelatedDocuments.vue`), actions: Submit, Cancel, **Create Bill**, **Add Landed Costs** (opens LCV form prefilled, §C).
- Create entry points: (a) PO detail drawer gains **"Receive"** button → partial-receipt modal (rows = PO items with pending qty, editable qty, capped); (b) standalone "New Receipt" for no-PO deliveries.

**Route:** `{ path: "receipts", name: "purchasing-receipts", component: PurchaseReceipts, meta: { title: t("Receipts") } }` — insert between Orders and Invoices in router + PurchasingHome tabs.

### A3. PO lifecycle effects

`per_received` now moves via PR or PI(update_stock). PO list/detail already render it — no change. PO detail drawer: add linked receipts query (mirror `pi_links` SQL against `tabPurchase Receipt Item.purchase_order`).

---

## 4. Workstream B — PI multi-currency + taxes

### B1. API — extend `create_purchase_invoice`

New optional params: `currency`, `conversion_rate`, `price_list`, `taxes`, `set_warehouse` (A1), `discount` fields per line (parity with PO create).

- `currency` ≠ company currency → require `conversion_rate > 0` (UI prefills from `stabler.api.compliance` exchange-rate source if available, else last PI rate for that supplier, else manual).
- `taxes`: list of `{account_head, description, rate?, tax_amount?}` rows appended as `charge_type = "On Net Total"` (rate) or `"Actual"` (amount).
- Simpler operator path: new endpoint `list_purchase_tax_templates(company)` returning `tabPurchase Taxes and Charges Template` rows; `create_purchase_invoice(taxes_template=...)` sets `taxes_and_charges` and lets ERPNext expand it. **UI uses templates only** (dropdown "VAT 12 %" / "No VAT"); raw tax rows stay API-level for future needs.

### B2. UI — create modal additions

- Currency Select (reuse `sales.list_currencies`) + conversion-rate MoneyInput (shown only when ≠ base ccy) + live base-total preview line.
- Tax template Select; computed tax + grand total shown before save.
- All amounts via `MoneyInput`, dates via `DateInput` (hard rules).

### B3. Draft editing

Add `update_purchase_invoice(name, …same payload…)` — draft-only (docstatus 0), full row replace, same validation. Plus `delete_purchase_invoice(name)` draft-only. UI: detail drawer "Edit"/"Delete" buttons visible only for Draft. (PO parity: PO already has amend; draft-PO edit deferred, not in scope.)

---

## 5. Workstream C — Landed Cost Voucher

### C1. Concept presented to operators

"Additional arrival costs" — not accounting jargon. Fixed category list in UI, each mapped to an expense account:

| Category (i18n key) | Account resolution |
|---|---|
| Customs duty (Bojxona boji) | per-company default, see C4 |
| Freight (Yuk tashish) | 〃 |
| Certification (Sertifikatlash) | 〃 |
| Other | 〃 |

### C2. Endpoints

```
list_landed_cost_vouchers(company, from_date?, to_date?, limit=100)
  → name, posting_date, receipt docs (type+name), total_taxes_and_charges, docstatus

landed_cost_voucher_detail(name)

create_landed_cost_voucher(company, receipts, costs, distribute_based_on="Amount",
                           posting_date?, auto_submit=1)
  receipts: [{doctype: "Purchase Receipt"|"Purchase Invoice", name}]
            (PI rows must have update_stock=1 — validate, else throw with clear message)
  costs:    [{category, amount, description?}]  → mapped to expense_account (C4)
  distribute_based_on: "Amount" | "Qty"
  Implementation: frappe.new_doc("Landed Cost Voucher"); append purchase_receipts;
  call doc.get_items_from_purchase_receipts(); append taxes; doc.distribute_charges_based_on;
  insert; submit if auto_submit.

cancel_landed_cost_voucher(name)
```

> Implementation note: before coding, confirm against the installed ERPNext version that
> `Landed Cost Purchase Receipt.receipt_document_type` includes "Purchase Invoice" and that
> `LandedCostVoucher.get_items_from_purchase_receipts()` exists (both standard since v13;
> bench source wasn't reachable from this session).

Currency note: LCV taxes are **company-currency** in ERPNext. Costs entered in UZS even when the PR is USD — the UI labels this explicitly ("Costs in UZS").

### C3. UI

**New page** `pages/purchasing/LandedCosts.vue`: list + create drawer + detail drawer.

Create drawer flow: pick receipt document(s) (Typeahead over submitted PRs + stock-PIs, last 90 d, filterable by supplier) → items preview table (read-only, shows current valuation) → cost rows (category Select + MoneyInput + optional note) → distribution toggle Amount/Qty (default Amount) → preview of per-item allocation → Submit.

Entry points: standalone page tab "Landed Costs"; **"Add Landed Costs"** action on PR detail (A2) and on stock-PI detail drawer.

Route: `{ path: "landed-costs", name: "purchasing-landed-costs", component: LandedCosts, meta: { title: t("Landed Costs") } }`.

### C4. Account mapping decision

Resolution order for each category's `expense_account`: (1) row in new child table on Stabler Company Settings (if such a settings doctype exists — reuse; else) (2) company's `expenses_included_in_valuation` account from `tabCompany` as fallback for **all** categories. **V1 ships with fallback only** — single account, zero setup. Category still recorded in the LCV row `description` for reporting. Per-category account mapping = follow-up patch when a customer asks.

---

## 6. Workstream D — Purchase returns (debit note)

Mirror `sales.create_sales_return` exactly:

```
create_purchase_return(purchase_invoice, items?, posting_date?, remarks?, auto_submit=1)
  → from erpnext.controllers.sales_and_purchase_return import make_return_doc
    doc = make_return_doc("Purchase Invoice", purchase_invoice)
    optional items=[{item_code, qty}] for partial return (qty clamped to returnable);
    update_stock copied from source PI (stock goes back out only if it came in via this PI);
    returns against PR-received goods: create the debit note with update_stock=0 and
    a separate PR-return is OUT OF SCOPE v1 — documented limitation, stock correction
    via Stock Entry if needed.
```

Also `list` support: returns appear in existing PI list (negative grand_total, status Return) — already works since they're Purchase Invoices.

**UI:** new `pages/purchasing/PurchaseReturnForm.vue` cloned from `SalesReturnForm.vue`; route `returns/new` (name `purchasing-return-new`). Entry point: "Return" button on submitted-PI detail drawer (hidden when `is_return`). PI detail endpoint: add `is_return`, `return_against`, and returns-issued-against-this list (mirror sales.py:521-526).

---

## 7. Workstream E — Reports + supplier detail

### E1. Purchasing reports

Mirror the `sales_report_*` family (sales.py:817-1000):

```
purchase_report_by_supplier(company, from_date, to_date)   # totals, bill count, returns net
purchase_report_by_item(company, from_date, to_date)       # qty, spend, avg rate
purchase_report_by_date(company, from_date, to_date, granularity)  # trend
purchase_price_history(company, item_code, limit=50)       # last N rates per supplier — UZ
                                                           # operators negotiate on this
```

All sum `base_*` amounts (single-currency totals), show per-currency breakdown columns where the sales versions do. New page `pages/purchasing/PurchasingReports.vue` cloned from `SalesReports.vue` (tabs: Suppliers / Items / Trend / Price history; ApexChart for trend). Route: `reports`.

### E2. Supplier 360°

Wire the existing unused `supplier_detail` endpoint into `Suppliers.vue`: drawer becomes two tabs — **Overview** (outstanding by currency, lifetime spend, recent bills, contact fields) and **Ledger** (current drawer content). Extend `supplier_detail` with `recent_orders` (last 20 POs) and link rows open the respective drawers.

---

## 8. Cross-cutting requirements (hard rules — reviewer checklist)

- **No Desk links anywhere.** All new doc surfaces are SPA drawers/pages.
- **MoneyInput** for every amount/rate field; **DateInput** + `formatDate`/`formatDateTime` for every date. No bare `<input type="number|date">`, no raw ISO interpolation.
- Tables: plain `.table` (striping is global), currency cells `font-monospace`.
- **Module access:** all new routes live under the existing `/purchasing` parent which carries `meta: { module: "purchasing" }` — no `_MODULE_ROLES` change needed (roles: Purchase User, Purchase Manager). Verify Purchase Receipt / LCV doctype perms exist for those roles; if not, add `Custom DocPerm` fixtures via idempotent patch (`frappe.db.exists` guard).
- **i18n:** every new string through `t()`/`__()`; run harvest; fill **en, ru, uz, uzc, tr** before merge. Key new terms — Receipt: Приёмка / Qabul qilish; Landed Costs: Доп. расходы прихода / Kirim xarajatlari; Debit Note: Возврат поставщику / Yetkazib beruvchiga qaytarish (translator to confirm uzc).
- **Patches:** none required for v1 (no schema changes; C4 fallback uses existing Company field). Any future settings field → `[post_model_sync]`-safe, idempotent.
- **Commits:** explicit paths only; translations as five CSVs.

## 9. Phasing & acceptance

| Phase | Contents | Acceptance test |
|---|---|---|
| **P1** | A1 (PI update_stock UI) + B1/B2 (currency + tax templates) + B3 (draft edit/delete) | Create USD bill w/ VAT template + stock-in; stock ledger shows receipt; base totals correct at given rate; draft editable, submitted not |
| **P2** | A2/A3 (Purchase Receipt) | PO → partial Receive (3 of 5) → PO 60 % received; PR → Create Bill → PI links, no double stock; cancel chain clean |
| **P3** | C (Landed costs) | LCV over a PR with 2 cost rows distributes by amount; item valuation rises in Stock Ledger; works equally on stock-PI |
| **P4** | D (Returns) | Partial return of stock-PI restores AP and stock; return visible in PI list + against-source links |
| **P5** | E (Reports + supplier 360°) | Numbers reconcile vs PI list totals; price history matches last bills |

Each phase = one PR, deployable independently. Smoke per phase on local site, then standard rsync deploy to `anjan.erpstable.com` (confirm target via `list-apps | grep stabler` first; `bench restart` needed — every phase touches `.py`).

## 10. Out of scope (explicit)

- PR-returns (stock return against Purchase Receipt) — Stock Entry workaround documented.
- Per-category LCV account mapping UI (fallback account only).
- Supplier quotation / RFQ workflow.
- PO draft-edit (amend flow exists).
- Subcontracting, rejected-qty warehouse handling (rejected_qty surfaced read-only in PR detail).
