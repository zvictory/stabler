# CI-Centred Logistics, Customs, GRN and Landed Cost Workspace

## Status and Decision Record

This design supersedes the standalone Commercial Invoice Create/Open GRN
design. It was approved after inspecting the current Stabler code, the live
MSA tenant, and the reachable MSAERP GRN implementation.

Locked business decisions:

- The Commercial Invoice (CI) is the operational owner of logistics and
  customs activity.
- Containers linked to one CI travel as one sea shipment and share its status
  and dates.
- A typical CI has three containers whose cargo is transferred at the Iran
  port into four trucks.
- Trucks travel to Uzbekistan independently and keep separate road statuses.
- No container-to-truck product allocation is recorded.
- Container packing lists describe expected product quantities.
- GRN expected quantities are the item-level aggregate of all linked
  Container packing lists, not a copy of the CI commercial lines.
- Products, boxes and kilograms are physically counted when each truck arrives
  at the Uzbekistan warehouse.
- Every truck has its own Truck Receipt and native ERPNext Purchase Receipt.
- One CI may have multiple Customs Declarations / GTDs.
- All four trucks remain visible in one GRN supervisor window while only one
  selected Truck Receipt is edited and submitted at a time.

## Goals

1. Make the CI detail route the self-contained Imports workspace for sea
   shipment, containers, customs, trucks, receiving, GRN and landed cost.
2. Remove duplicate voyage/status ownership between CI and Container.
3. Preserve independent truck tracking after the Iran-port transload.
4. Combine MSAERP's useful product-by-truck matrix with Stabler's safer
   per-truck QC, submission and ERPNext-native stock flow.
5. Keep all stock and financial truth in native ERPNext documents.
6. Migrate existing records without silently resolving contradictory legacy
   statuses, dates or payment records.

## Non-Goals

- No container-to-truck allocation or origin tracing is added.
- No Frappe Desk `/app/...` link or redirect is introduced.
- No Django-style local StockEntry, stock ledger, GL or landed-cost engine is
  copied into Stabler.
- No automatic submission of Landed Cost Vouchers or other financial
  documents is introduced.
- No bulk production GRN creation is performed by the feature deployment.
- Existing legacy fields are not destructively removed in the first rollout.

## Aggregate Ownership

### Commercial Invoice

The CI owns:

- shared sea-shipment lifecycle;
- vessel, voyage, bill of lading, ports and common voyage dates;
- linked Containers;
- one or more Customs Declarations / GTDs;
- linked Trucks and the expected truck set;
- the single GRN Checklist;
- landed-cost review and completion summary.

The existing CI route remains canonical:

```text
/stabler/#/imports/commercial-invoices/:name
```

### Import Container

A Container is a physical cargo unit within the CI sea shipment. It owns:

- container and seal numbers;
- type and size;
- packing-list item, box and kilogram quantities;
- container-specific documents;
- container-specific costs;
- exceptions, holds, damage or other deviations.

Packing-list rows require a dedicated Container child table with item, boxes,
quantity, net kilograms and gross kilograms. The table is not a
Container-to-Truck allocation: it records only what was packed in each sea
Container.

It does not own a second editable sea-shipment lifecycle. The operational sea
status displayed for a Container is derived from its CI.

The existing stored Container status and date fields remain during migration
as read-only legacy evidence. A later schema cleanup requires a separate data
retention decision.

### Import Truck

A Truck is an independent land-transport unit linked directly to the CI. It
owns:

- plate/truck number, carrier, driver and contact details;
- destination warehouse;
- departure, border, arrival and unloading dates;
- target temperature range and road-transport cost;
- its independent road lifecycle.

A Truck does not own product contents before arrival and does not reference a
source Container allocation.

### Truck Receipt

A Truck Receipt records the physical warehouse acceptance for one Truck:

- arrival date and receiver;
- measured arrival temperature;
- seal and packaging checks;
- QC note when required;
- received boxes and kilograms by CI/GRN item;
- Good, Damaged or Rejected condition;
- damaged/rejected box counts;
- optional expiry data and photo evidence;
- the resulting native ERPNext Purchase Receipt.

### GRN Checklist

There is one GRN Checklist per CI. It is the cumulative operational control
over all submitted Truck Receipts, not a second stock-entry document.

### Customs Declaration

