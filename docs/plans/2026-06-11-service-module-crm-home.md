# Service Module + CRM Home — Tech Spec

Date: 2026-06-11 · Status: approved direction, ready for implementation
Replaces the standalone `~/Documents/horeca` Next.js/React-Native/Node/Postgres app with a
Stabler SPA module backed by **native ERPNext doctypes**. Target tenant: `horeca.erpstable.com`
(own site, runs the same stabler app). Sales-manager CRM home ships for all CRM-enabled tenants.

Decisions made by Zafar:
- Reuse ERPNext/Frappe doctypes to the maximum; separate storage is last resort.
- All field events must produce financially correct ERP document chains.
- Everything lives in the Stabler SPA (no second web app).
- Postgres has real production tickets → migration required.

---

## 1. Data model — native doctypes + thin extension layer

### 1.1 Doctype mapping (Prisma → ERPNext)

| horeca Prisma model | ERPNext doctype | Notes |
|---|---|---|
| `Ticket` | **Issue** | Support module. `issue_type` = user-defined Issue Types; `priority` = Issue Priority; SLA via Service Level Agreement |
| `Assignment` | `_assign` (ToDo) + custom field | granular tech state → custom field, §1.2 |
| `ServiceReport` | **Maintenance Visit** | `maintenance_type` Scheduled/Unscheduled/Breakdown, per-serial purposes, `completion_status`, `customer_feedback` |
| `ReportPart` | **Stock Entry** (Material Issue) or items on the billing SI | §4 financial rules |
| `Photo` | **File** attachments on Issue / Maintenance Visit | BEFORE/AFTER/PROBLEM/PART via File `attached_to_field` or description prefix |
| signature | custom **Signature**-fieldtype field on Maintenance Visit | native fieldtype |
| `Equipment` (sold) | **Serial No** | customer, warranty_expiry_date, amc_expiry_date, maintenance_status — all native |
| `Equipment` (loaned/placed) | **Asset** + **Asset Movement** | machine stays on our books, depreciates, sits at customer Location; Serial No remains the service identity |
| `MaintenanceSchedule` | **Maintenance Schedule** (+ extension §1.2) | native rows: serial_no, periodicity, incharge; generates Maintenance Schedule Detail dates |
| warranty repair | **Warranty Claim** | native |
| recurring rent / AMC billing | **Subscription** / SI with deferred-revenue item | native |
| `User` roles ADMIN/DISPATCHER/TECHNICIAN | Frappe roles, §6 | |
| `SyncLog` (offline mobile) | — none — | parked, out of scope v1 |
| `Notification` | Frappe Notification / assignment emails | v1: in-SPA lists only |
| Customer hierarchy + geo | already done | `custom_parent_customer`, `custom_latitude`, `custom_longitude` on Customer (created by horeca bootstrap script — **keep these exact fieldnames**) |

CRM side (already live in Stabler): `CRM Lead`, `CRM Deal`, `CRM Deal Status` (Frappe CRM app).
**Pre-flight check:** confirm Frappe CRM app + ERPNext Support/Maintenance modules are installed
on horeca.erpstable.com (`bench --site horeca.erpstable.com list-apps`).

### 1.2 Custom fields (fixtures, idempotent patch)

All created via `Custom Field` fixtures guarded with `frappe.db.exists` (patches.txt runs pre-sync — see project rules).

| Doctype | Field | Type | Purpose |
|---|---|---|---|
| Issue | `custom_serial_no` | Link → Serial No | which machine the ticket is about |
| Issue | `custom_tech_state` | Select: `\nAccepted\nEn Route\nStarted` | technician granular state; blank when not in field |
| Issue | `custom_maintenance_visit` | Link → Maintenance Visit | completion record link |
| Maintenance Visit | `custom_issue` | Link → Issue | back-link |
| Maintenance Visit | `custom_customer_signature` | Signature | sign-off |
| Maintenance Visit | `custom_sales_invoice` | Link → Sales Invoice | billing link (§4) |
| Maintenance Visit | `custom_stock_entry` | Link → Stock Entry | parts consumption link (§4) |
| Maintenance Schedule Item | `custom_interval_days` | Int | every-N-days recurrence (Prisma INTERVAL mode) |
| Maintenance Schedule Item | `custom_day_of_month` | Int | FIXED_DOM mode |
| Serial No | `custom_placement` | Select: `Sold\nLoaned\nIn Stock` | ownership classification |
| Serial No | `custom_asset` | Link → Asset | set when Loaned |

