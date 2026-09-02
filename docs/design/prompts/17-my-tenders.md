# 17 · My tenders

> `/tender/my-tenders` · `stabler/public/js/pages/tender/MyTenders.vue` (125 lines)
> Server: `stabler.api.tender.sourcing_my_tenders` (`tender.py:2474`)
>
> **Nothing in this file is invented.** Every number was produced by executing
> `sourcing_my_tenders`, `_deal_landed` and `_deal_deadlines` against
> `stabler/maintenance/seed_tender_demo.py`.

---

## Read this first — and correct prompt 13 while you are here

This screen carries **1 `ds-*` token in 125 lines** — the `Clear filters` button,
and nothing else. It is Bootstrap end to end:

| | measured |
|---|---|
| Structure | `card` › `card-body p-0` › `table card-table` |
| Utilities | `text-end`, `text-nowrap`, `fw-semibold`, `font-monospace`, `p-0` |
| Risk chip | Tabler `badge bg-*-lt text-*`, built in a JS map (below) |
| Row cursor | `style="cursor:pointer"` — inline |

    const riskBadge = (r) => ({
        good: "bg-green-lt text-green",
        warn: "bg-yellow-lt text-yellow",
        risk: "bg-red-lt text-red",
    }[r] || "bg-secondary-lt");

A `grep 'badge bg-'` over the template returns **0** for this file, because the
classes live in that map. Prompts 11 and 12 already caught the same trick and
counted it honestly — *"2 `badge bg-` sites over three colour maps"*. Nothing new
there; the count just has to be taken from the JavaScript as well as the markup.

**What is new is a correction owed to prompt 13.** Its comparison table put
`43 · 64 · 34` in a column headed *"What 10 / 11 / 12 have"*. Those three numbers
belong to `DirectorBoard`, `TenderFunnel` and `TenderFlow` — prompts **14, 15 and
16**. Prompts 10, 11 and 12 are `PoControlBoard`, `DeclarantQueue` and
`LogistBoard`, and each of those files says **0 `ds-*`** in its own header, which
is correct. Fix the row in 13.

**The measured ranking, whole module:**

    TenderCrm 107 · OperationsDesk 79 · TenderFunnel 64 · DirectorBoard 43
    TenderFlow 34 · TenderOverview 27 · TenderPage 4 · TenderNav 3
    MyTenders 1
    BidPricing · DeclarantQueue · LogistBoard · PoControlBoard · SourcingWorkspace
    · TenderDocumentChain · TenderDocuments · TenderDocumentsPanel · TenderIntake
    · TenderWorkspaceTabs  — all 0

**Ten of nineteen tender files carry no house layer at all.** This screen is not
the exception; it is the smallest and simplest member of the unmigrated majority,
which makes it the cheapest place to prove the migration end to end. 125 lines,
five columns, one badge map, one table.

**And it explains a number the package has been reporting without comment.**
`EmptyState.vue` is Tabler-native — Tabler icons, Tabler colour tokens, a
gradient disc. Every migrated screen shows `EmptyState: 0`: not an oversight, the
migration replaced it with `.ds-panel-foot` state rows. This screen is the only
one in 10–17 that still uses it. Deciding what replaces it here decides whether
the house layer ever gets a real empty-state component or keeps building them out
of panel footers.

---

## 0 · Where this screen sits

`TenderFunnel` (prompt 15) is the module's hub, and it has **three**
destinations, not one:

| what you click in the funnel | goes to |
|---|---|
| chevron strip phase | filters in place, or `/tender/portfolio?phase=` (prompt 14) |
| **a stage box or a funnel rung** | **`/tender/my-tenders?funnel_stage=<key>`** — here |
| an execution bucket (`kind: "so"`) | `/tender/board` (prompt 18) |

`TenderFunnel.vue:358-360` states the rule: *"Graphics stay here; records live on
their ORIGINAL list page."* The funnel never grows a table of its own. **Seven
of its eleven stage boxes and all five funnel rungs land here**; the other four
boxes are the execution buckets, which carry `kind: "so"` and go to the contract
board instead.

Prompt 14 owns the chevron's arrival; this prompt owns the stage boxes'.

---

## 1 · The product, and the column this screen has wrong

Stabler is a tender operations SPA for a company bidding on Uzbek state railway
tenders and importing the goods it wins.

This is the **sourcing** window — the pre-win worker's own list. Its gate is
`_require_tender_view("sourcing", company)` and its five columns are:

    Tender · Landed · PO count · Delivery deadline · Risk

