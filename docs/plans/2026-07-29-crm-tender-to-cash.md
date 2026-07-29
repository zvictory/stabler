# Mikas CRM Tender-to-Cash Implementation Plan

## Global constraints

- Keep every workflow inside the Stabler SPA; never link to Frappe Desk.
- Require and enforce the selected company on every CRM list, detail, report, activity, and mutation API.
- Apply record-level permissions and prevent arbitrary client payloads from updating server-owned fields.
- Preserve separate acquisition, tender, and contract-execution state machines linked by one commercial record spine.
- Use test-driven development and keep existing company data isolated.
- Pilot new navigation and workflow behavior for Mikas without changing unrelated companies.

## Task 1: Secure CRM API company scope and mutable fields

- Add behavior tests proving CRM lead/deal lists require a selected company, filter records to that company, and do not expose cross-company AR.
- Add behavior tests proving lead/deal mutations accept only explicit editable fields and set company server-side.
- Update the CRM API with shared company validation, permission-aware list queries, company-scoped reports/metrics, company-scoped AR, and field whitelists.
- Preserve current response shapes where possible; missing company must fail loudly instead of falling back across allowed companies.

## Task 2: Add daily-work data model and transition history

- Add patches for Deal `deal_type`, next-action fields, stage-entry/won/lost timestamps, loss reason, and forecast category.
- Add immutable CRM Activity and CRM Stage Event records with company and reference fields.
- Add server APIs for activity creation/completion, activity timeline, and controlled deal transitions.
- Require owner and dated next action for open deals after the migration grace mechanism is enabled.

## Task 3: Add Lead-to-Deal conversion and My Day APIs

- Add idempotent Lead-to-Deal conversion with duplicate candidates based on normalized phone, email, tax ID, and organization.
- Preserve source attribution and link the converted records.
- Add company-scoped My Day queues for overdue, today, no-next-action, stale, closing-soon, unassigned, and assigned-to-me.
- Add saved personal/team CRM views with server-side ownership and company scoping.

## Task 4: Build the Daily CRM and hybrid Deal 360 UI

- Add `/crm/workspace`, keep `/crm/deals`, and add `/crm/deals/:name`.
- Build My Day queues and shared Kanban/Table filters.
- Open a route-addressable Deal 360 side panel from cards and provide a full workspace route for deep work.
- Show owner, next action, age-in-stage, deadline, risk, timeline, stakeholders, documents, tender summary, and compact ERP/finance snapshot.
- Add keyboard/mobile stage movement and optimistic rollback through the controlled transition API.

## Task 5: Connect tender lifecycle and contract execution

- Add explicit standard/tender transition behavior and create tender intake on transition.
- Add bid/no-bid, submission, award, loss-reason, document, pricing, and margin gates.
- Make won-to-Customer-to-Sales-Order handoff idempotent, auditable, and retryable.
- Keep `/tender/board` as the Sales Order execution board and add bidirectional SPA drill-down through Deal 360.

## Task 6: Add two-way email and controlled automation

- Send email from Deal 360 through Frappe Communication/Email Account.
- Match replies by thread, participants, and references; route ambiguous messages to a triage queue.
- Add audited rules for stage-entry tasks, SLA reminders, overdue escalation, stale/no-next-action alerts, and handoff retries.
- Ensure retries do not duplicate tasks, email, activities, customers, or orders.

## Task 7: Add manager cockpit and trusted intelligence boundary

- Add drillable weighted forecast, commit/best-case, aging, slippage, conversion, activity coverage, workload, and win/loss reports.
- Ensure board, table, KPI, and drill-down use the same company-scoped filter contract.
- Add human-approved interfaces for future document summaries, deadline extraction, risk explanation, and next-best-action suggestions.
- Do not let AI mutate financial values, contractual stages, or approvals.

## Final verification

- Run all focused CRM/Tender Python tests, the complete JavaScript suite, lint, and build.
- Verify cross-company isolation, mutation protection, idempotent handoffs, filter parity, email triage, automation auditability, keyboard/mobile interactions, and no Desk redirects.
- Review the complete branch before integration and production rollout.