**Property Setter:** Issue `status` options → `Open\nAssigned\nIn Progress\nOn Hold\nResolved\nClosed\nCancelled`
(maps the 9 Prisma statuses; ACCEPTED/EN_ROUTE/STARTED collapse into In Progress + `custom_tech_state`).

**Issue Types (fixtures):** Install, Inspection, Maintenance, Refill, Repair, Complaint.

### 1.3 Scheduler extension

Native Maintenance Schedule can't do every-N-days or fixed day-of-month. Add
`stabler/service/schedule_engine.py`:

- Daily scheduler job (`hooks.py scheduler_events.daily`): for active Maintenance Schedule Items
  carrying `custom_interval_days` or `custom_day_of_month`, append/extend
  Maintenance Schedule Detail rows for a rolling 90-day horizon. Idempotent
  (skip dates that already exist). Native periodicity rows untouched — ERPNext generates those.
- `next_due` per serial = MIN(scheduled_date) of unvisited future detail rows — computed in API, not stored.

Implementation note: appending Maintenance Schedule Detail rows to a *submitted* parent
requires either an `allow_on_submit` property setter on the child table field or direct
`frappe.get_doc(...).append + db_update` with docstatus guard — decide at implementation,
test cancel behavior. Alternative if it fights back: keep extension schedules as
docstatus 0 (never submit), since we read detail rows ourselves and don't rely on
ERPNext's submit-time generation for interval/DOM modes.

No new doctypes anywhere in this spec.

---

## 2. Migration (Postgres → ERPNext)

Principle: **operational history migrates as documents; financial history starts at opening balances.**
No backdated invoices/stock moves for pre-ERP events.

### 2.1 Pipeline

1. Export: one-off script in horeca repo (`scripts/export-for-erp.ts`) dumps Postgres →
   `migration/*.json` (customers already in ERPNext; export equipment, schedules, tickets,
   assignments, reports, photos as files + manifest).
2. Import: `stabler/service/migrate_horeca.py`, run via
   `bench --site horeca.erpstable.com execute stabler.service.migrate_horeca.run --kwargs "{'path': ...}"`.
   **Idempotent**: every record carries source id; importer skips existing
   (match on a `custom_horeca_id` Data field added to Issue, Maintenance Visit, Serial No — included in §1.2 fixtures pass).
3. Order: Items/Serial Nos (+ Assets for loaned) → Maintenance Schedules → Issues (original
   dates via `set_posting_time`-style direct db.set_value for creation/modified after insert) →
   Maintenance Visits (submitted) → File attachments (photos, signatures) → ToDo assignments.
4. Equipment ownership classification: CSV produced from Postgres export, reviewed by Zafar
   (column: sold / loaned), drives Serial No `custom_placement` + Asset creation. Loaned assets
   enter via Asset with `is_existing_asset=1` + opening values from the classification CSV.
   Sold machines that pre-date ERP: Serial No created with customer + delivery date, **no** backdated DN/SI.
5. Status mapping: NEW→Open, ASSIGNED→Assigned, ACCEPTED/EN_ROUTE/IN_PROGRESS→In Progress (+tech_state),
   ON_HOLD→On Hold, RESOLVED→Resolved, CLOSED→Closed, CANCELLED→Cancelled.
6. Dry-run mode (`dry_run=1`) prints counts and validation errors without writing.
7. Acceptance: row counts match per entity; 20-record spot check; sum of open tickets equal.

### 2.2 Cutover

Freeze Node API writes → final export/import delta (idempotency makes re-run safe) → repoint
users to Stabler SPA → Node API read-only for 30 days → decommission. RN technician app keeps
working only if Phase 5 (mobile repoint) is done; otherwise techs use SPA on mobile browser
(online-only) during the gap — explicitly accepted.

---

## 3. Backend — `stabler/api/service.py`

All endpoints: `@frappe.whitelist()`, `_require_company`, role gate per §6, parametrized SQL,
same style as purchasing.py. Listing endpoints take `limit` + standard date/party filters.

