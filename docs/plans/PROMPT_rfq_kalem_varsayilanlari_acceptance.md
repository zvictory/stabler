# RFQ Item Defaults Prompt Acceptance & Provenance Log

**Source Path**: `/Users/zafar/Downloads/PROMPT_rfq_kalem_varsayilanlari.md`  
**Target Path**: `docs/plans/PROMPT_rfq_kalem_varsayilanlari.md`  
**Source SHA-256**: `c1941e5579922623467c6ab59131c693cff64fb75e5ab6e4f86676a1378fbc06`  
**Target SHA-256**: `c1941e5579922623467c6ab59131c693cff64fb75e5ab6e4f86676a1378fbc06`  
**Provenance Status**: **PASS** (Byte-for-byte identical match)  
**Ingestion Date**: 2026-08-02  
**Branch**: `design/modernist-operations-desk`  
**HEAD SHA**: `038a788`  

---

## Acceptance Matrix

| Gereksinim | Kod | Test | Commit | Sonuç |
|---|---|---|---|:---:|
| `_apply_rfq_item_defaults` | [stabler/api/sourcing.py:277-310](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L277-L310) | `test_rfq_item_defaults_populates_stock_uom_and_uom` | `4800f08` | **PASS** |
| `stock_uom` -> `uom` | [stabler/api/sourcing.py:291-298](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L291-L298) | `test_rfq_item_defaults_populates_stock_uom_and_uom` | `4800f08` | **PASS** |
| conversion factor | [stabler/api/sourcing.py:299-306](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L299-L306) | `test_rfq_item_conversion_factor_is_one_when_uom_matches_stock_uom` | `4800f08` | **PASS** |
| schedule-date fallback | [stabler/api/sourcing.py:309](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L309) | `test_rfq_item_empty_schedule_date_uses_header_or_today`, `test_rfq_item_explicit_schedule_date_is_preserved` | `4800f08` | **PASS** |
| row warehouse / no `set_warehouse` | [stabler/api/sourcing.py:270-274, 453, 460](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L270-L274) | `test_saved_quotation_has_warehouse_from_company_default`, `test_explicit_warehouse_overrides_company_default` | `4800f08` | **PASS** |
| corrected assertions | [stabler/tests/test_sourcing_api.py:530-575](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/tests/test_sourcing_api.py#L530-L575) | `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_api` | `4800f08` | **PASS** |
| `valid_till` via `getdate` | [stabler/api/sourcing.py:353-359](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L353-L359) | `test_valid_till_before_transaction_date_throws_our_error`, `test_valid_till_equal_or_after_transaction_date_is_valid` | `6ce5093` | **PASS** |
| company-scoped frontend defaults | [stabler/api/sourcing.py:428-450](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/api/sourcing.py#L428-L450), [SourcingWorkspace.vue:263-288](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/tender/SourcingWorkspace.vue#L263-L288) | `test_get_deal_rfq_defaults_returns_company_scoped_defaults`, `sourcingWorkspace.spec.js` | `cbfe7bb` | **PASS** |
| dirty-state preservation | [SourcingWorkspace.vue:257-265](file:///Users/zafar/frappe-bench-local/apps/stabler/stabler/public/js/pages/tender/SourcingWorkspace.vue#L257-L265) | Vitest Source Contract Test (`preserves user dirty state without overwriting manual input on async reload`) | `cbfe7bb` | **VERIFY** |
| browser smoke | User Responsibility per Prompt | Authenticated UAT Report ([docs/uat/2026-08-02-tender-crm-final-hardening.md](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/2026-08-02-tender-crm-final-hardening.md)) | — | **USER GATE** |

---

## Verification Commands & Baseline

- **Python Sourcing Test Suites**:
  `PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_api stabler.tests.test_sourcing_spa -v`  
  **Result**: 105 tests, **OK** (0 failures, 0 errors, 0 skips).

- **Frontend Vitest Suite**:
  `npx vitest run stabler/public/js/tests/sourcingWorkspace.spec.js`  
  **Result**: 7 tests passed (**100% PASS**).
