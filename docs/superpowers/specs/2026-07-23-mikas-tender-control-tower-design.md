# MIKAS Tender Control Tower — Approved Design

Date: 2026-07-23
Status: Approved for implementation
Selected direction: A + A1 + S1 + P1

## 1. Outcome

MIKAS gets a role-aware tender operations control tower. The dashboard answers:

1. How many tenders entered, advanced, were submitted, and were won?
2. Which tenders require attention now?
3. Where is each won tender in PO, receipt, invoice, delivery, and finance execution?
4. Which vendor quotation and landed-cost PO is economically best?

All navigation and CRUD remain inside the Stabler SPA. No `/app/...` Frappe Desk links are allowed.

## 2. Approved Information Architecture

### Sidebar

`Tender` becomes a collapsible Operations group:

- Control Tower
- My Tenders
- Vendor & PO
- Customs
- Logistics

Children are filtered by the existing tender view roles:

- director: Control Tower
- sourcing: My Tenders, Vendor & PO
- declarant: Customs
- logist: Logistics

The current visibility bug is caused by `Sidebar.vue` creating the `tender` item but omitting it from every `sections` group. The implementation must first restore Tender under Operations, then add role-aware children.

### Routes

- `/dashboard`: role-adaptive Control Tower when the tender module is enabled
- `/tender/director`: full portfolio
- `/tender/my-tenders`: assigned sourcing work
- `/tender/po-control?deal=...`: dedicated Tender Workspace
- `/tender/customs`: declarant queue
- `/tender/logistics`: logistics queue

Existing `/tender/po-control` links remain valid. It becomes the workspace shell rather than being replaced by an incompatible route.

## 3. Executive Precision Visual Language

- Existing navy Stabler sidebar is retained.
- Content background: cool neutral, not pure white.
- One primary accent: desaturated Stabler blue.
- Amber and red are reserved for warning and risk.
- Monetary and percentage values use monospace.
- Major groups use thin borders and negative space; cards are used only where hierarchy requires a surface.
- Existing Tabler icons are used. No icon or chart dependency is added.
- Charts use accessible inline SVG with text alternatives.
- Motion is limited to opacity and transform transitions, and respects `prefers-reduced-motion`.

## 4. Control Tower Layout

### Header

- Title and role context
- Period selector with Month, YTD, and custom range
- Manager filter for oversight roles
- Last updated time and Refresh

Filter state is stored in the route query and restored after drill-down.

### KPI strip

- Portfolio value
- Verified participation and win rate
- Tenders at risk
- Weighted margin

Every KPI is clickable and opens a filtered in-SPA list. No synthetic overall completion percentage is shown.

### Three-month trend

Inline SVG chart shows:

- submitted tender count
- won tender count
- won contract value

The chart uses monthly server aggregates and never fabricates missing historical evidence.

### Attention panel

Ranked by severity and due date:

- overdue bid deadline
- missing required tender evidence
- missing vendor quotation policy
- delayed receipt or delivery
- customs/TNVED gap
- draft or overdue PI/SI

Clicking an item opens the relevant tender workspace tab.

### Execution flow

Won tenders move through:

```text
Won → Contract/SO → Purchase/PO → Receipt/PR → Invoice/PI-SI → Delivery/DN
```

Counts and progress come from ERPNext documents:

- PO: `per_received`, `per_billed`
- SO: `per_delivered`, `per_billed`
- PI/SI: `docstatus`, `status`, `outstanding_amount`

### Portfolio preview

Rows display:

- tender and lot
- lifecycle status
- PO receipt/billing progress
- SO delivery/billing progress
- contract–procurement spread
- risk state

The entire row is keyboard-accessible and opens `/tender/po-control?deal=...`.

## 5. Dedicated Tender Workspace

The existing PO control page becomes a four-tab workspace:

### Overview

- tender intake and evidence readiness
- lifecycle timeline
- buyer, deadline, manager, result
- contract and procurement summary

### Vendor & PO

Combines current sourcing and PO-control capabilities:

- Supplier Quotations compared in company currency
- quotation count and country-policy checks
- selected vendor marker
- PO goods total
- planned charges
- actual ledger-backed charges
- landed cost
- delta from cheapest
- receipt and billing progress

“Cheapest quote” and “cheapest landed cost” remain separate facts.

### Delivery

- PO receipt progress
- Purchase Receipts
- Sales Order delivery progress
- Delivery Notes
- delayed quantities and next due action

### Finance

- Purchase Invoices and Sales Invoices
- submitted/draft/unpaid status
- AP, AR, and outstanding amounts
- planned margin versus realized margin
- guarantee exposure and net remaining when permission allows

Finance data is excluded from responses for unauthorized roles, not merely hidden in Vue.

## 6. Data Contract

Extend `tender_dashboard(company, from_date, to_date)` without breaking existing keys:

- `trend[]`: month, submitted, won, won_value
- `portfolio_preview[]`: deal, label, lot, status, risk, PO/SO progress, spread
- `attention[]`: add destination tab and evidence text
- `execution`: add partial progress totals and invoice status counts

Add or extend one tender-scoped workspace endpoint:

```text
tender_workspace(deal)
```

It returns permission-filtered sections:

- overview
- sourcing
- purchase_execution
- sales_execution
- finance, only when authorized

Existing quotation, PO-control, landed-cost, and intake endpoints remain valid during migration.

Every query must enforce:

- active company scope
- Frappe DocType permission
- tender module gate
- role view gate

## 7. States and Accessibility

- Layout-matching skeletons for dashboard and workspace
- Empty states explain how to create or link data
- Inline error panels preserve selected filters and provide retry
- Full keyboard navigation and visible focus
- Charts include accessible labels and a tabular equivalent
- Color is never the only status signal
- Desktop: asymmetric 8/4 layout
- Tablet: two-column where safe
- Mobile: single-column, workspace tabs scroll horizontally

## 8. Testing

### Backend

- company, module, role, and finance-exclusion tests
- May/June/July monthly trend calculations
- partial PO/SO progress calculations
- draft/submitted/unpaid PI/SI classification
- quotation versus landed-cost ranking

### Frontend

- Tender sidebar visibility and role-filtered children
- filter restoration after drill-down
- SVG chart values and accessible fallback
- loading, empty, error, and reduced-motion states
- workspace tab routing
- 1440 px, 1024 px, and mobile layouts

### Live acceptance

Using the `[TEST-E2E]` data:

- May shows completed PO/SO and submitted PI/SI
- June shows PO 60% and SO 40%
- July shows open PO/SO and draft PI/SI
- June Vendor & PO shows five quotations and the selected supplier

## 9. Non-goals

- No Frappe Desk redirects
- No new chart or icon dependency
- No tenant-name conditionals
- No replacement of ERPNext financial or stock truth with custom status fields
- No payment automation in this scope

## 10. Acceptance Criteria

Within ten seconds, a director can identify:

1. portfolio value and win rate,
2. tenders currently at risk,
3. PO/SO execution progress,
4. the selected vendor and landed-cost comparison,
5. the next operational action.

The Tender group is visible in the sidebar whenever the tender module is enabled and contains only role-permitted destinations.
