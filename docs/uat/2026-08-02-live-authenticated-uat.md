# Live Authenticated UAT Report — Final Hardening

**Date**: 2026-08-02  
**Target Site**: `stabler` (`http://localhost:8000/stabler`)  
**Bench Environment**: Local Frappe Bench (Site: `stabler`)  
**Evidence Artifact Path**: [docs/uat/evidence/2026-08-02-final-hardening/live_authenticated_uat_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-final-hardening/live_authenticated_uat_results.json)

---

## 1. Verified Users, Roles & Database Records

### Real Database Users & Roles
- **Manager User**: `hayrulloh@mail.com`  
  **Roles**: `Sales Manager`, `Sales Master Manager`, `Sales User`, `Accounts User`, `Customer`
- **Non-Manager User**: `fayzulloxoshimov61@gmail.com`  
  **Roles**: `Sales User`, `Accounts User`, `Customer` (Lacks `Sales Manager`, `System Manager`, `CRM Specialist`)
- **System Administrator User**: `Administrator`  
  **Roles**: `System Manager`, `Administrator`

### Real Database Records
- **Company**: `Mikas` (UZS)
- **CRM Deals**: `CRM-DEAL-2026-00001` through `CRM-DEAL-2026-00005` under `Mikas`
- **Tender Master**: `TND-2026-00001` (`UTY 154555`) under `Mikas`
- **Communication Record**: `3kvdri7p0e` linked to `CRM-DEAL-2026-00005`

---

## 2. Authenticated Endpoints Execution & Negative Role Verification

| Scenario | Authenticated Session | API / Route | Expected Result | Actual Result / Status | Evidence |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Manager Cockpit Access** | `hayrulloh@mail.com` (Manager) | `stabler.api.crm_analytics.get_manager_cockpit_metrics` | `200 OK`, returns company-scoped metrics | `200 OK` (company: Mikas, deal_count: 13) | `live_authenticated_uat_results.json` |
| **RFQ Defaults Lookup** | `hayrulloh@mail.com` (Manager) | `stabler.api.sourcing.get_deal_rfq_defaults` | `200 OK`, returns deal item/supplier defaults | `200 OK` (deal: CRM-DEAL-2026-00005) | `live_authenticated_uat_results.json` |
| **Automation Rules Preview** | `hayrulloh@mail.com` (Manager) | `stabler.api.crm_automation.preview_crm_automation_rules` | `200 OK`, read-only preview | `200 OK` (summary: Previewed 0 rules) | `live_authenticated_uat_results.json` |
| **Non-Manager Cockpit Block** | `fayzulloxoshimov61@gmail.com` (Non-Manager) | `stabler.api.crm_analytics.get_manager_cockpit_metrics` | `403 PermissionError`, fail-closed | `403 PermissionError` ("Not permitted. CRM Manager role required.") | `live_authenticated_uat_results.json` |
| **Non-Manager Automation Block** | `fayzulloxoshimov61@gmail.com` (Non-Manager) | `stabler.api.crm_automation.preview_crm_automation_rules` | `403 PermissionError`, fail-closed | `403 PermissionError` ("Not permitted. CRM Manager role required.") | `live_authenticated_uat_results.json` |
| **Email Send & Audit Retry** | `Administrator` (Admin) | `stabler.api.crm_email.send_deal_email` | Creates `Communication` record & records delivery status in DB | DB `tabCommunication` record `3kvdri7p0e` created with `custom_execution_status="Failed"`, `custom_attempts=1`, `custom_last_error="Please setup default outgoing Email Account..."` | MariaDB Query: `SELECT name, reference_name, custom_execution_status, custom_attempts, custom_last_error FROM tabCommunication WHERE name='3kvdri7p0e';` |

---

## 3. Schema & Database Column Verification on Live Site

### Live Custom Columns on `tabCommunication`
```sql
SHOW COLUMNS FROM `tabCommunication` LIKE "custom_%";
```
**Output**:
- `custom_triage_status`: `varchar(140)`, default `"Pending"`
- `custom_idempotency_key`: `varchar(140)`, index `UNI` (Unique)
- `custom_execution_status`: `varchar(140)`, default `"Executed"`
- `custom_attempts`: `int(11)`, default `1`
- `custom_last_error`: `text`

### Live Custom Columns on `tabCRM Activity`
```sql
SHOW COLUMNS FROM `tabCRM Activity` LIKE "custom_%";
```
**Output**:
- `custom_idempotency_key`: `varchar(140)`, index `UNI` (Unique)
- `custom_rule_name`: `varchar(140)`
- `custom_execution_status`: `varchar(140)`, default `"Executed"`
- `custom_attempts`: `int(11)`, default `1`
- `custom_last_error`: `text`
