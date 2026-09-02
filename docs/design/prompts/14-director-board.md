# 14 · Director board

> `/tender/portfolio` · `stabler/public/js/pages/tender/DirectorBoard.vue` (386 lines)
> Server: `stabler.api.tender.tender_director_board` → `_tender_director_payload`
> (`stabler/api/tender.py:2079-2170`)
>
> **Nothing in this file is invented.** Every number below was produced by
> executing `_tender_director_payload`'s own expressions against
> `stabler/maintenance/seed_tender_demo.py`. Where a figure depends on a code
> path I did not execute, this file names the path and declines to state the
> figure.

---

## Corrections this file owes the package

**Prompt 13 said the rule-under-the-number signature "exists nowhere else in the
module." That is wrong, and the truth is more useful.**

It exists here too, and here it is older and larger: **six** counters, not four,
and each carries **two** sub-lines rather than one —

    <div class="ds-kpi-note">{{ k.note }}</div>   ← a human sentence, a t() key
    <div class="ds-kpi-q">{{ k.rule }}</div>      ← raw query syntax, not a key

The screen prints its own thesis in the page head (`:148`):

> *Numbers are read from ERP records — the rule under each says what it counted*

**Three of its six rules do not say what it counted.** That is S1, and it is the
reason this prompt exists. Correct prompt 13's §1 and `00-SETUP.md`'s *From 13*
section: the signature appears in more than one screen, and the older
implementation is the one whose promise fails.

**Corrected again the same day by prompt 15.** There are **three** carriers, not
two, and this is not the largest: `TenderFunnel` carries the signature fifteen
times — 4 counters, 11 stage boxes, plus a rule inside each chevron popover.

**And this screen does not render six counters. It renders ten.**
`<TenderFunnel pipeline-strip :selected="phase">` passes no `mode`, the prop
defaults to `"full"`, and the `v-if="props.mode === 'full'"` branch draws **four
more counters** plus eleven stage boxes plus the conversion funnel — below this
screen's own six and above its table. Two of those pairs collide on label,
caption and rule while showing different numbers. Prompt 15 §S1 measures it; this
file was written before that was known, so every count in §6 below is the board's
own, not the page's.

---

## 0 · What you are extending — and the one thing you must not draw

**Do not draw `TenderFunnel`.** It is 745 lines, it is the whole of prompt 15,
and the package already decided it is drawn once, there. This prompt owns only
what `DirectorBoard` does *with* it.

The difference is documented by the two hosts themselves:

| | `DirectorBoard` (this prompt) | `TenderOverview` (prompt 15) |
|---|---|---|
| props | `pipeline-strip :selected="phase"` | `mode="full" pipeline-strip` |
| `@select` | `onPhaseSelect` — filters the table below | `openPhase` — **navigates here** |
| owns | the `phase` URL param, the `board-phase` status bar, the filtered table | nothing; there is no table under it |

`TenderOverview.vue:115-118` says why, and it is the right instinct — *"Aynı
zihinsel model, tek fark filtrenin nerede uygulandığı."* The same mental model;
the only difference is where the filter is applied. **This screen is where the
funnel points.** Design the arrival, not the strip.

---

## 1 · The product

Stabler is a tender operations SPA for a company bidding on Uzbek state railway
tenders and importing the goods it wins. This is the only screen built for one
person: the director, looking at the whole portfolio at once.

Its job is not to be pretty. Its job is to be **trusted without asking anyone**,
which is why every counter prints the query behind it and the panel footer names
the four tables the board reads:

    tender_lot · quotation · sales_order · purchase_order

That is a design position, not decoration. Keep it. Then make it true.

---

## 2 · The role, and the gate that has no states

One line: `_require_tender_view("director", company)` (`tender.py:2184`). There
is no view switcher, no role lens, no `sourcing`/`declarant`/`logist` variant —
this screen either is yours or it is not.

**And the refusal has nowhere to land.** Measured: `load()` catches everything
into `toast.error(...)` (`:42`) and leaves `data.value` at its previous value.
There is no `error` ref, no forbidden branch, no "select a company" branch —
`load()` simply returns early when `activeCompany` is falsy.

