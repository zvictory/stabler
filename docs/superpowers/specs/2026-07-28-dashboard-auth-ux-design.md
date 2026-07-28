# Dashboard consolidation and authentication transition design

**Date:** 2026-07-28
**Status:** Approved in conversation
**Scope:** Stabler SPA dashboard information architecture and login/logout transitions

## Context

Tender leadership information is split between the general Dashboard and
`/tender/director`. The general Dashboard also mixes executive indicators with
operational charts, attention lists, and a portfolio table. This makes the
primary decision surface harder to scan.

Authentication has a separate interaction problem. Successful login currently
assigns `window.location.href` and immediately calls `window.location.reload()`.
It also accepts a `redirect-to` value such as `/desk/user/...` as though it were
a Stabler route. Logout silently awaits the server before navigation. The user
therefore sees an unexplained pause during both transitions.

The referenced
`~/.claude/plans/https-msa-erpstable-com-stabler-reports-vivid-penguin.md` file
describes the PI Group Container Status report, not authentication. It is not an
implementation source for this work.

## Goals

1. Make the general Dashboard the single executive Tender overview.
2. Show only executive KPI indicators and a sales conversion funnel on the
   Tender Dashboard.
3. Reduce header and Tender sub-navigation density.
4. Eliminate duplicate post-login navigation and prohibit Desk redirects.
5. Give immediate, accessible feedback throughout login and logout.
6. Preserve existing non-Tender Dashboard behavior.

## Non-goals

- Redesigning financial or Imports dashboards.
- Changing Frappe's credential verification or session lifetime.
- Adding new Tender workflow actions.
- Keeping the Director portfolio table elsewhere on the Dashboard.
- Navigating to Frappe Desk for any record or authentication continuation.

## 1. Tender Dashboard

### Information architecture

For a company with the Tender module enabled, `/dashboard` uses the approved
**Executive ribbon** layout:

1. Compact page header.
2. Compact Tender sub-navigation.
3. One horizontal KPI ribbon.
4. One full-width sales conversion funnel.

No table, attention list, acquisition trend, execution status panel, or
portfolio preview appears below the funnel.

For companies without Tender enabled, the existing Imports-first and financial
fallback branches remain unchanged.

### Header and navigation

The page header contains:

- pretitle: `Tender operations`;
- title: `Dashboard`;
- period control, defaulting to the last 90 days;
- Refresh action.

The period controls the sales funnel and the time-bound win-rate calculation.
Active tenders, portfolio value, average margin, at-risk count, and net remaining
are explicitly labeled as current-portfolio snapshots and do not change with the
historical funnel period.

The Tender sub-navigation contains:

- Overview — `/dashboard`, active on the Dashboard;
- My tenders;
- PO control;
- Customs;
- Logistics.

The `Director board` item is removed. The existing `/tender/director` route is
retained as a compatibility redirect to `/dashboard` so saved bookmarks do not
break. No route may redirect to `/app/...` or another Frappe Desk URL.

### KPI ribbon

The ribbon shows six indicators in this order:

1. Active tenders
2. Portfolio value
3. Average margin
4. At risk
5. Win rate
6. Net remaining

Currency values use the shared money formatting utilities, tabular/monospaced
figures, and the company currency. Large values may use compact display text,
but the exact formatted value must remain available through accessible helper
text or a tooltip.

Semantic color is restrained:

- green for positive margin and win rate;
- red only when at-risk count is non-zero;
- neutral ink for volume and monetary totals.

The layout uses six columns on wide screens, three or two columns at narrower
breakpoints, and one column only when required for legibility.

### Sales funnel

The full-width funnel presents conversion stages for the selected period:

- Lots seen;
- GO decision;
- Sourcing started;
- Bid submitted;
- Won.

Each stage shows its count. The adjacent detail list shows conversion percentage
and drop-off from the previous stage. Stage interaction may open an existing
Stabler list/filter route, but it must never open Desk.

The separate horizontal Tender pipeline and all record tables are excluded from
this Dashboard design.

### Data contract

The Dashboard must not download the Director board's complete row collection
only to render its KPIs. The existing
`stabler.api.tender.tender_dashboard` aggregate response is extended with an
`executive_kpi` object. A second row-heavy Director request is not made.

The KPI calculation must reuse the same backend calculation helpers as the
Director board so values do not diverge during the route transition. Existing
period and company permission checks remain authoritative.

Loading uses KPI-shaped skeletons and a funnel-shaped skeleton. An aggregate
failure shows one inline error with Retry; it does not leave stale values
presented as current.