A CI may own multiple Customs Declarations. Each declaration keeps its own GTD
number, lines, status, dates, values, duties and documents. Each declaration
has an explicit `required_for_departure` flag, defaulting to true. Optional,
amending or post-clearance declarations must be deliberately marked false; an
unset value is never interpreted as optional. A Container link may remain
optional metadata, but navigation and workflow ownership are CI based.

## Lifecycle Rules

### Shared sea lifecycle

The CI is the source of truth for:

```text
BOOKED
→ STUFFED
→ GATE_IN
→ ON_BOARD
→ IN_TRANSIT
→ DISCHARGED
→ AVAILABLE
→ ARRIVED_AT_IRAN
```

Linked Containers display the CI status and shared voyage dates. Container
exceptions are represented separately and do not mutate the shared status.

### Customs and port-transfer gate

Because no Truck-to-Container or Truck-to-GTD allocation exists, partial GTD
clearance cannot safely authorize selected Trucks. Therefore every CI Customs
Declaration marked `required_for_departure` must be cleared, and a valid
veterinary certificate or an authorized, reasoned Imports Manager override
must exist, before any Truck can advance to `DEPARTED_IRAN`.

### Independent truck lifecycle

Each Truck independently follows:

```text
PENDING
→ DEPARTED_IRAN
→ AT_BORDER
→ CROSSED_BORDER
→ IN_TRANSIT
→ ARRIVED
→ UNLOADING
→ GRN_CREATED
→ COMPLETED
```

Backward correction remains privileged, reason-required and audit-visible.

### Derived CI completion

`DELIVERED_TO_UZBEKISTAN` is no longer an arbitrary manual declaration. It is
set when the CI's GRN has passed its completion gates after every planned
Truck has a submitted Truck Receipt and native Purchase Receipt.

The planned Truck set is every non-cancelled Truck linked to the CI when the
GRN receives its first submitted Truck Receipt. That submission freezes the
set. Adding or removing a Truck afterwards requires an authorized,
reason-recorded GRN correction workflow; it cannot silently change the
completion denominator.

## CI Workspace UX

The CI route becomes a modular tabbed workspace:

```text
CommercialInvoiceWorkspace
├── CiHeader
├── CiOverview
├── CiProductsAndPricing
├── CiSeaShipment
├── CiContainers
├── CiCustoms
├── CiTrucks
├── CiGrnWorkspace
│   ├── TruckSummaryStrip
│   ├── GrnSupervisorMatrix
│   └── TruckReceiptDrawer
└── CiLandedCost
```

The current large Commercial Invoice form is not expanded into a larger
monolith. The route shell owns the common header and tab navigation; focused
components own each operational area and load only their required data.

All CRUD stays inside the Stabler SPA:

- Containers can be created and edited from the CI Containers tab.
- Multiple GTDs can be created, edited and advanced from the CI Customs tab.
- Trucks can be created and tracked from the CI Trucks tab.
- Create/Open GRN appears in the CI workspace.
- GRN, receipts, landed-cost review and late-cost actions remain within the CI
  context.

Standalone list routes remain useful for cross-CI queues and reporting. They
link back to the CI workspace rather than becoming competing workflow owners.

## Hybrid GRN Supervisor Matrix

The GRN workspace combines the strongest parts of the old and new systems.

### Persistent supervisor view

- All planned Trucks are shown together with plate, status, receipt state,
  arrival, kilograms, QC and photo indicators.
- A product-by-Truck matrix shows Expected, each Truck's received quantity,
  cumulative Received, Pending and Variance.
- Submitted Truck columns are read-only.
- In-transit Trucks remain visible with expected arrival and no received
  quantities.
- The matrix supports horizontal scrolling and fixed product/summary columns.

Expected quantity is initialized by aggregating every linked Container
packing-list row by item. The CI commercial lines remain a pricing and order
reference. The workspace shows a separate CI-versus-packing-list
reconciliation; incomplete packing lists or unresolved item/quantity
mismatches block port-transfer readiness.

At `STUFFED`, the guarded automation creates the GRN shell idempotently and
initializes expected rows from the packing-list aggregate. Before the first
Truck Receipt is submitted, an idempotent **Refresh expected quantities**
action may resynchronize the aggregate. The first Receipt submission freezes
both the expected snapshot and the planned Truck set. Later packing-list edits
are blocked until an authorized correction workflow is used.

### Single editable receipt boundary

Selecting a Truck opens an inline drawer in the same window. Only that Truck's
draft Receipt is editable. The drawer contains arrival, warehouse, temperature,
seal, packaging, item counts, condition, QC note, expiry and photos.

