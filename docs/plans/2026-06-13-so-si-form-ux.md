# SO / SI Form UX Optimization

Date: 2026-06-13 · Forward UI only — **does not touch historical data or the GL**.
Builds on the form-hardening engine (`useDocumentForm`, `LineItemsEditor` — both already provide
line validation, Enter-to-add-row, grandTotal). Bar: QuickBooks Enterprise data-entry feel.

## 0. Hide Quotations tab (trivial, do first)
- `pages/sales/SalesHome.vue:10` — remove (or comment) the `sales-quotations` tab entry.
- Keep the route in `router.js` reachable (don't break existing links / QuotationForm), just drop
  it from the visible tab bar. If it should be fully gone, also guard the route — confirm intent.
  Recommended: hide tab, keep route (least destructive).

## 1. Currency default + inline exchange rate (highest value — UX *and* correctness)
Problem: `SalesOrderForm.vue:38` falls back to `"USD"` (`…default_currency || "USD"`). For a
UZS-base tenant this nudges every order to USD, and the form shows currency as **display-only**
(no selector) — the clerk can't correct it.
- Default currency = **company default currency** (never hardcode USD). Fallback to company
  currency, not USD.
- Add a **currency selector** (the field is currently read-only text). Most orders stay company
  currency; selector is there for the genuine foreign order.
- When selected currency ≠ company currency: show an **inline exchange-rate row** —
  "1 USD = 12 040 сўм · ЦБ {date}" (editable MoneyInput, prefilled with CBU effective rate from
  the existing `cbu_rate_refresh` data), with a live base-total preview. Amber hint if >5% off CBU
  (server already hard-blocks >20% via `validate_exchange_rate`). Hidden entirely for
  company-currency orders → zero friction for the 99% case.
- Same treatment on SalesInvoiceForm and the Purchase forms (shared once built).
- Acceptance: new SO on a UZS tenant defaults to сўм; switching to USD reveals the rate row;
  base-total preview updates live; company-currency order shows no rate UI.

## 2. Prominent running total (the QuickBooks signal)
- Replace the tiny footer "$0.00" with a **bold total block** anchored near the action buttons
  (sticky footer already exists in FormPage). Show, per transaction currency: Subtotal → (Discount)
  → (Tax, SI only) → **Grand total** (largest, bold, monospace). Updates live as lines change.
- This lives in `LineItemsEditor`'s footer slot so SO/SI/PO/PI all inherit it.
- Acceptance: total is the visually dominant number on the form; matches server `grand_total` on save.

## 3. Tighten line-item layout
- Cap the ITEM search column (e.g. `max-width` / flex-basis) so QTY/UOM/RATE/AMOUNT cluster
  together instead of floating to the far edge on wide screens. Numeric cells right-aligned,
  `font-monospace`, consistent column widths.
- Row height comfortable for touch (POS-adjacent users); zebra off (already `table-no-stripe`).
- Acceptance: on a 1920px screen the eye travels a short distance from item to amount; columns
  align across rows.

## 4. Inline stock availability on SO lines (reserve-aware)
- SO reserves stock on submit; the clerk should see availability **while picking**, not on submit.
  The backend per-line availability check already exists (`overAvailableRows` logic). Surface it:
  a small muted "{n} available" next to the selected item, turning red when qty exceeds free stock
  (the `is-invalid` path already fires — add the available-qty hint text).
- Acceptance: picking an item shows free qty for the chosen warehouse; over-ordering shows the
  red state with the available number before submit.

## 5. Header validation parity
- `LineItemsEditor` validates lines inline; header required fields (Customer, Warehouse) should
  match — red border + message on the field the moment a submit is attempted empty, not a generic
  throw. Disable Submit while required header fields or any line are invalid (Save-as-draft stays
  enabled — drafts may be incomplete).
- Acceptance: submitting with no customer flags the Customer field inline; Submit disabled until valid.

## 6. Item search result richness
- Search results show **code + name + (available qty for SO)**; keyboard-selectable. Confirm the
  Typeahead result rows aren't bare names.

## SI-specific (SalesInvoiceForm)
- All of the above, plus: **tax template selector** + tax line in the total stack (QQS/VAT);
  **due date** / payment terms; visible **payment/outstanding status**; quick actions to
  **Print / Waybill** and **Create from SO** (don't re-key). SI item lines: confirm whether
  editable or derived-from-SO (currently hand-rolled table, not LineItemsEditor — per close-out
  brief T4) and make consistent.

## Sequencing
0 (hide tab) → 1 (currency/rate — correctness) → 2 (total) → 3–6 (entry polish) → SI extras.
Items 2,3,5,6 land in `LineItemsEditor` once and propagate to every transactional form.

## Out of scope
- Historical data / GL (untouched — forward UI only).
- New doctypes; offline drafts; the multi-currency *repair* (separate spec, R1).