**Two of those five are post-win facts.** `landed` is
`Σ (PO.base_grand_total + Σ charges.amount)` over the deal's Purchase Orders
(`_deal_landed` → `_deal_landed_split`, `tender.py:1042`), and a Purchase Order
exists only after a tender is won. On seed data **eleven of thirteen rows show
`0` landed and `0` POs** — and those eleven are exactly the tenders a sourcing
user is actually working on.

The sourcing window's only two data columns describe what happens after sourcing
ends.

**And the right number already exists.** Zafar's ruling, recorded in prompt 03:
pre-win costing is a **fixed landed-cost estimate entered against each incoming
quotation** by the sourcing officer, from experience, with no customs or
logistics staff involved — because that estimate is what sets the bid price.
`get_quotation_landed` (`sourcing.py:1284`) returns `landed_charges_total`,
`base_landed_total` and `has_landed_estimate` for exactly that.

So the design question this screen asks is not cosmetic: **which landed cost
belongs on a sourcing user's list — the one that will exist after they win, or
the one they typed in order to bid?** Answer it. Do not simply restyle the
column that is empty.

---

## 2 · The role, and the flag the server sends that the screen throws away

The endpoint splits its audience in one line (`tender.py:2481-2487`):

    oversight = _is_tender_oversight()
    ...
    if not oversight and (intake.get("assigned_to") or "") != me:
        continue

An oversight user (director) sees the whole pipeline; a plain sourcing user sees
only tenders **assigned to them** by the department head via `assign_tender` —
which is the manager `<select>` on prompt 14's board. The two screens are the two
ends of one gesture.

The client knows this and says so in a comment (`MyTenders.vue:50-51`):

> Note for non-oversight users: my-tenders shows only assigned tenders, so they
> may see a subset of the director's number — by design.

**The server returns `"oversight": oversight` in the payload
(`tender.py:2516`). Measured: zero consumers in the SPA.** The flag that would
let the screen say *"showing only tenders assigned to you"* is on the wire and
dropped — so the screen cannot explain the very discrepancy its own comment
documents. A sourcing user who is told "there are ten in sourcing" and sees three
has nothing on screen to reconcile the two.

**This is the third unread payload key the package has found**, after
`generated_at` (prompt 13) and `stage_sla` (prompt 16). All three carry exactly
the sentence their screen is missing.

`useEscapeBack(null, "/tender/board")` — Escape leaves for the sales-folder file,
same as prompt 14.

---

## 3 · Nine mandates — measured

| # | Mandate | Measured |
|---|---|---|
| 1 | House layer, not Bootstrap | **FAIL** — 1 `ds-*` in 125 lines; one of ten tender files with no house layer (see above) |
| 2 | Every number carries its rule | **N/A** — no counters at all. It is the only tender board with no KPI strip |
| 3 | Loading is skeleton, not spinner | **PASS** — `<SkeletonRows :cols="5" :rows="6">` |
| 4 | Five states per region | **FAIL** — three: loading, rows, `EmptyState` |
| 5 | State lives in the URL | **PASS** — `funnel_stage` plus the whole `tenderRouteFilters` set |
| 6 | Keyboard and screen reader reachable | **FAIL** — zero `aria-*`, zero `role=`; the row is a `<tr>` with an inline `cursor:pointer` |
| 7 | No raw identifiers in front of a human | **PASS** — but only because nothing is labelled at all; the filter chip prints raw `key: value` |
| 8 | Refresh is not a button | **PASS** — `useAutoRefresh(load)`, no control |
| 9 | Freshness is the server's | **FAIL** — this screen auto-refreshes and shows **no timestamp at all**, not even the browser's |

---

## 4 · Hard rules

- **No dark mode.**
- **Migrate, do not redesign the data.** The five columns, the sort and the
  filters are the contract; `card`/`table`/`badge` are not. One exception, and it
  is the point of §1: the `Landed` column's *source* is a product question, not a
  styling one.
- **The stage filter must never be able to disagree with the number that sent the
  user here.** The client comment states this as the design intent — both come
  from `tender_funnel.rows`. S2 is how the implementation breaks it.
- **Do not make this screen fetch more.** It already issues two requests to two
  endpoints on a single navigation (S2).
- **`filterTenderRows` / `tenderRouteFilters` / `activeTenderFilters` are shared**
  with prompt 14's board. Whatever you draw for the active-filter summary must
  work on both, or say explicitly that it does not.