Photo evidence is optional for a normal receipt. It is mandatory when any item
is Damaged or Rejected, the measured temperature is outside its target range,
the seal is broken, or packaging fails inspection.

This deliberately avoids MSAERP's single giant editable form, which lacked
real autosave, concurrency safety and independent receipt submission.

## Transaction Boundaries

### Truck Receipt submit

Submit requires:

- Truck status is `ARRIVED` or `UNLOADING`;
- arrival date and destination warehouse exist;
- temperature is recorded and an out-of-range value has a QC note;
- seal and packaging checks are recorded;
- at least one received item quantity exists;
- box/kg and condition values are internally valid;
- required exception photos exist for damage, rejection, temperature, seal or
  packaging failures;
- no submitted Receipt already exists for the Truck;
- the optimistic-concurrency version is current;
- company, module gate and Frappe write permission pass.

In one database transaction:

1. validate and submit the Truck Receipt;
2. create required batches/expiry metadata;
3. create and submit one native ERPNext Purchase Receipt containing only
   Good-condition stock;
4. keep Damaged/Rejected quantities as claim evidence;
5. recompute cumulative GRN totals and variance;
6. advance the Truck operational status.

If Purchase Receipt creation or submission fails, the Receipt submission,
batch changes, GRN totals and Truck transition roll back together.

### GRN submit

GRN submission requires:

- every planned Truck has a submitted Truck Receipt;
- every submitted Receipt has a submitted native Purchase Receipt;
- a valid veterinary certificate or an authorized, reasoned override exists;
- required Customs Declarations are cleared;
- received quantities are non-zero;
- variance is reviewed;
- critical variance has a claim/reference or explicit manager resolution;
- company, module and Frappe permission gates pass.

In one database transaction, submission freezes the cumulative receiving
snapshot, advances the CI to `DELIVERED_TO_UZBEKISTAN`, and creates a Draft
Landed Cost Voucher. If LCV validation or creation fails, GRN submission and
the CI transition roll back together. The workflow never auto-submits the
LCV.

### Cancellation and reversal

A submitted Truck Receipt can be cancelled only through a controlled reversal
that also cancels its Purchase Receipt and recomputes the GRN. Reversal is
blocked when the GRN or dependent LCV state makes the stock/accounting reversal
unsafe; the user receives the specific blocking document reference.

## Landed Cost and Multiple GTDs

The initial Draft LCV collects eligible, unconsumed cost lines across the CI,
including multiple cleared GTDs, freight and import expenses. Every source
cost line carries a stable consumption reference so a line from any GTD is
included at most once across the initial and delta LCVs.

- Recoverable VAT is excluded from capitalization.
- Customs amounts are not divided away by Container count.
- Distribution follows the configured quantity-based rule.
- Expense accounts come from Stabler Settings, never tenant-name branching.
- Late costs create delta LCVs containing only unconsumed lines.
- Finance reviews and submits every LCV in Stabler; no Desk redirect is used.

## Existing Automation Changes

### Automatic GRN creation

The existing guarded `STUFFED` hook remains idempotent for new CI activity,
but its expected rows are changed from CI commercial lines to the aggregate of
linked Container packing-list rows. It creates a GRN shell even when the
packing lists are not yet ready, records the readiness blockers, and never
invents expected quantities. Migrated CIs that already passed `STUFFED` use
the explicit Create/Open GRN action. Deployment does not bulk-create
production GRNs.

### Seventy-percent advance Payment Entry

The current Container-arrival automation can create one draft Payment Entry
per Container. That conflicts with the shared CI arrival model and must be
replaced by an idempotent CI/PO-level automation.

Existing Payment Entries are not deleted or rewritten automatically. A
reconciliation report identifies duplicate or ambiguous draft records for
human resolution.

## API Design

The server remains authoritative for company scope, module gates, Frappe
permissions, lifecycle transitions, eligibility and derived totals.

The CI workspace API exposes bounded sections rather than one ever-growing
payload:

- CI header and sea-shipment state;
- Container rows and packing-list summaries;
- Customs Declaration rows and clearance summary;
- Truck rows and planned/submitted counts;
- GRN summary, matrix and selected Truck Receipt detail;
- landed-cost summary and eligible actions.

Mutation APIs remain explicit and idempotent where creation may race. Every
mutation validates that linked CI, Container, Truck, GRN and Customs records
belong to the same company.

## Migration and Reconciliation

### Container status and dates