So a director who lacks the view, a company that was never selected, and a
server that fell over all render **the same screen**: six counters reading zero,
an empty table, and the sentence *"No tenders match these filters."* plus
*"Clear filters or select another dashboard period."*

**The board's failure mode is to blame the user's filters for the server's
silence**, behind a toast that has already faded. This is the defect prompt 13
proved is avoidable — `OperationsDesk` renders five distinct states in one panel
— and it is worse here, because this screen is read by the one person who will
act on a number without checking it.

**The finished answer is already in the repository.** `TenderOverview.vue` renders
a user with neither role a panel titled *"Your work is on the operations desk"*
with a link there, because *a white page reads like an error*; and `loadFlow()`
writes its failure **into the panel** rather than a toast, because two requests
fire on open and the reader must be able to see which one fell over. Cite prompt
15 §2 rather than designing this twice.

---

## 3 · Nine mandates — measured

| # | Mandate | Measured |
|---|---|---|
| 1 | House layer, not Bootstrap | **PASS** — 43 `ds-*`, 0 `badge bg-`, 0 bare `btn-`, 0 `spinner-border`, 0 `table-responsive` |
| 2 | Every number carries its rule | **PRESENT BUT FALSE** — six counters, two sub-lines each, three rules wrong (S1) |
| 3 | Loading is skeleton, not spinner | **PASS** — `<SkeletonRows :cols="9" :rows="6" hide-first-on-mobile>` |
| 4 | Five states per region | **FAIL** — two: loading and empty (§2) |
| 5 | State lives in the URL | **PASS, and it is the module's best** — `phase` via `router.replace`, plus the whole `tenderRouteFilters` set, plus a `Clear filters` chip that names what is active |
| 6 | Keyboard and screen reader reachable | **FAIL** — 1 `aria-*` on the whole screen (the manager `<select>`); the row is a `<tr>` with `cursor: pointer` (S4) |
| 7 | No raw server identifiers in front of a human | **DELIBERATE HERE** — `ds-kpi-q` and the panel footer print table and column names on purpose. That is a defensible choice; S1 is what makes it indefensible today |
| 8 | Refresh is not a button | **PASS** — `useAutoRefresh(load)`, no refresh control |
| 9 | Freshness is the server's, not the browser's | **FAIL** — `Last read` = `new Date().toTimeString()`, the browser's clock at receipt (see prompt 13's correction 2) |

---

## 4 · Hard rules

- **No dark mode.**
- **Do not remove the rule lines.** Fix them. A number without its query is the
  thing this screen exists to refuse.
- **Do not draw the funnel** (§0).
- **Do not recompute risk, margin or Остаток on the client.** All three are
  server-derived; the client only maps them to tone
  (`RISK_TONE = {good: "ok", warn: "today", risk: "crit"}`).
- **`Остаток` stays.** It is the domain's word for net remaining and it appears
  as both a KPI label and a column header in an otherwise English-first
  codebase. That is a deliberate exception, not drift — but say in the design
  which of the two it is, because nothing in the repo currently says.
- Nine columns is the measured width. Do not add a tenth without removing one.

---

## 5 · Two states, where five belong

| Region | States it has | States it needs |
|---|---|---|
| KPI strip (6 counters) | **1** — always renders, zeros when empty | loading, empty, error, forbidden |
| `unverified_history` warning | **1** — hidden when 0 (`v-if="unverified"`), which is correct | — |
| Funnel strip | prompt 15's problem | — |
| `board-phase` status bar | **1** — `v-if="phaseMeta"`, `role="status"` | — |
| Portfolio table | **2** — `SkeletonRows`, then rows or the empty foot | error, forbidden, no-company |

The KPI strip is the sharper half of this. It renders **six zeros with six
confident rule lines under them** while the request that would have filled them
is still in flight or has already failed. Six numbers that are not numbers, each
insisting on the query it did not run.

---

## 6 · The screen

### The shell

`TenderPage :label="t('Tender')" :title="t('Director board')"` — note the label
is the *module*, not the screen, unlike prompt 13's `Operations desk`. Pick one
convention for the package and say which.

