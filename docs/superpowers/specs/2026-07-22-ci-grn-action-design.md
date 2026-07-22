# Commercial Invoice Create/Open GRN Action

## Problem

The production Imports SPA contains migrated Commercial Invoices that have
already passed the `STUFFED` lifecycle state but have no GRN Checklist. The
automatic `Commercial Invoice` `on_update` hook creates a GRN only when a new
status transition enters `STUFFED`; migration intentionally suppresses that
hook. As a result, an eligible migrated CI can be delivered and linked to
containers while the GRN list remains empty.

The backend already exposes the company-scoped, permission-checked,
idempotent `create_grn_for_ci` method. The missing behavior is an accessible
Stabler SPA action and visibility of the CI's existing GRN.

## Scope

Add a GRN action to the Commercial Invoice detail page:

- Show **Create GRN** when the saved CI has no GRN and is at or beyond
  `STUFFED` in the logistics pipeline.
- Ask for confirmation before creating a live GRN Checklist.
- Call the existing idempotent API and navigate to the returned GRN detail.
- Show **Open GRN** when a GRN already exists and navigate without a write.
- Disable the action while a create request is in progress.
- Surface backend errors through the existing toast mechanism.

This change does not bulk-create GRNs, create records when a page is opened,
alter lifecycle transitions, or change the automatic `STUFFED` hook.

## Server Contract

Extend `get_commercial_invoice` with a small `grn` object when one exists:

```json
{
  "grn": {
    "name": "GRN-...",
    "docstatus": 0,
    "receipt_status": "Not Started"
  }
}
```

Return `null` when no GRN exists. The query must remain scoped through the CI
that has already passed company, module-gate, and Frappe read-permission
checks. No new write endpoint is introduced.

`create_grn_for_ci(commercial_invoice)` remains the only write operation. Its
idempotent response is used for both race recovery and normal creation:

```json
{ "name": "GRN-...", "created": true }
```

or:

```json
{ "name": "GRN-...", "created": false }
```

## SPA Design

Place the GRN action in the existing Commercial Invoice status action bar so
it is visible in the logistics context and does not create another page-level
navigation pattern.

Eligibility is derived from the current CI status:

- Not shown for a new/unsaved CI.
- Not shown for `BOOKED` or `Cancelled` when no GRN exists.
- Shown as **Create GRN** for `STUFFED`, `GATE_IN`, `ON_BOARD`, `IN_TRANSIT`,
  `DISCHARGED`, `AVAILABLE`, `ARRIVED_AT_IRAN`, and
  `DELIVERED_TO_UZBEKISTAN` when no GRN exists.
- Always shown as **Open GRN** when the server reports an existing GRN,
  including exceptional legacy states.

After confirmation, creation calls `importsApi.createGrnForCi(form.name)`.
The returned name is authoritative; the UI immediately routes to
`/imports/grn-checklists/:name`. This avoids a second fetch and handles the
case where another user created the GRN between page load and click.

## Error and Concurrency Behavior

- A rejected confirmation performs no write.
- Double clicks are prevented by a local `creatingGrn` flag.
- Backend permission, module-gate, validation, and empty-item errors are shown
  with the existing error toast.
- An idempotent `created: false` response still opens the existing GRN.
- The UI does not infer or synthesize a GRN name.

## Testing

Add focused tests that encode the business intent:

1. The CI detail API returns `grn: null` when no GRN exists.
2. It returns the linked GRN identity and operational status when present.
3. The frontend eligibility helper allows creation at and after `STUFFED`,
   excludes `BOOKED` and `Cancelled`, and always allows opening an existing
   GRN.
4. The existing idempotency behavior of `create_grn_for_ci` remains covered.
5. Build or SFC validation confirms the Vue template compiles.

Production verification is read-only until a real business CI is explicitly
selected for GRN creation. Deployment and creation of production records are
outside this implementation change.

## Acceptance Criteria

- A migrated delivered CI without a GRN visibly offers **Create GRN**.
- Clicking it requires explicit confirmation.
- A successful response opens the Stabler GRN detail route; no `/app/...`
  navigation occurs.
- Reopening the CI shows **Open GRN** instead of **Create GRN**.
- Existing automatic GRN creation on the `STUFFED` transition still works.
- Company scope, module gating, Frappe permissions, and the one-GRN-per-CI
  invariant remain enforced server-side.
