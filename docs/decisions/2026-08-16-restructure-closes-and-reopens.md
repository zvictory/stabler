# Architectural Decision Record: A Restructure Closes the Agreement and Opens a Successor

Date: 2026-08-16
Status: Approved & Permanent (design panel, bead `stabler-4b4n`)
Supersedes nothing. Binding on slices `stabler-l0m.3.9`, `stabler-l0m.3.10`, `stabler-l0m.3.11`.

## The conflict

Two rules in the frozen `stabler-l0m.3` contract could not both hold:

- the agreement total is **fixed on submit** (slice `stabler-l0m.3.11`, wizard step 3:
  "Agreement total (fixed on submit)")
- `agreement_status` carries **`Restructured`** as one of seven states
  (`vehicle_agreement.json:71`)

If a restructure mutates the total of a submitted agreement, the first rule is dead. If
it does not, the second state means something else and needs a different name.

Left unresolved, paid/outstanding on the summary tiles become uninterpretable: you cannot
separate original-plan performance from renegotiated-plan performance.

## Decision

**A restructure CLOSES the original agreement and OPENS a new one.** The original record
is never mutated. The delta is readable as the difference between two records, and the
audit trail survives intact.

Two panelists reached this independently, from different premises — which is why it is
recorded as settled rather than argued further:

- **Finance:** mutating the total in place and adding a "difference" field weakens exactly
  the audit trail the immutability rule exists to protect.
- **Business owner:** the restructure count then becomes an objective number — the count of
  closed agreements in the chain — rather than a tab nobody opens. Their words on the
  rejected alternative: *"it hides it better — the active agreement always looks healthy"*,
  which was the original complaint.

### Condition of the owner's vote — not a nice-to-have

The chain position must be visible **at a glance** in the work queue and the agreement
list, e.g. `3/3 · restructured twice`. Without it you still have to go hunting for the last
closed agreement to learn the history, which reproduces the very problem this decision was
chosen to solve.

## Restructure is not Reschedule. Keep them apart.

| | Reschedule | Restructure |
|---|---|---|
| What changes | the schedule inside one agreement — a corrected due date, a re-cut plan | the total and the economics |
| Record created | new `Vehicle Finance Schedule Version` | new `Vehicle Agreement` |
| Original | stays open, stays collectible | closed, immutable, linked to its successor |
| Total | unchanged | different by definition |

`Vehicle Finance Schedule Version` is **not** made redundant by this decision. Collapse the
two concepts and the design silently reverts to the rejected alternative.

## Known defect this decision exposes

The collapse has already happened in shipped code, and it is why this ADR exists rather
than a one-line note:

- `stabler/api/vehicle_finance/v1.py:926` — `approve_reschedule` sets
  `agreement_status = "Restructured"` after cutting a new Schedule Version
- `stabler/api/vehicle_finance/v1.py:41` — `_COLLECTIBLE_STATUSES = ("Active", "Restructured")`,
  so `Restructured` is an **active** state, not a terminal one
- `stabler/public/js/composables/status.js:280` — the comment itself reads
  "a *rescheduled* agreement", against an enum value named `Restructured`

So today `Restructured` labels a **reschedule**: same total, new schedule version. The
immutability rule is not violated by live code — `approve_reschedule` never touches
`total_contract_price` — but the name for a real restructure is already taken by something
else, and a real restructure has no implementation at all.

Resolving that naming/semantics collision is tracked separately and must land before the
successor link is built on top of it.

## Implementation consequences

1. `Vehicle Agreement` needs a semantic self-link for the chain. Follow the existing
   pattern at `vehicle_finance_payment_application.json:34` (`reverses`, a Link to its own
   doctype) — **not** Frappe's `amended_from`, which means something else.
2. The agreement-list and work-queue serialisers must expose chain depth and position, so
   the UI can render `3/3 · restructured twice` without a second round trip.
3. The status enum must distinguish "this agreement was closed by a restructure" (terminal)
   from "this agreement's schedule was re-cut" (collectible).

Items 1 and 2 are schema changes. They must land **before** slices `stabler-l0m.3.9`
(agreement list) and `stabler-l0m.3.10` (agreement detail) are built, not after.