`#meta` carries three spans: the two thesis sentences (*"Every lot is counted in
exactly one stage"*, *"Numbers are read from ERP records…"*) and `Last read`.
`#actions` renders **only when filters are active** — a `ds-chip[data-tone=soon]`
listing them as `key: value · key: value`, and a `Clear filters` button.

`useEscapeBack(null, "/tender/board")` — **Escape leaves this screen for
`/tender/board`, which renders `pages/sales/SalesOrderBoard.vue`** (00-SETUP
finding #3). The director's escape hatch is a file in the sales folder. Not
yours to fix; yours to notice.

### The counter strip — `ds-kpis data-cols="3"`, six counters, two rows

| key | `data-sev` | label | value | caption | note | **rule** |
|---|---|---|---|---|---|---|
| `count` | neutral | Active tenders | `k.count` | lots in the pipeline | seen through to awaiting result | `tender_lot · result = null` |
| `win_rate` | ok | Result | `k.win_rate%` | win rate | *n* won / *n* lost · *n* pending | `result in (won, lost)` |
| `at_risk` | crit | Risk | `k.at_risk` | deadline risk | needs action today — lands on the desk | `deadline < 48h · act_now` |
| `total_value` | neutral | Portfolio value | money | contracted | sum of every open tender's value | `sum(sales_order.grand_total)` |
| `avg_margin` | ok | Avg margin | `%` | on revenue | average across tenders that have pricing | `avg(margin_on_revenue_pct)` |
| `ostatok` | neutral | Остаток (net remaining) | money | net remaining | what is still to be collected after landed cost | `value − landed − collected` |

### The table — `ds-table` inside `.board-scroll { overflow-x: auto }`

Nine columns: Row · Tender · Value · Margin on revenue · Landed · Остаток ·
Delivery deadline · Risk · Manager.

The Tender cell stacks a title, a result **or** `Unverified` chip, and an
evidence line: `{po_count} PO · {so_count} SO · {deal}`. Sort is server-side —
`risk → delivery → deal` (`_RISK_ORDER = {risk: 0, warn: 1, good: 2, none: 3}`).

Panel foot, when rows exist: *"Linked directly to ERP records"* and, in mono,
the four table names.

---

### S1 — three of six rules do not describe what the number counted

This is the screen's central defect, and it is fatal to its own thesis.

| counter | its printed rule | what the code actually does | on seed data |
|---|---|---|---|
| **Active tenders** | `tender_lot · result = null` | `visible_count` increments for **every readable deal**, before any result test (`tender.py:2091-2093`). Won and lost lots are included. | says **13**; only **10** are open |
| **Risk** | `deadline < 48h · act_now` | `dl["risk"] == "risk"`, and `_milestone` sets `risk` when **`days < 0`** — already past due — across four milestones: bid, contract, PO ETA, delivery. Nothing is 48 hours. `days <= 7` is `warn`, which this counter ignores entirely. **`TenderFunnel` prints the identical string**, where it is equally false and yields **1** — and both render on this page. | says **2**; one of them is a *purchase order ETA that passed six days ago*, which no reading of "deadline < 48h" reaches |
| **Portfolio value** | `sum(sales_order.grand_total)` | `value = so_revenue or bid_price` (`:2113`) — a Sales Order wins where one exists, otherwise the **stored bid price** from the deal's pricing plan | **2** of 13 rows come from a Sales Order; **5** come from a stored bid price; **6** are zero |

The other three are honest: `result in (won, lost)` is exactly the win-rate
denominator, `avg(margin_on_revenue_pct)` is exactly the average taken, and
`value − landed − collected` matches `pnl["ostatok"]`.

**Your deliverable is not new copy for three strings.** It is the answer to what
a rule line must be so this cannot recur: a caption a developer writes by hand
and a reader cannot verify, or something the server emits beside the number it
computed. Draw both, choose one, keep the other.

### S2 — six of thirteen rows are zero in every money column

`custom_bid_pricing` is written only for stages `priced`, `submitted`, `won`,
`lost` (`seed_tender_demo.py:663`). That is correct behaviour — a lot at `seen`
has no price to state. But the board lists all thirteen anyway, and the six
without a pricing plan render `0 · 0% · 0 · 0` across Value, Margin, Landed and
Остаток, sorted into the same table as the seven real ones, under a header that
says *Portfolio value*.

**Zero and *not yet priced* are the same pixels.** Distinguish them. This is the
same defect class as prompt 12's *Transport* column — a number that is 0 because
nothing was measured, printed as though 0 were the measurement — and its third
appearance in the package.

### S3 — the load failure is a toast over an empty table

`load()` has no error state (§2). Draw the three the screen is missing —
error, forbidden, no-company — and note the design constraint the code creates:
because `data.value` is left untouched on failure, a **failed refresh keeps the
last good numbers on screen with no indication they are stale.** That is
arguably right, and it is certainly undesigned. Pick it deliberately: last-known
values plus a staleness marker, or a cleared board plus an error.

`useAutoRefresh(load)` means this fires repeatedly, unattended, on a screen a
director leaves open.

### S4 — the row is the control, and the control is not reachable

    <tr class="board-row" @click="openDeal(r.deal)">   /* cursor: pointer */

A `<tr>` is not focusable, takes no Enter, and announces nothing. One
`aria-label` exists on the whole screen, on the manager `<select>` — which is
also the only element that had to defend itself from the row with `@click.stop`.

Two facts make the fix concrete rather than cosmetic:

- `openDeal(item)` reads `item.parent_tender || item.custom_parent_tender` in an
  object branch — but the call site passes `r.deal`, a **string**, and the
  payload builder (`tender.py:2126-2144`) never emits `parent_tender` on a row
  at all. The branch cannot fire either way; the tender context always comes
  from `route.query.tender`.
- The destination is `tender-po-control` — **prompt 10's board**. The director's
  drill-down lands on the PO control board, not on the deal.

### S5 — the manager select keeps a choice the server rejected

    <select :value="r.assigned_to" @change="assign(r, $event.target.value)">

`assign()` writes `row.assigned_to` **only on success** (`:57-58`). On failure it
raises a toast and returns. `:value` is a one-way bind, so nothing reactive
changed, so Vue does not re-render, so **the select keeps showing the manager
the server refused to assign.** The toast fades; the wrong name stays.

This is the module's only inline write outside the document centre. Design the
three states an inline write needs — in flight, confirmed, rejected-and-reverted
— and note that "rejected" must visibly move the control back.

### S6 — the phase filter says what it did; the row filter does not

Two filtering mechanisms sit on this screen and only one explains itself:

- **Phase** (from the funnel) → `board-phase` bar with `role="status"`, printing
  the phase label, the lot count, a note, and its own `Clear filter`. Exemplary.
- **Route filters** (`tenderRouteFilters`) → a `ds-chip` in `#actions` reading
  `key: value` joined by `·` — **raw filter keys**, and it is the header, far
  from the table it narrows.

They compose (`filteredRows` applies both) but they never say so. A table showing
`3 / 13 tenders` gives no way to learn which of the two filters removed which
ten.

---

## 7 · Data — derived by execution, invent nothing

Produced by running `_tender_director_payload`'s expressions over the seed's 13
lots. `_tender_deal_names` returns all 13 (every seeded deal carries an intake).

**The six counters:**

| counter | value | derivation |
|---|---|---|
| Active tenders | **13** | `visible_count` — every readable deal (S1) |
| Result | **66.7%** | won 2 (4314, 4315) / lost 1 (4316) / pending 0 → `round(2/3*100, 1)` |
| Risk | **2** | 4305 and 4314 (below) |
| Portfolio value | **10 340 000 000** | sum of the seven priced rows |
| Avg margin | *not stated* | `avg(margin_on_revenue_pct)` over the seven rows with pricing; `_compute_bid_pnl` subtracts exchange commission and taxes, which this file did not execute |
| Остаток | *not stated* | same path |

`unverified_history` = **0** — a deal is unverified only when it carries a
`result` without `submitted_at`, and the seed always writes both together
(`seed_tender_demo.py:602-609`). **The `board-warn` line never renders on demo
data**, and neither does the `Unverified` chip.

**Risk, per milestone.** `_milestone` (`tender.py`): `done → good`;
`days < 0 → risk`; `days <= 7 → warn`; else `good`. A deal's risk is the worst
of bid · contract · PO ETA · delivery.

**Corrected 2026-09-02 (coordinator review, P1-3):** that is incomplete two
ways, and both are why the P8 fix (below) first landed on a rule string that
was itself wrong. `_deal_deadlines` appends a **fifth** milestone,
`guarantee`, whenever `intake.guarantee_return` is set (`tender.py:1711-1715`)
— none of the 13 seeded deals happens to set it, which is why no worked
example below ever needed it, not because it does not exist. And "worst" is
not a magnitude comparison over dates; it is `for m in milestones: if
m["status"] == "risk": break` — the first **not-done** milestone whose days
are negative, full stop. A done milestone reads `good` regardless of how
overdue it was (4314's own walkthrough below is exactly this: bid is done,
so bid's lateness does not count — only the still-open PO ETA does). The
accurate statement is: **any milestone, not done, days < 0** — which is what
`directorBoardRuleLines.spec.js`'s at_risk case now asserts structurally,
not just as a string.

- **4305** — bid deadline was yesterday (`DEADLINE_OFFSETS: -1`), not done → **risk**
- **4314** — bid done (won); PO ETA is Hebei Rail Parts at **−6 days** with 0%
  received → **risk**
- **4315** — PO ETA is Shandong Heavy at **+3 days**, 40% received → **warn**
- **4308 (0), 4310 (+2), 4311 (+6)** — bid deadline within 7 days → **warn**
- the remaining seven → **good**

**The table, in rendered order** (`risk → delivery → deal`):

| # | lot | value | landed basis | delivery | risk | result |
|---|---|---|---|---|---|---|
| 1 | UTY-2026-4314 [DEMO] | 2 270 000 000 | from real POs | +30 | **At risk** | Won |
| 2 | UTY-2026-4305 [DEMO] | **0** | — | +90 | **At risk** | — |
| 3 | UTY-2026-4315 [DEMO] | 1 650 000 000 | from real POs | +60 | Deadline near | Won |
| 4 | UTY-2026-4308 [DEMO] | **0** | — | +90 | Deadline near | — |
| 5 | UTY-2026-4310 [DEMO] | 3 150 000 000 | 2 300 000 000 | +90 | Deadline near | — |
| 6 | UTY-2026-4311 [DEMO] | 780 000 000 | 640 000 000 | +90 | Deadline near | — |
| 7 | UTY-2026-4301 [DEMO] | **0** | — | +90 | On track | — |
| 8 | UTY-2026-4302 [DEMO] | **0** | — | +90 | On track | — |
| 9 | UTY-2026-4306 [DEMO] | **0** | — | +90 | On track | — |
| 10 | UTY-2026-4309 [DEMO] | **0** | — | +90 | On track | — |
| 11 | UTY-2026-4312 [DEMO] | 480 000 000 | 320 000 000 | +90 | On track | — |
| 12 | UTY-2026-4313 [DEMO] | 1 120 000 000 | 850 000 000 | +90 | On track | — |
| 13 | UTY-2026-4316 [DEMO] | 890 000 000 | 540 000 000 | +90 | On track | Lost |

Two authoritative margins, from the seed's own comment
(`seed_tender_demo.py:143-144`): **4314 ≈ 12,5%**, **4315 ≈ 19,6%** — chosen so
the board would not render one colour. The other five are `_compute_bid_pnl`
output over the value and landed basis above; do not print a percentage you did
not compute.

**PO / SO evidence line**, from `DEMO_PURCHASE_ORDERS` and `DEMO_SALES_ORDERS`:
4314 = `3 PO · 1 SO`, 4315 = `2 PO · 1 SO`, **every other row = `0 PO · 0 SO`**.

**Two states you cannot exercise from this data:** the `Unverified` chip and the
`board-warn` line (both need `unverified_history > 0`). Say so on the canvas
rather than seeding a fake row. This is the fifth consecutive screen with a
region that cannot populate.

Manager names are **not specified** — assignment is round-robin over the site's
non-Administrator users, and the two `seen` lots (4301, 4302) are deliberately
left unassigned, so the `— Unassigned —` option is reachable on exactly two rows.

---

## 8 · Vocabulary

| Term | Means, exactly |
|---|---|
| **rule** (`ds-kpi-q`) | the query printed under a counter, in query syntax, not a `t()` key |
| **note** (`ds-kpi-note`) | the human sentence above it, which *is* a key |
| **phase** | a funnel stage: seen · go · sourcing · priced · submitted. **Not `stage`** — `stage` is `tenderBoardFilters`' lifecycle key (identified/decided/…), and the comment at `:69-72` records that collapsing the two would silently empty the table |
| **Остаток** | net remaining: value − landed − collected |
| **Landed** | `refs["po_landed"]` — what the purchase orders actually cost to land |
| **risk / warn / good** | past due · within 7 days · beyond. Rendered as *At risk* · *Deadline near* · *On track* |
| **Unverified** | a result with no submission evidence — the number exists, the record behind it does not |
| **result** | won · lost · pending, and only when `_has_submission_evidence` passes |

---

## 9 · Responsive

Measured: one media query (`:378`) hiding `.board-ord`, the row-number column,
below 768px — matched by `hide-first-on-mobile` on the skeleton. Everything else
was `.board-scroll { overflow-x: auto }`: **the table scrolls, the page does
not** (`:325`, and the comment says exactly that).

**Corrected 2026-09-02 (agent, prompt-14 branch — forwarded from the prompt 15
agent, which hit the identical pattern in its own file, and verified
independently here).** That line described `.board-scroll`'s own rule
accurately and stopped one step short of the table inside it. `.ds-table`
carries `width: 100%` (`stabler-modernist.css:389`, shared, not this file's to
touch) and nothing in DirectorBoard.vue overrode it. A `width: 100%` table
inside `overflow-x: auto` never overflows its container — the nine columns
compress instead, and the scroller has nothing to scroll. `.board-scroll` was
real; a narrow screen never actually triggered it. Fixed with `min-width:
960px` on `.ds-table` in this file's own `<style scoped>` block (Vue scopes
that selector to elements this component renders, so the shared `.ds-table`
rule is untouched) — `min-width` and `width` are different properties, not a
cascade/specificity contest: the browser takes `max(width, min-width)`, so
`width: 100%` still governs above the floor and the floor only bites once the
container is narrower than it. **Not verified**: no jsdom in this repo, so
nothing proves a phone actually scrolls now — only that the pieces needed for
it to are present (`directorBoardTableScroll.spec.js`, source-level, with a
vacuity guard on the min-width match).

So on a phone the director gets eight columns of horizontal scroll, six KPI
cards at `data-cols="3"`, and a nine-column table whose most important cells —
Остаток and Risk — are the furthest right. Specify the phone properly; scrolling
is a mechanism, not a design.

---

## 10 · Deliverables

Artboards, 1440×900 unless stated.

1. **The board, populated** — the thirteen rows of §7 in order, counters
   13 / 66.7% / 2 / 10 340 000 000, correct risk chips, correct evidence lines.
2. **Three rule lines, corrected** (S1) — and beside them, the structural
   answer: a rule line the server emits with the number.
3. **Priced vs. not-yet-priced** (S2) — the six zero rows, distinguished.
4. **KPI strip · four states** — loading, empty, error, forbidden. Today it has
   one.
5. **Table · the three missing states** (S3), plus the stale-after-failed-refresh
   case, drawn both ways with your choice marked.
6. **The row as a real control** (S4) — focus ring, Enter, and what the manager
   `<select>` does inside a focusable row.
7. **Inline assignment · in flight / confirmed / rejected** (S5). Rejected must
   visibly revert.
8. **Two filters, one sentence** (S6) — phase and route filters explaining
   themselves together, near the table they narrow.
9. **`Unverified` and `board-warn`**, drawn from a constructed row and **labelled
   as constructed**, since seed data cannot reach them.
10. **Mobile, 390×844** — the nine-column problem, answered.
11. **The arrival from the funnel** — this screen with `?phase=sourcing` already
    applied, which is what prompt 15 navigates into. Do not redraw the strip.
12. **An annotation board** carrying the correction at the top of this file, so
    the two-implementations finding survives without this prompt.

Keep the artboards you rejected.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| P1 | Rows render in `risk → delivery → deal` order | passes |
| P2 | Counters read 13 / 66.7% / 2 / 10 340 000 000 on seed data | passes |
| P3 | Zero `badge bg-*`, zero bare `btn-*`, zero `spinner-border`, zero `table-responsive` | passes |
| P4 | `phase` and every route filter round-trip through the URL | passes |
| P5 | Loading renders `SkeletonRows`, not a spinner | passes |
| P6 | The phase filter states what it filtered, in a live region | passes |
| P7 | The `unverified` warning is hidden at 0 rather than printing a zero | passes |
| P8 | **Every** counter's rule line describes the query that produced it | **passes** (2026-09-02) — all six `rule:` strings now name the actual query (`count`, `at_risk`, `total_value` corrected); `directorBoardRuleLines.spec.js`, cross-file against `_tender_director_payload`, mutation-tested |
| P9 | *Not yet priced* is distinguishable from *zero* | **passes** (2026-09-02) — server sends `priced` per row (same `has_pricing_col`/`has_pricing` idiom used three other places in `tender.py`); the four money/percent cells and the Tender-cell chip read it instead of inferring from a number; `directorBoardPricedState.spec.js`, mutation-tested |
| P10 | A failed load renders as an error, not as "no tenders match these filters" | **passes** (2026-09-02) — `error`/`everLoaded` refs, a dedicated panel-foot branch ahead of the empty-filters one, printing the server's own message with zero new `t()` calls; `directorBoardLoadState.spec.js`, mutation-tested |
| P11 | A user without the director view sees a refusal, not an empty board | **passes** (2026-09-02) — `forbidden` (waits for `tenderViewsLoaded`) gates the KPI strip, `TenderFunnel`, the phase bar and the table behind `TenderOverview.vue`'s own refusal panel, cited rather than redesigned; `directorBoardForbidden.spec.js`, mutation-tested |
| P12 | A row is reachable and openable from the keyboard | **passes** (2026-09-02) — `role="button" tabindex="0"`, Enter and Space, `.self`-guarded so the manager `<select>` does not fire it |
| P13 | A rejected assignment returns the select to its previous value | **passes** (2026-09-02) — `assign()` captures the previous value before the request and writes it directly onto the DOM element the change event carries (necessarily imperative — `:value` is one-way, so nothing reactive changing on failure gives Vue a reason to re-patch it); `directorBoardAssignRevert.spec.js`, mutation-tested |
| P14 | Phase filter and route filters are legible together, beside the table | **passes** (2026-09-02) — `filterLabel()` maps all seven `tenderBoardFilters.js` keys to existing catalogue labels; a second bar reuses the phase bar's own `board-phase`/`role="status"` shape verbatim, directly beside it and the table; the raw `key: value` header chip is removed; `directorBoardFilterLegibility.spec.js`, mutation-tested |
| P15 | The freshness stamp reflects the server's generation time | **passes** (2026-09-02) — `generated_at`, folded with the funnel's own |
| P16 | A stale board after a failed auto-refresh says it is stale | **passes** (2026-09-02) — `stale` computed (true only once a load has succeeded and the next one fails, never on a first load), marker beside the freshness stamp in `#meta`; `directorBoardLoadState.spec.js`, mutation-tested |

**P8–P11, P13, P14, P16 verified at source/logic level only** (this repo has no
jsdom; `new Function`-lifted logic and TEMPLATE source-regex per the existing
idiom in `contractBoardReload.spec.js` / `stageColor.spec.js`) — no live-bench
or rendered-browser verification was performed for any of them. Three new
`t()` keys were added in the process (*Not yet priced*; *Refresh failed —
showing the last known numbers*; *This board is built for the director role.
Your queue for today is on the operations desk.*) and are **not yet** in the
five translation catalogues — `stabler/translations/*.csv` was out of scope
for the branch that added them. `make test` fails
`test_tender_dashboard_i18n.py`'s completeness check on exactly these three
keys, across all five locales, until they are translated; every other check
(`lint`, `compile`, `guards`, the other 274 frappe-free modules, `test-js`)
passes. See the implementing agent's final report for the full breakdown.

**Closed 2026-09-02, on `main`:** the three keys above are translated in all
five catalogues (`5330668`, out of this branch's scope, landed independently).
`make check` is fully green on this branch as of the P1 fixes below, rebased
onto that commit.

**Corrected again, 2026-09-02 (coordinator re-review found four P1s in P8,
P9, P10 and P13's own fixes):**

- **P9 follow-up.** `has_pricing` was read for the row-level fix but not for
  the header: `total_value`, `total_ost` and `margins.append` ran
  unconditionally, so an unpriced deal's row correctly showed "—" (P9) while
  still moving Portfolio value / Остаток / Avg margin by a `_BID_DEFAULTS`
  back-solved figure nobody entered. Now gated on `has_pricing`
  (`tender.py:2118-2122`), which also makes Avg margin's note ("average
  across tenders that have pricing") true rather than aspirational, with no
  wording change. Two residuals are **not** fixed by this: the Sales Order
  set behind `so_revenue` is `docstatus < 2` (DRAFT SOs still count toward
  Portfolio value), and `value = so_revenue or bid_price` resolves per-deal,
  not per-SO as the rule line's `sum(...)` phrasing reads. Tracked
  separately, not by this file. `directorBoardPricedState.spec.js`,
  mutation-tested.
- **P10 follow-up.** `await session.ensureTenderViews()` sat outside `load()`'s
  try block, so a genuine rejection there threw before `error` / `everLoaded`
  / `loading` were touched — reproducing P10's own defect ("No tenders match
  these filters.") on every cold load, plus `forbidden` staying false since
  `tenderViewsLoaded` never gets set. `loading.value = true` had also
  regressed to sit after that await, so the whole round-trip showed a
  false-empty table instead of `SkeletonRows`. Both moved inside/before the
  try (`DirectorBoard.vue:49-52`). `directorBoardLoadState.spec.js`,
  mutation-tested.
- **P8 follow-up.** The rule string this file's own §7 correction above
  explains: `"worst(bid,contract,po_eta,delivery).days < 0"` omitted the
  `guarantee` milestone, omitted "not done", and named a function that
  returns a status string, not an object with `.days`. Corrected to
  `"any milestone · not done · days < 0"` (`DirectorBoard.vue:156`), the
  predicate `_deal_deadlines` actually evaluates. `TenderFunnel.vue:117`
  carries the identical stale string and is deliberately untouched — owned by
  the prompt-15 branch, converged separately. `directorBoardRuleLines.spec.js`
  now asserts the string **and**, structurally, that `_deal_deadlines` still
  appends `guarantee` and still walks the full milestone list and that
  `_milestone` still checks `done` before `days` — so backend drift on any of
  the three original defects re-fails this test, not just a string edit.
  Mutation-tested three ways (string revert; guarantee-append removed;
  done/days order reversed).
- **P13 follow-up.** `assign()`'s revert captured `previous = row.assigned_to`
  per call and wrote it onto `event.target.value` on rejection — but two
  changes on one `<select>` share one DOM node, so both calls capture
  `previous` before either settles. A late rejection could overwrite a value
  a different, already-successful call had established, showing a manager
  who is not actually assigned server-side — worse than the pre-P13 bug,
  which at least left the user's own last choice on screen. The revert now
  only writes while the select still shows exactly what THIS call submitted
  (`event.target.value === user`, `DirectorBoard.vue:90`); the four original
  single-request cases are unaffected. `directorBoardAssignRevert.spec.js`,
  new two-in-flight-request case, mutation-tested two ways (guard dropped;
  guard compared against the wrong variable).

All four verified the same way as the rows above — source/logic level, no
live bench. Full suite green (`npx vitest run stabler/public/js/tests/`,
111 files / 1343 tests) and `make check` clean, both after rebasing this
branch onto `main` at `3e3579a`.
