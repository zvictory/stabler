# HTTP & Browser Session Authenticated UAT Report

**Date**: 2026-08-02  
**Target Server**: `http://localhost:8000` (Site: `stabler`)  
**HTTP Evidence Harness**: [docs/uat/scripts/http_session_uat_harness.py](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/scripts/http_session_uat_harness.py)  
**JSON Evidence Artifact**: [docs/uat/evidence/2026-08-02-browser-final/http_session_uat_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/http_session_uat_results.json)  
**DB Concurrency Evidence Artifact**: [docs/uat/evidence/2026-08-02-browser-final/db_concurrency_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/db_concurrency_results.json)

---

## 1. HTTP Session Login & Cookie Authentication Evidence

- **Manager Session**: `hayrulloh@mail.com`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=<redacted>`, `system_user=<redacted>`
- **Non-Manager Session**: `fayzulloxoshimov61@gmail.com`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=<redacted>`
- **Administrator Session**: `Administrator`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=<redacted>`

---

## 2. HTTP Web Routes & API Authorization Verification Matrix

| Scenario | HTTP Session Cookie | Target Route / API | HTTP Code | Response Summary / DB Verification | Evidence |
| :--- | :--- | :--- | :---: | :--- | :---: |
| **Portfolio SPA Route** | `sid=<redacted>` (Manager) | `GET /stabler#/tender/portfolio` | `200 OK` | Loads modernist SPA app shell | `http_session_uat_results.json` |
| **Deal 360 SPA Route** | `sid=<redacted>` (Manager) | `GET /stabler#/crm/deals/CRM-DEAL-2026-00005` | `200 OK` | Loads deal record workspace | `http_session_uat_results.json` |
| **Cockpit SPA Route** | `sid=<redacted>` (Manager) | `GET /stabler#/crm/cockpit` | `200 OK` | Loads cockpit analytics view | `http_session_uat_results.json` |
| **Manager Cockpit API** | `sid=<redacted>` (Manager) | `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` | `200 OK` | Returns `deal_count: 13`, `company: Mikas` | `http_session_uat_results.json` |
| **RFQ Defaults API** | `sid=<redacted>` (Manager) | `POST /api/method/stabler.api.sourcing.get_deal_rfq_defaults` | `200 OK` | Returns company-scoped defaults for `CRM-DEAL-2026-00005` | `http_session_uat_results.json` |
| **Non-Manager Cockpit API** | `sid=<redacted>` (Non-Manager) | `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` | `403` | `frappe.exceptions.PermissionError: Not permitted. CRM Manager role required.` | `http_session_uat_results.json` |
| **Non-Manager Automation API** | `sid=<redacted>` (Non-Manager) | `POST /api/method/stabler.api.crm_automation.preview_crm_automation_rules` | `403` | `frappe.exceptions.PermissionError: Not permitted. CRM Manager role required.` | `http_session_uat_results.json` |
| **Email Failure Transaction (Attempt 1)** | `sid=<redacted>` (Admin) | `POST /api/method/stabler.api.crm_email.send_deal_email` | `500` | Structured error returned (`status: "Failed"`, `error: "Email delivery failed..."`). **Durable DB row saved**. | `http_session_uat_results.json` |
| **Email Retry Lifecycle (Attempt 2)** | `sid=<redacted>` (Admin) | `POST /api/method/stabler.api.crm_email.send_deal_email` | `500` | Structured error returned (`status: "Failed"`, `error: "Email delivery failed..."`). **Durable DB row updated**. | `http_session_uat_results.json` |

---

## 3. Multi-Process Database Concurrency Race Verification

**Test Harness**: [docs/uat/scripts/db_concurrency_harness.py](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/scripts/db_concurrency_harness.py)  
**Methodology**: Two independent Python worker processes synchronized via `multiprocessing.Barrier` fired simultaneous POST requests against the exact same scoped idempotency keys (`comm:Mikas:CONCURRENCY-RACE-COMM-001` and `CONCURRENCY-RACE-ACT-001`).

### Empirical MariaDB Verification Results
- **Communication Race**:
  - Winner Process (PID 81191): Saved row `82s8gde3ep` (`custom_execution_status: "Failed"`).
  - Loser Process (PID 81192): Caught MariaDB `IntegrityError(1062, "Duplicate entry 'comm:Mikas:CONCURRENCY-RACE-COMM-001' for key 'custom_idempotency_key'")`.
  - **MariaDB Rows Found**: **Exactly 1 row** (`single_row_verified: true`).
- **CRM Activity Race**:
  - Winner Process (PID 81195): Saved row `ACT-2026-001143` (`custom_execution_status: "Executed"`).
  - Loser Process (PID 81196): Caught MariaDB `IntegrityError(1062, "Duplicate entry 'CONCURRENCY-RACE-ACT-001' for key 'custom_idempotency_key'")`.
  - **MariaDB Rows Found**: **Exactly 1 row** (`single_row_verified: true`).