---

## 5 · Three states, where five belong

| Region | Has | Missing |
|---|---|---|
| Table | **3** — `SkeletonRows`, rows, `EmptyState` | error, forbidden, no-company |

Better than prompts 14 and 16, and broken the same way: `load()` catches into
`toast.error` and leaves `data.value` alone, so a failed load renders the
`EmptyState` reading **"No tenders match these filters."** — a sentence that is
wrong twice over when there are no filters and the server never answered.

And the component is used at a third of its capability: `EmptyState` accepts
`subtitle`, `tone`, `accentIcon` and an `actions` slot; this call passes `icon`
and `title` only. The second line that would distinguish *nothing matched* from
*nothing loaded* is a prop away.

---

## 6 · The screen

`TenderPage :label="t('Tender')" :title="t('My tenders')"`.

`#meta` and `#actions` both render **only when a filter is active** — so the
default page head is a title and nothing else. When they do render, `#meta` is
one span of `key: value` joined by `·`, and `#actions` is `Clear filters`.

Then a single `card` holding a five-column `table card-table`:

| column | content |
|---|---|
| Tender | `r.label` — the lot number, or the buyer, or the deal id |
| Landed | `formatMoney(r.landed)` |
| PO count | `r.po_count` |
| Delivery deadline | `formatDate(r.delivery)` or `—` |
| Risk | badge: On track · Deadline near · At risk · `—` |

Row click → `tender-po-control` (prompt 10's board).

---

### S1 — the migration, and what it must not lose

Beyond the class swap, three things in the current markup carry meaning that a
naive port would drop:

- **`text-nowrap` on the delivery header and cell.** A wrapped date in a
  five-column table is the reason it is there. `ds-table` has no equivalent by
  default.
- **`font-monospace` on the money cell.** Prompts 14 and 16 use `ds-mono` for the
  same reason: figures must align down the column.
- **`p-0` on `card-body`** so the table meets the card edge — `ds-panel` already
  does this, which is one line the migration deletes rather than translates.

The risk badge maps to the house layer directly: `ds-chip[data-tone]` with
`good → ok`, `warn → today`, `risk → crit`, exactly as `DirectorBoard`'s
`RISK_TONE` already does. **That map already exists in the codebase**; the
migration should import the pattern, not re-author it.

### S2 — the stage filter fetches a second copy of the whole funnel, and lies when it fails

Arriving from a funnel stage box triggers a **second full call to
`tender_funnel`** (`MyTenders.vue:60-70`) purely to learn which deals are in that
stage. That endpoint iterates every deal in the company and calls
`_deal_deadlines` for each open one — it is the heaviest read in the module — and
it is called here with the default `days=90`, which is **not necessarily the
window the user was looking at** when they clicked.

Then:

    } catch {
        funnelDeals.value = null; // filter degrades to "show all" rather than hiding everything
    }

The intent is defensible. The result is not: `filteredRows` skips the stage
filter when `funnelDeals` is null, **while `filterSummary` still prepends
`Stage: Collecting quotations`** — because that line is computed from
`route.query`, which has not changed. The header says the list is filtered to one
stage; the list is not.

There is a second, quieter version of the same gap: between the navigation and
the second response arriving, `funnelDeals` is null and the full list is rendered
under a chip naming one stage. **The filter is announced before it can be
applied.**

Draw the fix. The obvious one is not a spinner — the deal set is already in the
payload the funnel screen holds, and `pick()` on the chevron already passes
`deals` through the `@select` event to its host.

### S3 — `oversight` is on the wire and unread

See §2. The deliverable is the sentence the screen cannot currently say, and
where it goes: *"13 tenders"* for a director versus *"3 assigned to you, of 13 in
the company"* for a sourcing officer. The flag exists; only the design is
missing.

### S4 — the sort is not total, so the order is arbitrary

    for deal in _tender_deal_names(company):     # a set — no sorted()
        ...
    rows.sort(key=lambda r: (_RISK_ORDER.get(r["risk"], 3), r["delivery"] or "9999-99-99"))

Two keys. Prompt 14's board sorts the same rows on **three**, ending with
`r["deal"]`, and `tender_flow` iterates `sorted(deal_names)`. Here the input is
an unordered set and the sort key does not break ties.

