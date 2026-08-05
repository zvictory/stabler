# Commercial Invoice Form — Transport Expenses & Form Reordering Report

**Date:** 2026-08-05  
**Target Environment:** `msa.erpstable.com` / Stabler SPA  
**Feature Branch/Files Modified:**
- [`stabler/api/_imports_rules.py`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/_imports_rules.py): Pure allocation math helper `calculate_ci_transport_costs` & `TRANSPORT_CATEGORIES` configuration.
- [`stabler/api/imports.py`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/imports.py): Whitelisted `@frappe.whitelist()` endpoint `ci_transport_costs(commercial_invoice)`.
- [`stabler/public/js/pages/imports/CommercialInvoiceForm.vue`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/imports/CommercialInvoiceForm.vue): UI redesign, section reordering, PO links removal from template while preserving payload state.
- [`stabler/tests/test_ci_transport_allocation.py`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/tests/test_ci_transport_allocation.py): 4 pure unit tests covering allocation math, category splitting, payment masking, and zero-weight fallback.
- [`stabler/translations/*.csv`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/translations): 25 new i18n keys added across `en.csv`, `ru.csv`, `tr.csv`, `uz.csv`, `uzc.csv`.

---

## 1. Executive Summary

All three requirements for the Commercial Invoice (CI) form update have been fully implemented, tested, and verified:

1. **Form Section Reordering**:
   - `CiLogisticsOverview` (`Логистическая готовность`) was moved to the very bottom of the form (after `Linked Trucks` / `Размещение контейнеров по фурам`).
   - Standard section sequence: Header → Items → Containers → Transport Expenses → Trucks → Logistics Readiness.

2. **PO Links Preservation**:
   - `Linked Purchase Orders` card removed from template layout to streamline form structure.
   - `po_links` model state, `blankForm` default, `fromDetail` initialization, and `savePayload` properties remain completely intact, preventing silent data loss upon saving.

3. **Transport Expenses Card (`Транспортные расходы`)**:
   - Displays transport allocation summary, payment progress bar, vendor summary table, expense documents breakdown, landed cost impact per kg, and separate sub-table for non-transport categories (`Other expenses` / `Прочие расходы`).
   - Integrated container transport allocation column (`Транспорт по контейнеру`) in the `Linked Containers` table.
   - Masking enforced via `rules.mask_named` using `_cost_visible()` permissions.

---

## 2. Allocation Logic & Pure Backend Rules

The helper `calculate_ci_transport_costs` in [`stabler/api/_imports_rules.py`](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/_imports_rules.py#L1360) implements standard landed cost allocation rules:

| Category Condition | Allocation Method | Rule |
| :--- | :--- | :--- |
| `expense.container` specified | `direct` | Allocated 100% to that specific container |
| `expense.truck` specified | `truck` | Allocated proportionally across containers assigned to that truck |
| General expense, `sum(container_weight) > 0` | `weight` | Allocated proportionally by container gross weight (`total_kg`) |
| General expense, `sum(container_weight) == 0` | `equal` | Allocated equally across all containers |
| No containers on CI | `invoice` | Summary table rendered at invoice level without container breakdown |

### Transport vs. Other Categories Split
- `TRANSPORT_CATEGORIES = ('Transport', 'Border Crossing', 'Handling', 'Storage', 'Insurance')`
- Documents with `category` in `TRANSPORT_CATEGORIES` are included in transport totals and container allocations.
- Categories outside this tuple (e.g. `Customs`, `Documentation`, `Other`) are grouped under `Other expenses` (`Прочие расходы`).

---

## 3. Automated Test Results

### Pure Unit Tests (`test_ci_transport_allocation.py`)
```bash
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_transport_allocation -v
```
- `test_direct_and_weight_allocation`: **PASS** (direct container allocation + weight-proportional split)
- `test_equal_allocation_when_weights_zero`: **PASS** (equal fallback when container weights are zero)
- `test_category_separation`: **PASS** (separates Transport vs Other expense categories correctly)
- `test_masked_payments`: **PASS** (masked payments set bank_payment/cash_payment to `None` when cost is restricted)

### JavaScript / Vue i18n & Utility Tests (`vitest`)
```bash
npm run test:js
```
- **138/138 tests passed** across 8 test suites (including i18n translation key verification).

---

## 4. Verification Screenshots

The following UAT evidence screenshots have been saved to `docs/uat/2026-08-05-ci-transport/screenshots/`:
- `01_ci_form_top_and_items.png`: Top metrics strip with 4th box (`Transport expenses`), header, and items table.
- `02_ci_transport_expenses_card.png`: `Транспортные расходы` card showing payment progress bar, vendor summary, container allocation, and landed cost.
- `03_ci_form_bottom_logistics_overview.png`: Bottom section showing `CiLogisticsOverview` positioned after trucks.

---

## 5. Compliance Checklist

- [x] **No Frappe Desk redirects**: Stabler remains fully self-contained.
- [x] **Striped tables**: Follows global CSS without redundant `table-striped` classes.
- [x] **Money fields**: All amounts render using `MoneyInput` / standard monospace formatting.
- [x] **Data Integrity**: PO links payload state preserved on load and save.
- [x] **Cost Masking**: Bank/cash payments masked via `_cost_visible()`.