## 2. Authentication transitions

### Redirect policy

Post-login redirect input is untrusted. A redirect is accepted only when all of
the following hold:

- it resolves to a known internal Stabler SPA path;
- it begins with exactly one `/`;
- it is not `/app`, `/desk`, or a child of either;
- it contains no scheme, protocol-relative prefix, control character, or
  backslash;
- decoding it once does not reveal a forbidden or external target.

Invalid, external, Desk, doubly encoded, and unknown paths fall back to
`/dashboard`. The reported `/desk/user/zvictory2001%40gmail.com` target therefore
resolves to `/dashboard`.

### Login state machine

1. **Idle:** form is interactive.
2. **Authenticating:** submit button is disabled and shows progress.
3. **Transitioning:** after Frappe confirms login, a full-screen overlay shows
   `Session opened` and `Preparing your Dashboard…`.
4. **Failure:** the overlay is removed, the form becomes interactive, focus
   returns to the error summary, and the server-safe error is shown.

Successful login performs exactly one terminal navigation with
`window.location.replace()` to the sanitized Stabler target. The current
`location.href` plus `location.reload()` sequence is removed.

This design keeps the native Frappe `/api/method/login` contract and its session
cookie behavior. It intentionally avoids reload-free session hydration because
that would require a broader CSRF-token and session-store contract change.

### Logout state machine

1. The first logout activation immediately closes the account menu, disables
   repeated activation, and opens a full-screen overlay.
2. The overlay shows `Signing out securely…` and remains visible while the
   official Frappe logout endpoint invalidates the session.
3. Success uses one `window.location.replace()` to `/stabler#/login`.
4. Failure removes the overlay, restores interaction, and shows a retryable
   toast. The UI must not claim that logout succeeded while the session may
   still be active.

No artificial minimum animation duration is added. A longer-than-normal request
may update the overlay copy, but must not silently redirect before the server
confirms logout.

### Transition overlay

The overlay is a shared, narrowly scoped component used only for terminal
authentication transitions. It provides:

- full viewport coverage;
- Stabler mark;
- action-specific title and status;
- `role="status"` and polite live-region semantics;
- reduced-motion behavior;
- no dismiss action during an in-flight terminal transition.

## Error handling and accessibility

- Login and logout network errors preserve a usable recovery path.
- Buttons expose disabled/busy state with `aria-disabled` and `aria-busy` where
  appropriate.
- Focus is not trapped in an overlay that has no interactive controls.
- New user-facing strings use the existing `t()` mechanism and are added for
  the supported `en`, `ru`, `uz`, `uzc`, and `tr` catalogs.
- Refresh, funnel stages, and navigation retain visible keyboard focus.

## Testing

### Dashboard

- Tender-enabled Dashboard renders all six executive KPI labels.
- Tender branch renders the sales funnel and no `<table>`.
- `TenderPortfolioPreview`, attention list, acquisition chart, and Director
  table are absent from the Tender Dashboard branch.
- `/tender/director` redirects to `/dashboard`.
- Tender navigation contains Overview and no Director board entry.
- KPI API response contains aggregates without requiring portfolio rows.
- Non-Tender Dashboard branches retain existing behavior.

### Authentication

- Valid Stabler routes remain valid after sanitization.
- `/desk`, `/app`, external, protocol-relative, backslash, unknown, and
  doubly-encoded targets resolve to `/dashboard`.
- Login success performs exactly one replacement navigation and never calls
  `reload()`.
- Authenticating and transitioning states prevent duplicate submission.
- Logout immediately exposes busy state and prevents duplicate calls.
- Login/logout failure restores interaction and displays a retryable error.
- Overlay exposes the expected status semantics.

## Acceptance criteria

- The Tender Dashboard contains only its compact header/navigation, six KPI
  indicators, and the sales conversion funnel.
- No Dashboard or auth path links to Frappe Desk.
- Existing `/tender/director` bookmarks land on the general Dashboard.
- Login performs one post-success navigation.
- Login and logout display immediate full-screen progress and recover cleanly on
  failure.
- Focused tests, JavaScript lint, frontend tests, Python Tender tests, and the
  production asset build complete without skipped failures.

## Implementation sequencing

This design spans two independent subsystems and should be implemented as two
reviewable milestones:

1. Dashboard consolidation and route/navigation cleanup.
2. Login/logout redirect hardening and transition states.

Each milestone follows a separate red-green-refactor cycle and verification
checkpoint.
