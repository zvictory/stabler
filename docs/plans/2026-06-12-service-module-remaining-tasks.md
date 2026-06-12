# Service Module Remaining Tasks

Date: 2026-06-12
Status: in progress

## Done

- [x] Service schema custom fields for Issue, Maintenance Visit, and Serial No.
- [x] Ticket board with create, assign, status, technician state, filters, detail drawer.
- [x] Close Visit action that creates a submitted Maintenance Visit and resolves the Issue.
- [x] Backend billing bridge APIs for Sales Invoice, Material Issue, and unbilled visit queue.

## Next Tasks

- [x] Service Billing Queue UI
  - Show submitted, billable Maintenance Visits without linked Sales Invoice or Stock Entry.
  - Let users add item rows with item search, qty, warehouse, and MoneyInput rate/basic rate.
  - Create draft Sales Invoice for billable service revenue.
  - Create submitted Material Issue for covered repair/parts consumption.

- [x] Visit list/report
  - Add `list_visits` backend endpoint.
  - Add visit list page with date, customer, technician, issue type, and linked billing document filters.

- [x] Service Calendar
  - Add calendar feed endpoint.
  - Build calendar page using `CalendarMonth.vue`.
  - Add reschedule API for planned service rows.

- [ ] Equipment Registry
  - List Serial Nos by customer, item, placement, warranty/AMC, next due, open issue count.
  - Drawer history: schedules, tickets, visits, invoices, stock issues.
  - Actions: new ticket and new schedule from equipment.

- [ ] CRM Home / Service Dashboard
  - Replace Service dashboard placeholder with manager cockpit.
  - KPIs: open tickets, overdue SLA, due planned visits, unbilled visits, revenue leakage.
  - Drilldowns stay inside Stabler; no Desk redirects.

## Current Implementation Slice

Started with Service Billing Queue UI because backend support already exists and it closes the revenue leakage path introduced by completed service visits.
