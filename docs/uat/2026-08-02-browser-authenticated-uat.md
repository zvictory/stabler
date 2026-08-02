# Real HTTP & Browser Session Authenticated UAT Report

**Date**: 2026-08-02  
**Target Server**: `http://localhost:8000` (Site: `stabler`)  
**Evidence Harness**: [docs/uat/scripts/browser_authenticated_uat_harness.py](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/scripts/browser_authenticated_uat_harness.py)  
**JSON Evidence Artifact**: [docs/uat/evidence/2026-08-02-browser-final/browser_uat_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/browser_uat_results.json)  
**DB Concurrency Evidence Artifact**: [docs/uat/evidence/2026-08-02-browser-final/db_concurrency_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/db_concurrency_results.json)

---

## 1. HTTP Session Login & Cookie Authentication Evidence

- **Manager Session**: `hayrulloh@mail.com`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=73956ca2a82243c99f8a8df7c4c9689dba261721f30b71fc182e2b25`, `system_user=yes`
- **Non-Manager Session**: `fayzulloxoshimov61@gmail.com`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=5626fe70c0be8ea0c8f9213837b511174c18377c879ca6ff72e5495f`
- **Administrator Session**: `Administrator`  
  - **Login Route**: `POST http://localhost:8000/api/method/login` -> **HTTP 200 OK**  
  - **Session Cookie**: `sid=49c5fb37e8f4c8995582583a97e702dbf9fe7d1cf1e2286130326ef3`

---

## 2. HTTP Web Routes & API Authorization Verification Matrix

| Scenario | HTTP Session Cookie | Target Route / API | HTTP Code | Response Summary / DB Verification | Evidence |
| :--- | :--- | :--- | :---: | :--- | :---: |
| **Portfolio SPA Route** | `sid=73956ca...` (Manager) | `GET /stabler#/tender/portfolio` | `200 OK` | Loads modernist SPA app shell | `browser_uat_results.json` |
| **Deal 360 SPA Route** | `sid=73956ca...` (Manager) | `GET /stabler#/crm/deals/CRM-DEAL-2026-00005` | `200 OK` | Loads deal record workspace | `browser_uat_results.json` |
| **Cockpit SPA Route** | `sid=73956ca...` (Manager) | `GET /stabler#/crm/cockpit` | `200 OK` | Loads cockpit analytics view | `browser_uat_results.json` |
| **Manager Cockpit API** | `sid=73956ca...` (Manager) | `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` | `200 OK` | Returns `deal_count: 13`, `company: Mikas` | `browser_uat_results.json` |
| **RFQ Defaults API** | `sid=73956ca...` (Manager) | `POST /api/method/stabler.api.sourcing.get_deal_rfq_defaults` | `200 OK` | Returns company-scoped defaults for `CRM-DEAL-2026-00005` | `browser_uat_results.json` |
| **Non-Manager Cockpit API** | `sid=5626fe7...` (Non-Manager) | `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` | `403` | `frappe.exceptions.PermissionError: Not permitted. CRM Manager role required.` | `browser_uat_results.json` |
| **Non-Manager Automation API** | `sid=5626fe7...` (Non-Manager) | `POST /api/method/stabler.api.crm_automation.preview_crm_automation_rules` | `403` | `frappe.exceptions.PermissionError: Not permitted. CRM Manager role required.` | `browser_uat_results.json` |
| **Email Failure Transaction (Attempt 1)** | `sid=49c5fb3...` (Admin) | `POST /api/method/stabler.api.crm_email.send_deal_email` | `500` | Structured error returned (`status: "Failed"`, `error: "Email delivery failed..."`). **Durable DB row saved** (`8u3u3hj6s3`, `custom_execution_status: "Failed"`, `custom_attempts: 1`). | `browser_uat_results.json` |
| **Email Retry Lifecycle (Attempt 2)** | `sid=49c5fb3...` (Admin) | `POST /api/method/stabler.api.crm_email.send_deal_email` | `500` | Structured error returned (`status: "Failed"`, `error: "Email delivery failed..."`). **Durable DB row updated** (`custom_execution_status: "Failed"`, `custom_attempts: 2`). | `browser_uat_results.json` |

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