```
# Tickets
list_tickets(company, status?, issue_type?, technician?, customer?, from_date?, to_date?, limit=200)
  → name, subject, status, custom_tech_state, issue_type, priority, customer, customer_name,
    custom_serial_no, _assign, sla resolution_by + sla_failed flag, opening_date, modified
ticket_detail(name)            # + linked visit, files, comments, SLA timeline
create_ticket(company, customer, subject, issue_type, priority?, serial_no?, description?)
update_ticket_status(name, status, tech_state?)      # kanban drag + tech flow
assign_ticket(name, user)                            # ToDo via frappe.desk.form.assign_to
ticket_board_meta(company)     # columns (status options), issue types, priorities, technicians

# Visits / reports
create_visit_from_ticket(ticket, work_done, completion_status, serial_purposes?, signature?, feedback?)
  → creates+submits Maintenance Visit, back-links Issue, sets Issue → Resolved
visit_detail(name)
list_visits(company, from_date?, to_date?, technician?, customer?, limit=200)

# Schedules / calendar
list_schedules(company, customer?, serial_no?, active_only=1, limit=200)
create_schedule(company, customer, serial_no, service_type, periodicity?|interval_days?|day_of_month?,
                incharge?, start_date)               # wraps Maintenance Schedule + extension fields
calendar_feed(company, from_date, to_date, technician?)
  → merged: Maintenance Schedule Detail rows (planned) + open Issues with due dates (reactive)
    + Maintenance Visits (done); each row: date, kind, customer, serial_no, assignee, status, link
overdue_feed(company)          # detail rows past date with no visit; the triage source

# Equipment registry
list_equipment(company, customer?, placement?, search?, limit=200)
  → serial_no, item_code/name, customer, custom_placement, warranty_expiry_date,
    amc_expiry_date, maintenance_status, next_due (computed), open_issue_count
equipment_detail(serial_no)    # + asset link, schedule list, ticket history, visit history
register_equipment(...)        # Serial No (+ Asset when loaned) for new placements

# Map
map_pins(company)
  → per customer with custom_latitude/longitude: lat, lng, customer_name, parent,
    health: {overdue_visits, open_issues, sla_failed, ar_outstanding}
    (single SQL with subqueries; health drives pin color client-side)

# Billing bridges (§4)
create_invoice_from_visit(visit, items?)   # SI prefilled: customer, consumables/labor; links back
create_material_issue_from_visit(visit, items, warehouse)
unbilled_visits(company, from_date?, to_date?)
  → submitted visits with no custom_sales_invoice AND billable type — revenue-leak list

# CRM home
crm_home_summary(company)
  → {triage: {overdue_visits[], sla_failed_issues[], unbilled_visits[], expiring_amc[],
              stalled_deals[]},      # each list ≤10 rows + total count
     kpis: {visits_planned, visits_done, refill_compliance_pct, open_issues_by_priority,
            new_leads_30d, open_deals_value_by_currency, service_revenue_mtd},
     map_pins: [...]}                # one round-trip for the whole dashboard
```

`service_revenue_mtd` = SUM(base_grand_total) of SIs linked from visits this month.
`stalled_deals` = CRM Deal, open status, `modified` older than 14 days.
`expiring_amc` = Serial No where amc_expiry_date or warranty_expiry_date within 60 days.

---

## 4. Financial linkage rules (enforced in API + UI defaults)

| Event | Documents | Rule |
|---|---|---|
| Sell machine | SO → DN (serial) → SI | standard sales flow, Serial No gets customer automatically |
| Loan machine | Asset (+ Asset Movement to customer Location) | created by `register_equipment(placement="Loaned")`; optional Subscription for rent |
| Refill visit | Maintenance Visit + **SI with update_stock** (consumables) | visit-close drawer defaults to "Create invoice"; warehouse defaults to tech's van warehouse if `van_stock` maps one, else company default |
| Billable repair | Visit + SI (parts + labor items) | same drawer |
| Warranty/AMC repair | Warranty Claim + Visit + **Stock Entry Material Issue** | no SI; drawer switches default when ticket type = Repair and serial under warranty/AMC (server decides, UI shows "Under warranty — parts will be expensed") |
| AMC sale | SI with deferred-revenue service item; set serial `amc_expiry_date` | manual v1; renewal surfaced on CRM home |