On seed data **ten of thirteen rows tie on both keys** — three at
`warn` / +90 days and seven at `good` / +90 days. Their order is whatever the set
iteration produced, which is stable within a process and arbitrary across
restarts. A user who reloads after a `bench restart` can see the same thirteen
tenders in a different order, with nothing changed.

A design cannot fix this, but it must not paper over it: whatever secondary
ordering you show (lot number, buyer, assignment) is also the fix, and should be
named as such.

### S5 — the same three purchase orders total two different numbers on two screens

| screen | label | 4314 | 4315 |
|---|---|---|---|
| Prompt 10 · PO control board | **Total committed** | **1 640 000 000** | **1 120 000 000** |
| This screen · and prompt 14's board | **Landed** | **1 769 000 000** | **1 182 000 000** |

Both are correct. The difference is exactly the customs charges — 41 000 000 +
88 000 000 = **129 000 000** for 4314, and 62 000 000 for 4315 — because *committed*
is `Σ base_grand_total` and *landed* is `Σ (base_grand_total + charges)`.

Nothing on either screen says so. A sourcing user moving between the two sees a
7,9 % difference on the same three orders, one word apart, and no arithmetic to
reconcile them. Show the delta, or name the two quantities so the difference
reads as a distinction rather than a discrepancy.

### S6 — `result` is on every row and rendered nowhere

The payload carries `result` (`""` · `won` · `lost`) plus `lifecycle`, `status`,
`due`, `event_date` and `assigned_to_name` on every row. The table renders the
first of those **nowhere** and the rest only as filter evidence.

So on a sourcing user's own list, **a won tender, a lost tender and an open one
are visually identical.** Prompt 14's board gives `result` a chip; this screen
does not, and it is the screen where the distinction decides whether there is any
work left to do.

`assigned_to_name` is likewise unrendered — on a screen whose entire premise for
non-oversight users is assignment.

---

## 7 · Data — derived by execution, invent nothing

`_tender_deal_names` yields all 13 seeded deals. For a **director** (oversight)
every row survives; for a plain sourcing user only rows where
`intake.assigned_to == me`, which the seed distributes round-robin over the
site's non-Administrator users while leaving the two `seen` lots unassigned.

`landed` = `Σ (PO.base_grand_total + Σ charges.amount)`; only the two won lots
have Purchase Orders.

**The table for a director, in rendered order:**

| # | Tender | Landed | PO count | Delivery | Risk |
|---|---|---|---|---|---|
| 1 | UTY-2026-4314 [DEMO] | **1 769 000 000** | **3** | +30 | **At risk** |
| 2 | UTY-2026-4305 [DEMO] | 0 | 0 | +90 | **At risk** |
| 3 | UTY-2026-4315 [DEMO] | **1 182 000 000** | **2** | +60 | Deadline near |
| 4–6 | UTY-2026-4308 · 4310 · 4311 [DEMO] | 0 | 0 | +90 | Deadline near — **order arbitrary** (S4) |
| 7–13 | UTY-2026-4301 · 4302 · 4306 · 4309 · 4312 · 4313 · 4316 [DEMO] | 0 | 0 | +90 | On track — **order arbitrary** |

**Eleven of thirteen rows: `0` and `0`.** The two that are not are the two won
lots — the two this screen's audience has already finished with.

Landed, derived from `DEMO_PURCHASE_ORDERS`:

    4314  Hebei 620 000 000 + 41 000 000  ·  Temiryo'l 430 000 000 + 0
          ·  UralVagon 590 000 000 + 88 000 000   =  1 769 000 000
    4315  Shandong 780 000 000 + 62 000 000  ·  Sanoat 340 000 000 + 0
                                             =  1 182 000 000

**Arriving with `?funnel_stage=sourcing`** (the stage box reading 3 on prompt 15)
filters this list to `4305`, `4308`, `4309` — all three with `0` landed and `0`
POs. The header reads `Stage: Collecting quotations`.

**States you cannot exercise from this data:**

1. A row whose `Risk` is `—` (`none`) — every seeded deal has at least one dated
   milestone.
2. The `EmptyState` — no filter combination in §7 empties the list for a
   director; only a non-oversight user with no assignments reaches it, and that
   depends on the site's users.
3. `oversight: false` for a director; `oversight: true` for a sourcing officer.

Eighth consecutive screen with a state demo data cannot reach. Label anything you
draw from these as constructed.

---

## 8 · Vocabulary

