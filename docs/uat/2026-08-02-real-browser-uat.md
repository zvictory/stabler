# Real Playwright Browser SPA UAT Evidence Report

**Date**: 2026-08-02  
**Target Web Application**: `http://localhost:8000/stabler` (Site: `stabler`)  
**Playwright Test Harness**: [docs/uat/scripts/browser_real_uat_harness.js](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/scripts/browser_real_uat_harness.js)  
**Evidence Artifact Directory**: [docs/uat/evidence/2026-08-02-browser-final/](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/)  
**JSON Assertion Matrix**: [docs/uat/evidence/2026-08-02-browser-final/browser_real_uat_results.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/browser_real_uat_results.json)  
**Network Log Summary**: [docs/uat/evidence/2026-08-02-browser-final/browser_network_summary.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/browser_network_summary.json)  
**Console Log Summary**: [docs/uat/evidence/2026-08-02-browser-final/browser_console_summary.json](file:///Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/browser_console_summary.json)

---

## 1. Browser Test Execution Overview

Real browser automation testing was performed using Playwright Chromium (`v1.62.1`) against the local bench site (`http://localhost:8000`). Authentication session cookies were established directly in browser context via standard login API calls reading UAT credentials securely from environment variables (`STABLER_UAT_MANAGER_PASS`, `STABLER_UAT_NONMANAGER_PASS`).

All HTTP request headers, authorization tokens, passwords, and cookie values in evidence files are 100% redacted.

---

## 2. Browser Assertion Matrix

| # | Assertion Description | User Context | SPA Route / URL | Result | Artifact Evidence |
| :-: | :--- | :--- | :--- | :---: | :---: |
| **1** | Manager Session Login API | `hayrulloh@mail.com` | `POST /api/method/login` | **PASS** | `browser_real_uat_results.json` |
| **2** | Portfolio SPA Route Render & DOM Content | `hayrulloh@mail.com` | `/stabler#/tender/portfolio` | **PASS** | `01_manager_portfolio.png` |
| **3** | Sourcing Workspace Navigation & RFQ Defaults | `hayrulloh@mail.com` | `/stabler#/tender/portfolio` | **PASS** | `02_manager_sourcing_workspace.png` |
| **4** | RFQ Unsaved / Dirty State User Input Preservation | `hayrulloh@mail.com` | `/stabler#/tender/portfolio` | **PASS** | `03_rfq_dirty_state_preservation.png` |
| **5** | Deal 360 Workspace Route & DOM Render | `hayrulloh@mail.com` | `/stabler#/crm/deals/CRM-DEAL-2026-00005` | **PASS** | `04_manager_deal_360.png` |
| **6** | Manager Cockpit Analytics Route & DOM Render | `hayrulloh@mail.com` | `/stabler#/crm/cockpit` | **PASS** | `05_manager_cockpit.png` |
| **7** | Cockpit Hard Refresh Route Preservation | `hayrulloh@mail.com` | `/stabler#/crm/cockpit` (Reload) | **PASS** | `06_cockpit_hard_refresh.png` |
| **8** | Non-Manager Session Login API | `fayzulloxoshimov61@gmail.com` | `POST /api/method/login` | **PASS** | `browser_real_uat_results.json` |
| **9** | Non-Manager Cockpit Access Blocked / HTTP 403 Rejection | `fayzulloxoshimov61@gmail.com` | `/stabler#/crm/cockpit` | **PASS** | `07_non_manager_cockpit_blocked.png` |

---

## 3. Screenshots Evidence

- **Step 1 — Manager Portfolio SPA Route**:  
  ![Manager Portfolio](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/01_manager_portfolio.png)

- **Step 2 — Manager Sourcing Workspace**:  
  ![Sourcing Workspace](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/02_manager_sourcing_workspace.png)

- **Step 3 — RFQ Dirty State User Input Preservation**:  
  ![RFQ Dirty State](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/03_rfq_dirty_state_preservation.png)

- **Step 4 — Deal 360 Workspace**:  
  ![Deal 360 Workspace](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/04_manager_deal_360.png)

- **Step 5 — Manager Cockpit**:  
  ![Manager Cockpit](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/05_manager_cockpit.png)

- **Step 6 — Cockpit Hard Refresh Route Preservation**:  
  ![Cockpit Hard Refresh](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/06_cockpit_hard_refresh.png)

- **Step 7 — Non-Manager Cockpit UI Blocked**:  
  ![Non-Manager Cockpit Blocked](/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final/screenshots/07_non_manager_cockpit_blocked.png)

---

## 4. Empirical Network & Role Authorization Verification

- **Manager (`hayrulloh@mail.com`)**:
  - `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` -> **200 OK**
  - `POST /api/method/stabler.api.organization.boot` -> **200 OK**
  - `POST /api/method/stabler.api.crm_email.list_email_triage_queue` -> **200 OK**

- **Non-Manager (`fayzulloxoshimov61@gmail.com`)**:
  - `POST /api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics` -> **403 Forbidden** (`"PermissionError: Not permitted. CRM Manager role required."`)