Guardrail: `create_visit_from_ticket` for billable types returns `needs_billing=1`; the SPA keeps
the visit in the **Unbilled** list (CRM home triage + Tickets page filter) until an SI or Stock
Entry is linked. Nothing blocks closure — we surface the leak, not bureaucratize the flow.

---

## 5. Frontend — module `service`, pages under `/service`

Parent route `meta: { module: "service" }` (hard rule). Tabs on `ServiceHome.vue` (clone module-home pattern):
Dashboard · Tickets · Calendar · Equipment · Map.

| Page | Spec |
|---|---|
| `ServiceDashboard.vue` | = **CRM home for sales manager**, §5.1 |
| `Tickets.vue` | Kanban, **clone Deals.vue** (1024 L donor: drag-drop columns, count chips, drawer). Columns = Issue statuses; card: subject, customer, type badge, priority dot, SLA countdown (red when `resolution_by < now`), assignee avatar, serial chip. Filters: type, technician, customer. Detail drawer: timeline, files, assign, status actions, **Close visit** flow (work done, parts, signature pad, feedback) → billing step per §4 |
| `ServiceCalendar.vue` | Month grid on existing `CalendarMonth.vue` + week list. Source `calendar_feed`. Color by kind (planned/reactive/done). Click → day panel (DayPlanPanel equivalent): rows grouped by technician. Drag-to-reschedule detail row = update scheduled_date (API: `reschedule_detail(name, date)` — add to §3) |
| `Equipment.vue` | Registry list: serial, item, customer, placement badge, next due (formatDate), warranty/AMC chips (red ≤60 d), open issues. Drawer: full history (schedules, tickets, visits), actions: new ticket, new schedule. Register-placement form (sold → links to existing DN flow; loaned → creates Asset) |
| `ServiceMap.vue` | **MapLibre GL + OSM tiles** (decision: FOSS, no key, fine UZ coverage; Yandex rejected — JS API commercial licensing risk). Pins from `map_pins`, colored: red = overdue visit or SLA-failed issue, yellow = due ≤7 d or open issue, green = healthy. Pin click → side card (BranchDetail equivalent): equipment list, next visits, open tickets, AR outstanding, button "plan route" → ordered list + deep links to Yandex Maps/Google Maps navigation URL (no in-app routing engine v1) |

New deps: `maplibre-gl` (pin via package-lock, no `^`). No other additions — calendar/kanban/charts already in-house.

### 5.1 CRM home / Service dashboard layout

Desktop: 3 rows. (KpiCard, ApexChart, AgingTable patterns all exist.)

1. **KPI cards:** Visits done/planned MTD · Refill compliance % · Open tickets (URGENT count red) ·
   Unbilled visits (count + base-currency sum) · Service revenue MTD · Open deals value.
2. **Needs attention** (⅔ width): tabbed triage table — Overdue visits / SLA-failed tickets /
   Unbilled visits / AMC & warranty expiring / Stalled deals. Rows link to the relevant drawer.
   **Map widget** (⅓ width): mini ServiceMap, click-through to full page.
3. **Trend strip:** visits + revenue by week (ApexChart), tickets opened vs resolved.

Data: single `crm_home_summary` call. On tenants without `service` enabled, the same
CrmHome shows only pipeline cards + stalled deals (module-gated card rendering — same SPA everywhere).
Pipeline cards link to existing `/crm/deals` kanban.

Placement decision: this page is `ServiceDashboard.vue` at `/service` (landing tab) **and**
`/crm` gains a "Dashboard" tab rendering the same component (shared SFC, two routes). One
component, no fork.

---

## 6. Module registration, roles, permissions

- `organization.py`: `_MODULE_FIELDS["service"] = "enable_service"`;
  `_MODULE_ROLES["service"] = ["Sales Manager", "Support Team", "Maintenance User", "Maintenance Manager"]`.
- `stabler_company_modules` doctype: add `enable_service` Check, **default "0"** (only HoReCa
  tenants turn it on; per project rules the go-live default comes from the field default, no backfill patch).
- Role mapping from Prisma: ADMIN → System Manager/Stabler Admin (bypass), DISPATCHER →
  Maintenance Manager + Support Team, TECHNICIAN → Maintenance User. Verify native doctype perms
  (Issue: Support Team; Maintenance Visit/Schedule: Maintenance User/Manager; Serial No: Stock roles —
  grant read to service roles via DocPerm fixtures if missing, idempotent patch).
