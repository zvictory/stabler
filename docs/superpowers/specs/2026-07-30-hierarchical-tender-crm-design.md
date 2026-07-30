# Hierarchical Tender CRM and Role Workspaces — Approved Design

Date: 2026-07-30  
Status: Approved for presentation  
Selected direction: Tender Master → CRM Deal/Lot → Role-derived workspaces

## 1. Outcome

Stabler will present tenders at two CRM levels without creating separate CRM
systems:

1. The Tender CRM shows one card per complete tender.
2. Opening a tender shows a second Kanban with one CRM Deal per lot.
3. Opening a lot shows its sourcing, execution, document, and finance workspace.

The same records feed role-specific dashboards for management, CRM, sourcing,
customs, logistics, and finance. Dashboards and Kanban boards are projections of
source documents; they do not store duplicate business state.

## 2. Record Hierarchy

### Tender Master

A new parent record represents the published tender as a whole. It owns shared
information:

- company, tender number, buyer, source, publication and submission dates;
- tender-level team, owner, currency, and estimated total value;
- common announcement, specification, guarantee, and contract documents;
- aggregate lot counts, values, deadlines, risks, and results.

The parent is not used for quotations, bid pricing, purchase orders, or
financial postings.

### CRM Deal / Lot

The existing CRM Deal remains the transactional unit for one lot and gains a
required `parent_tender` link for tender deals. It owns:

- lot number, item scope, quantity, expected value, deadline, and assigned user;
- GO decision, RFQ, supplier quotations, sourcing decision, and bid pricing;
- bid submission and lot result;
- linked sales, purchase, customs, logistics, and finance documents.

Existing deal-linked fields and APIs remain lot-scoped during migration.

### Document scope

Documents are explicitly scoped as `tender` or `lot`.

- Tender-scoped documents are visible from every child lot.
- Lot-scoped documents remain attached to one CRM Deal.
- Parent totals aggregate child documents but never copy them.
- Every list and drill-down preserves the active company, role, period, parent
  tender, and lot filters.

## 3. Navigation and Boards

### Level 1 — Tender CRM

The top-level board shows complete tenders in derived lanes:

`Preparation → Active → Awaiting Result → Partial Result → Completed`

Parent state is calculated from child lots:

- Preparation: no lot has advanced beyond intake/GO.
- Active: at least one open lot is in sourcing or pricing.
- Awaiting Result: at least one lot was submitted and none has a result.
- Partial Result: terminal and non-terminal lot results coexist.
- Completed: every lot is won, lost, cancelled, or closed.

Each card shows total/open/submitted/won/lost lots, aggregate value, earliest
deadline, policy-gap count, risk count, and responsible team.

### Level 2 — Lot CRM

Opening a parent card filters the existing tender pipeline to its child lots:

`New → GO → Sourcing → Priced → Submitted → Won / Lost`

Each lot card shows lot number, item summary, value, deadline, risk, assignee,
quotation/country coverage, sourced cost, and bid price.

### Level 3 — Lot workspace

Opening a lot provides these tabs:

1. Overview
2. RFQ and Supplier Quotations
3. Evaluation and Award
4. Bid Pricing
5. Purchasing
6. Customs
7. Logistics
8. Finance
9. Documents
10. Activity and Approval History

Breadcrumbs follow:

`Tender CRM → Tender → Lot → Workspace tab → Document`

### Pre-award and post-award split

The CRM pipeline ends at Won/Lost. A won lot links to the existing execution
board for procurement, receipt, delivery, invoicing, payment, and closure. The
CRM card retains a live execution summary without duplicating execution stages.

## 4. Role Projections

All role boards are derived from document and assignment state. Moving a card in
one role board must not create a second, conflicting tender stage.

| Role | Default level | Derived queue |
|---|---|---|
| Director | Tender CRM | portfolio, risk, participation, win, margin |
| CRM / Sales | Tender then lot | intake, GO, pricing, submission, result |
| Sourcing | Assigned lots grouped by tender | assigned, RFQ, collecting, evaluation, approval, PO handoff |
| Customs | Won lots | documents missing, ready, declared, inspection, released |
| Logistics | Won lots | planning, pickup, transit, border, delivery, acceptance |
| Finance | Tender and lot | document pending, posted, due, paid/collected, margin variance |

Backend responses enforce company scope, DocType permission, tender-module
access, role view, assignment scope, and finance authorization. Hiding a tab in
the frontend is not an authorization control.

## 5. Sourcing and Document Chain

The target chain is:

```text
Tender Master
└── CRM Deal / Lot
    ├── Request for Quotation
    ├── Supplier Quotations
    ├── Tender Sourcing Decision
    ├── Bid Pricing and Submission
    ├── Purchase Order → Receipt → Purchase Invoice → Supplier Payment
    ├── Customs / Import Documents
    └── Sales Order → Delivery Note → Sales Invoice → Customer Payment
```

`Tender Sourcing Decision` is the auditable award record. It stores the selected
quotation, normalized commercial comparison, technical result, selection
reason, approver, timestamp, and any policy exception. “Cheapest quotation” and
“selected quotation” remain separate facts.

## 6. Dashboard Aggregation

Dashboard data is calculated server-side from the same permission-filtered
record set used by drill-down lists.

- Parent KPIs aggregate child lots once.
- Lot KPIs aggregate linked documents once.
- Currency values use company-currency amounts for cross-supplier comparison.
- Draft, cancelled, expired, and policy-exception records remain distinguishable.
- Every KPI response includes enough filter context to open the exact supporting
  list.

No dashboard-specific table stores copied counts or totals.

## 7. Current and Target Presentation

The interactive presentation includes a `Today / Target System` switch.

Today marks existing capabilities:

- general CRM Deal table/Kanban;
- role-aware Tender navigation and dashboard;
- director, sourcing, customs, and logistics views;
- lot-scoped overview, Vendor & PO, delivery, document chain, and authorized
  finance content;
- read-only supplier quotation comparison.

Target System adds:

- Tender Master and parent CRM board;
- parent-to-lot drill-down;
- RFQ creation and response capture;
- supplier quotation history in the supplier panel;
- normalized evaluation and auditable award;
- role-derived Kanban queues;
- complete document and approval chain.

## 8. Failure and Empty States

- A tender without lots opens an empty lot board with a Create Lot action.
- A lot without RFQs remains in sourcing preparation and cannot satisfy quote
  policy.
- Missing parent links appear in a migration queue and are not silently grouped.
- Unauthorized finance data is omitted from payloads.
- Partial API failure keeps unaffected sections visible and identifies the
  failed section.
- Aggregate cards show data freshness and never infer missing historical events.

## 9. Acceptance Criteria

- One tender can contain multiple independent lot CRM Deals.
- A lot belongs to exactly one Tender Master.
- Parent counts and values equal the visible child-lot drill-down.
- Selecting a parent opens only its lots; selecting a lot opens only its
  documents.
- Role changes alter KPIs and work queues without changing the master lifecycle.
- Won lots link to execution while remaining traceable from CRM.
- Tender- and lot-scoped documents are visually and permission-wise distinct.
- Supplier quotation evaluation uses company currency and records an explicit
  selection decision.
- Desktop and mobile layouts preserve breadcrumb and drill-down context.
- No route links to Frappe Desk.

## 10. Delivery Sequence

1. Validate the interactive presentation.
2. Add Tender Master and parent-link migration.
3. Add parent CRM aggregation and drill-down.
4. Complete RFQ, quotation, evaluation, award, and supplier-panel workflows.
5. Add role-derived queues and permission contracts.
6. Complete execution/document aggregation and end-to-end tests.
