# MIKAS Tender Operations Center — Final Fix Report

Status: DONE

## Fix commit

`26b59a92bd32feee67dd4a74a874de558cdc05e9` — `fix(tender): close final dashboard review gaps`

## Findings closed

- Director rows now check CRM Deal read permission before intake, label, deadline, bid-pricing, margin, or assignment data is read.
- Declarant/logistics feeds retain readable operational documents while redacting Deal label/intake/deadline data when CRM Deal read permission is denied.
- `assigned_to` and `assigned_to_name` are server-managed; ordinary intake edits preserve them and only the oversight-only assignment endpoint changes them.
- Acquisition metrics and lifecycle drill-downs use stage-specific dates: creation, decision, submission, and result timestamps.
- Company module enablement is evaluated before the admin role bypass, so a tender-disabled active company keeps the financial dashboard and does not select the tender feed.
- Director won/lost/pending/win-rate counts exclude result-only legacy rows and expose them as unverified.
- All intake JSON writers use a `SELECT ... FOR UPDATE` locking read, preserving the first submission timestamp, user, and reference across concurrent submission and ordinary-edit requests.
- Tender dashboard copy has non-empty en/ru/uz/uzc translations in the repository translation CSVs.
- Behavioral regressions cover cross-Doctype denial, assignment spoofing/preservation, admin/company gating, multi-month transition/filter intersections, legacy director exclusion, and locked first-submission behavior.

## Verification

```text
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_tender_dashboard \
  stabler.tests.test_tender_dashboard_behavior \
  stabler.tests.test_tender_dashboard_spa \
  stabler.tests.test_tender_dashboard_i18n \
  stabler.tests.test_tender_landed_vat \
  stabler.tests.test_imports_api_invariants -v

Ran 59 tests in 0.199s
OK

NODE_NO_WARNINGS=1 node --experimental-vm-modules stabler/tests/tender_board_filters.test.mjs
tender board filter behavior: OK

NODE_NO_WARNINGS=1 node stabler/tests/tender_dashboard_company_gate.test.mjs
tender dashboard company gate behavior: OK

python3 -m py_compile \
  stabler/api/tender.py \
  stabler/api/organization.py \
  stabler/integrations/uzex/webhook.py \
  stabler/tests/test_tender_dashboard_behavior.py \
  stabler/tests/test_tender_dashboard_i18n.py
OK

Vue compiler-sfc parse/compile: Dashboard, SalesOrderBoard, DirectorBoard,
MyTenders, DeclarantQueue, LogistBoard
All 6 SFCs: OK

Translation CSV shape validation: en, ru, uz, uzc
All 4 CSVs: OK

Forbidden Desk-link / tenant-name branch scan
No matches

git diff --check
OK
```

## Concerns

None.