- UX gate only — real security stays in `has_permission` server-side (project rule).

## 7. Cross-cutting (hard rules checklist)

- No Desk links; every doc surface is an SPA drawer/page.
- MoneyInput for amounts; DateInput + formatDate/formatDateTime everywhere (calendar grid included).
- Tables plain `.table`; currency cells `font-monospace`.
- i18n: all five langs (en, ru, uz, uzc, tr) harvested + filled pre-merge. Core glossary —
  Ticket: Заявка / Murojaat; Visit: Выезд / Tashrif; Refill: Дозаправка / To'ldirish;
  Equipment: Оборудование / Uskuna; Warranty: Гарантия / Kafolat (translator confirms uzc).
- Patches: custom fields + Issue property setter + Issue Types as idempotent pre-sync-safe patch
  (guard `frappe.db.exists("Custom Field", …)`); no new columns on stabler doctypes → no
  post_model_sync concerns.
- Commits: explicit paths; translations as five CSVs; trailer per project rules.
- Deploy: this ships to the shared bench too (anjan has `enable_service=0`, invisible). Standard
  rsync procedure; `bench restart` required (py changes); migrate needed (fixtures/patch).

## 8. Phasing & acceptance

| Phase | Contents | Acceptance |
|---|---|---|
| **P1** | §1.2 fields/fixtures + `service.py` tickets endpoints + Tickets kanban page + module registration | Create→assign→drag→resolve a ticket wholly in SPA on horeca site; SLA countdown renders; module invisible on anjan |
| **P2** | Migration (§2) | Counts match; spot checks pass; open-ticket sum equal; re-run = no dupes |
| **P3** | Schedules + scheduler job + Calendar page + visit-close flow with billing drawer (§4) | 21-day interval schedule generates rolling dates; closing a refill visit creates SI from van warehouse; warranty repair produces Stock Entry, no SI |
| **P4** | Equipment registry + `crm_home_summary` + Dashboard (CRM home) | Unbilled visit appears in triage within one reload; AMC expiring list correct; dashboard ≤1 s on 1k serials (single round-trip) |
| **P5** | Map page + map widget + mobile repoint of RN tech app to whitelisted API (online-only) | Pins colored correctly vs triage data; tech can accept→en-route→start→close from phone |

Each phase = one PR, independently deployable. P2 runs only on horeca site.

## 8b. Convergence contract & decommission (added 2026-06-12, Zafar's directive)

**One codebase.** The stabler app is the single product; horeca features arrive as Service-module
pages. The horeca Next.js web app, Node API, and Postgres are terminal. Only the RN technician
app survives — as a thin client of stabler's whitelisted API, no backend of its own.

| Gate | Event | Action |
|---|---|---|
| now | — | Feature-freeze horeca web + Node API (bugfix only); put horeca dir under git |
| P2 run | historical migration done | ERPNext = system of record; Postgres = feeder only |
| P3 ships | visit-close billing live in SPA | **Kill switch 1:** disable Node approval-sync; Postgres read-only; web users fully on Stabler |
| P5 ships | RN app repointed to stabler API | **Kill switch 2:** decommission Node API + Postgres after 30-day read-only period |

Rules during the bridge window (P2→P3): no new Postgres tables/endpoints; Node sync writes are
tagged (`custom_horeca_id`) so migration re-runs stay idempotent; any document created by both
paths is a bug, caught by the nightly integrity check (duplicate horeca_id → alert).
Salvage list before decommission: MapView/route-optimization logic (P5 reference), i18n strings,
korzinka/bellissimo seed data (already migrated).
`ignore_mandatory=True` is migration-only — the P3 visit-close endpoint must satisfy mandatory
fields properly.

## 9. Out of scope (explicit)

- Offline mobile sync (SyncLog equivalent) — revisit after P5 usage data.
- In-app route optimization (deep links to external nav only).
- Push notifications (assignment emails native; push needs FCM plumbing — later).
- Automated AMC renewal invoicing (manual SI v1).
- Merging SFA `equipment`/`equipment_repair_request` with the service stack — boundary documented:
  SFA = marketing assets at outlets; Service = serialized sold/loaned machines. Do not merge in this iteration.
- Frappe Helpdesk (HD) app — not installed, not used; Issue is sufficient.