- Preserve stored legacy values as read-only evidence.
- If all Containers of a CI agree on one status/date and the CI is missing or
  behind, propose a deterministic backfill.
- If values conflict, create a reconciliation issue; do not choose the latest,
  maximum or majority value silently.
- After reconciliation, display the shared CI value in operational screens.

### Trucks

Existing Trucks retain their direct CI links and appear in the new workspace.
No Container allocation migration is performed.

### Customs and receiving

No downstream production GRN, Customs, Vet, Freight or Import Expense records
were observed in the inspected live data, so the new workflow begins without
inventing downstream records. This assumption must be rechecked immediately
before deployment.

### Payment Entries

Report existing Container-linked 70% draft Payment Entries and their CI/PO
coverage. No automatic deletion, cancellation or consolidation occurs.

## Testing Strategy

### Pure unit tests

- sea-status inheritance and exception rules;
- Container packing-list aggregation and CI-line reconciliation;
- expected-snapshot and planned-Truck-set freezing;
- customs-clearance and veterinary gates;
- required versus optional/amending GTD departure behavior;
- Truck transition eligibility;
- expected/received/pending/variance matrix math;
- receipt box/kg and condition validation;
- GRN completion and claim requirements;
- landed-cost aggregation across multiple GTDs;
- CI/PO-level advance idempotency.

### Frappe integration tests

- company and module isolation for every section and mutation;
- one CI with three Containers, two GTDs and four Trucks;
- a GRN shell with incomplete packing lists cannot become port-transfer ready;
- expected rows aggregate Container packing lists and freeze at first Receipt;
- each Truck Receipt creates exactly one submitted Purchase Receipt;
- a failed PR rolls the full Receipt transaction back;
- submitted Receipts recompute one cumulative GRN;
- GRN cannot submit at three of four Receipts;
- GRN submits at four of four only when vet, customs and variance gates pass;
- GRN submission creates one Draft LCV and advances the CI;
- multiple GTD cost lines are included once;
- cancellation reverses the corresponding PR and totals when allowed;
- concurrent Receipt edits fail loudly without overwriting data.

### SPA tests

- CI tabs preserve the current route and context;
- all four Trucks remain visible in the GRN matrix;
- packing-list blockers and CI-versus-packed mismatches are visible;
- only one Receipt drawer is editable at once;
- submitted columns are read-only;
- disabled actions explain their blocking gate;
- no action navigates to `/app/...`;
- monetary inputs use shared `MoneyInput`;
- tables follow Stabler striping and currency-alignment rules.

### Production pilot

Use one authorized business CI with three Containers and four Trucks. Verify
each native Purchase Receipt, Stock Ledger Entry, batch/expiry record, GRN
total, LCV input, valuation impact and GL result. Test evidence, not only API
success responses, is required before broader rollout.

## Phased Delivery

1. Modular CI workspace shell and read-only operational summaries.
2. CI-scoped Container and multi-GTD Customs CRUD.
3. Shared CI sea lifecycle and Container inheritance/reconciliation.
4. CI-scoped Truck CRUD and independent tracking.
5. Create/Open GRN action and expected-quantity initialization.
6. Hybrid supervisor matrix and inline Truck Receipt drawer.
7. Receipt-to-Purchase-Receipt integration verification.
8. GRN completion gates, derived CI delivery and Draft LCV.
9. CI-level advance automation and legacy reconciliation reports.
10. Controlled production pilot and evidence review.

Each phase is independently deployable and must preserve existing records.
Phases that write stock or accounting documents require a configured Frappe
test site and passing integration tests before production deployment.

## Acceptance Criteria

- A user can manage the complete logistics/customs workflow from the CI SPA
  route without opening Frappe Desk or navigating to a competing workflow.
- Three Containers visibly share the CI sea status and dates while retaining
  their physical packing-list and exception data.
- GRN Expected values equal the aggregate of Container packing-list items;
  no Truck product allocation is required or inferred.
- Multiple GTDs are visible and manageable under one CI.
- Four Trucks are visible together and retain independent road statuses.
- The GRN matrix compares every product across all four Trucks in one window.
- Only the selected draft Truck Receipt is editable and independently
  submitted.
- Each submitted Receipt creates exactly one native submitted Purchase Receipt
  or rolls back completely.
- One GRN accumulates all Receipt totals and cannot close until all declared
  gates pass.
- GRN completion derives CI delivery and creates a Draft, never auto-submitted,
  LCV.
- Legacy conflicts and payments are reported for reconciliation rather than
  silently overwritten or deleted.