| Term | Means, exactly |
|---|---|
| **my tenders** | for a sourcing officer, tenders **assigned to them**; for an oversight user, all of them. The same screen, two meanings, and nothing on it says which (S3) |
| **Landed** | `Σ (PO.base_grand_total + Σ charges.amount)` — a **post-win** figure. Not the quotation's pre-win landed estimate, which is what a sourcing user actually enters (§1) |
| **Total committed** | prompt 10's `Σ base_grand_total` for the same POs — the same orders, 129 000 000 less on 4314 (S5) |
| **PO count** | purchase orders on the deal, `docstatus < 2`, so drafts count |
| **funnel_stage** | the URL parameter that arrives from a funnel stage box; its set of deals comes from a **second** call to `tender_funnel` (S2) |
| **risk** | worst milestone across bid · contract · PO ETA · delivery: past due → *At risk*, within 7 days → *Deadline near*, else *On track* |

---

## 9 · Responsive

Measured: zero `@media`, zero `overflow-x`, no `table-responsive`. Five columns,
two of them money-shaped, and `text-nowrap` on a date.

Same gap as prompt 16, same available answer as prompt 14: scroll the table, not
the page. Specify the phone layout — and note that on a phone the two columns
that are empty on eleven of thirteen rows are the two taking the most width.

---

## 10 · Deliverables

Artboards, 1440×900 unless stated.

1. **The migrated screen, populated** — the thirteen rows of §7, house layer
   throughout, `ds-chip[data-tone]` risk, `ds-mono` money, `ds-table` inside
   `ds-panel`.
2. **The `Landed` question, answered** (§1) — the column as it is beside the
   column a sourcing user needs, drawn from `get_quotation_landed`. Mark your
   choice; keep the other.
3. **"Showing only tenders assigned to you"** (S3) — both audiences, using
   `oversight`, which is already on the wire.
4. **The stage filter, honest** (S2) — arriving, applied, and failed-to-apply.
   The failed case must not show a chip naming a filter that is not in effect.
5. **Table · the three missing states** (S5 heading in §5) — error, forbidden,
   no-company — and `EmptyState` with a `subtitle` that separates *nothing
   matched* from *nothing loaded*.
6. **`result` on the row** (S6) — won, lost and open, distinguishable.
7. **Committed vs landed** (S5) — the 129 000 000, explained where a user
   crossing between the two screens will see it.
8. **A secondary sort** (S4) — the ten tied rows given a stable, meaningful
   order.
9. **The row as a real control** — focusable, Enter-openable, no inline
   `cursor:pointer`.
10. **Mobile, 390×844.**
11. **An annotation board**: the three unread payload keys the package has now
    found (`generated_at`, `stage_sla`, `oversight`), and the note that
    `badge bg-` as a migration metric misses any screen that builds its classes
    in JavaScript.

Keep the artboards you rejected.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| M1 | The thirteen rows render with landed 1 769 000 000 / 1 182 000 000 and 0 elsewhere | passes |
| M2 | Rows sort by risk, then delivery | passes |
| M3 | `funnel_stage` and every route filter round-trip through the URL | passes |
| M4 | Loading renders a skeleton | passes |
| M5 | A non-oversight user sees only tenders assigned to them | passes — server-side |
| M6 | Arriving with `?funnel_stage=sourcing` lists exactly the three deals the funnel counted | passes **when the second request succeeds** (S2) |
| M7 | The screen uses the house layer | **fails** — 1 `ds-*` in 125 lines |
| M8 | The active-stage chip is shown only while that filter is in effect | **fails** — shown before and after failure (S2) |
| M9 | The screen says whether it is showing everything or only your assignments | **fails** — `oversight` unread (S3) |
| M10 | Two rows tied on risk and delivery have a defined order | **fails** — set iteration (S4) |
| M11 | A won or lost tender is distinguishable from an open one | **fails** — `result` unrendered (S6) |
| M12 | A failed load is distinguishable from "no tenders match these filters" | **fails** — same `EmptyState` |
| M13 | The row is reachable and openable from the keyboard | **passes** (2026-09-02) — `role="button" tabindex="0"`, Enter and Space. The inline `cursor:pointer` is untouched (M7) |
| M14 | The table scrolls on a phone; the page does not | **fails** — no responsive CSS |
| M15 | An auto-refreshing screen says how fresh it is | **passes** (2026-09-02) — `generated_at` |
| M16 | The landed figure shown to a sourcing user is one they can act on before the win | **fails** — it is a post-win sum, `0` on eleven of thirteen rows (§1) |
