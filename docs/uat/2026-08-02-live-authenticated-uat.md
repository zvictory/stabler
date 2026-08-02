# Live Backend Authorization UAT Report

**Date**: 2026-08-02  
**Target Site**: `stabler` (`http://localhost:8000/stabler`)  
**Bench Environment**: Local Frappe Bench (Site: `stabler`)  
**Evidence Harness**: [docs/uat/scripts/backend_live_auth_harness.py](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/scripts/backend_live_auth_harness.py)  
**Evidence Artifact Path**: [docs/uat/evidence/2026-08-02-browser-final/backend_live_auth_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/backend_live_auth_results.json)

> [!NOTE]
> **Scope Notice**: This document records backend API session authorization and permission checks executed directly via bench script context (`frappe.set_user`). For real HTTP web session & browser cookie evidence (`sid`), refer to [docs/uat/2026-08-02-browser-authenticated-uat.md](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/2026-08-02-browser-authenticated-uat.md).

---

## 1. Verified Database Users & Roles

- **Manager User**: `hayrulloh@mail.com`  
  **Roles**: `Sales Manager`, `Sales Master Manager`, `Sales User`, `Accounts User`, `Customer`
- **Non-Manager User**: `fayzulloxoshimov61@gmail.com`  
  **Roles**: `Sales User`, `Accounts User`, `Customer` (Lacks `Sales Manager`, `System Manager`, `CRM Specialist`)
- **System Administrator User**: `Administrator`  
  **Roles**: `System Manager`, `Administrator`

---

## 2. Backend Authorization Verification Matrix

| Scenario | Session Context | API Endpoint | Expected Result | Actual Result / Status | Evidence |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Manager Cockpit Access** | `hayrulloh@mail.com` (Manager) | `stabler.api.crm_analytics.get_manager_cockpit_metrics` | `200 OK`, returns company-scoped metrics | `200 OK` (company: Mikas, deal_count: 13) | `backend_live_auth_results.json` |
| **RFQ Defaults Lookup** | `hayrulloh@mail.com` (Manager) | `stabler.api.sourcing.get_deal_rfq_defaults` | `200 OK`, returns deal item/supplier defaults | `200 OK` (deal: CRM-DEAL-2026-00005) | `backend_live_auth_results.json` |
| **Automation Rules Preview** | `hayrulloh@mail.com` (Manager) | `stabler.api.crm_automation.preview_crm_automation_rules` | `200 OK`, read-only preview | `200 OK` (summary: Previewed 0 rules) | `backend_live_auth_results.json` |
| **Non-Manager Cockpit Block** | `fayzulloxoshimov61@gmail.com` (Non-Manager) | `stabler.api.crm_analytics.get_manager_cockpit_metrics` | `403 PermissionError`, fail-closed | `403 PermissionError` ("Not permitted. CRM Manager role required.") | `backend_live_auth_results.json` |
| **Non-Manager Automation Block** | `fayzulloxoshimov61@gmail.com` (Non-Manager) | `stabler.api.crm_automation.preview_crm_automation_rules` | `403 PermissionError`, fail-closed | `403 PermissionError` ("Not permitted. CRM Manager role required.") | `backend_live_auth_results.json` |
