# 11 · Customs queue

**Source:** `stabler/public/js/pages/tender/DeclarantQueue.vue` — 351 lines,
**0 `ds-*`, 2 `badge bg-` sites over three colour maps, 0 `spinner-border`,
3 `SkeletonRows`, 3 `EmptyState`, 16 bare `btn-*`, 0 `table-responsive`,
0 `ListToolbar`, 0 `aria-*`**.

**This is the best-behaved screen in the package so far, and it hides the package's
worst defect.** It obeys mandate 9 (skeleton, never a spinner), it has real empty
states, it routes inside the SPA, and it says in its own header comment that it is a
**read-only projection** — *"Moving a card across lanes is driven by uploading actual
documents or creating a GTD declaration, never by dragging cards around."*

**First, and it is not a screen-level finding at all:** this screen refreshes itself
every sixty seconds through `useAutoRefresh`, and the refresh calls the same `load()`
the first paint used — which sets `loading = true`, which the template answers with
`v-if="loading"`. **So the board a declarant is reading is replaced by a skeleton every
minute and then redrawn.** Measured across every consumer of that composable:

| screen | refresh fn | sets `loading = true` | has `v-if="loading"` |
|---|---|---|---|
| `DeclarantQueue` | `load` | yes | yes |
| `LogistBoard` | `load` | yes | yes |
| `DirectorBoard` | `load` | yes | yes |
| `MyTenders` | `load` | yes | yes |
| `RfqList` | `load` | yes | yes |
| `RfqDetail` | `load` | yes | yes |

**Six of six.** That is **S1**, and prompt 05 drew `RfqList` without catching it.

**Second:** this screen has a twin. `LogistBoard.vue` is 346 lines to this file's 351,
with **identical imports** and, by line count, **roughly 77 % identical content**
(80 lines differ here, 75 there). They are the same screen written twice — and the two
copies have already drifted apart on a question that matters. That is **S3**.

**Third:** the server sends this screen more than it draws. The list of *which*
documents are missing, a derived `risk`, a derived `due`, and every row **twice**. That
is **S4**.

**Scope and the ruling this prompt makes.** `LogistBoard.vue` is prompt **12**. Because
the two are one component copied, **this prompt draws the shared projection and prompt
12 draws only what is genuinely different** — six lanes instead of five, and whatever
survives S3. This mirrors the decision taken for `TenderFunnel` (drawn once, in prompt
15). Do not redraw the board twice.

---

<!-- ═══════════ PASTE BELOW THIS LINE ═══════════ -->

You are designing **one screen** of an existing product. Do not invent a design
system. Do not write code. The deliverable is design: artboards, states, and a
written rationale for each decision you make.

## 1 · The product

**Mikas Tender** is the tender module of **Stabler**, a Vue 3 SPA used by an Uzbek
trading company. It follows a public tender from the moment a state buyer publishes
it, through pricing, bidding, award, purchase orders, customs clearance and delivery.

The SPA is built on **Tabler**, with a house layer called **`stbl-ds`** on top. That
layer already exists and is not up for redesign — you extend it, you do not replace
it. There is **no dark mode** (the shell is hard-coded `light`); do not invent one.

**This screen belongs to one role.** It is the declarant's window: every purchase order
whose goods must clear Uzbek customs, grouped by how far through clearance they are.
The declarant does not create anything here. They read, and they leave for the screen
that can act.

## 2 · The role, and why the gate is simple here

Gated server-side. The gate sits **at the endpoint, not in the navigation** — hiding
a menu item was already tried, and a user who knew the URL still got a 200.

```
_require_tender_view("declarant", company)     # tender.py:2231
```

One view, one call, no per-row gate. `declarant` resolves to **System Manager · Stabler
Admin · Sales Manager · Stabler Declarant · Stabler Tender Declarant**.

**So the forbidden state on this screen is the whole page, not a region** — the
opposite of screen 09, where it was per row. Draw it once, at page level, and do not
invent a partial one.

## 3 · Nine mandates — not negotiable

1. **No links into Frappe Desk** — no `/app/...`, no `window.open`.
2. Tables are striped by default; never hand-add `table-striped`.
3. Money renders **only** through `MoneyInput`; decimal count **only** from
   `moneyFractionDigits(currency)`.
4. Dates render **only** through `DateInput` + `formatDate()`; visible format
   `dd.mm.yyyy`.
5. **One** primary button per visual region. A second colour is not a second primary.
6. Amounts stay in **their own transaction currency**.
7. Status badges come **only** from the shared status map. No page-local colour map.
8. List screens use the shared `ListToolbar` with auto-apply — no Apply/Refresh
   button; the search placeholder ends with `⌘K`.
9. Loading is a skeleton, never a bare spinner.

**Measured: this screen keeps 1, 2, 4 and 9, and breaks 5, 7 and 8.**

- **Mandate 9 is kept, and that is the point of S1** — this file has **zero**
  `spinner-border` and three `SkeletonRows`. It is the only screen in the package so
  far that obeys the mandate outright. The defect is not the skeleton; it is *when* it
  is shown, and *what shape* it is.
- **Mandate 7 — three colour maps in one file, for five statuses.**
  `LANE_CONFIGS[].headerClass` (`:66-104`), `LANE_CONFIGS[].badgeClass`, and
  `stBadge()` (`:121-129`). `released` is `bg-green-lt text-green` in the lane header
  and **`bg-success text-white`** in the lane badge — two different Tabler scales for
  one lane. `declared` is `bg-yellow-lt` paired with `text-warning`, mixing scales
  inside a single class pair. **Zero** imports of the shared status map.
- **Mandate 8** — no `ListToolbar`, no search, no `⌘K`. Filters arrive **from the
  URL only** (`tenderRouteFilters(route.query)`, `:61`); there is no way to set one on
  this screen, only to clear them all.
- **Mandate 5** — the header carries a two-button `btn-group` where the selected view
  is `btn-primary` (`:167-187`), plus a `btn-secondary` *Clear filters*. Three coloured
  buttons in one region; the primary marks a *selection*, not an action.
- **Mandate 6 has nothing to catch here** — a single `currency` for the whole payload,
  from the company. Every figure is a customs charge in company currency. Do not
  introduce a second.

**Mandate 1 is kept in a way worth naming:** both actions route inside the SPA —
`openPo` to `purchasing-order` (`:146-149`) and `openDocCenter` to `tender-documents`
(`:151-154`), the screen-09 route. No Desk link anywhere.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** This screen
  carries urgency in **colour alone** — `text-red` past due, `text-warning` within
  seven days, nothing otherwise (`:265`, `:325`).
- **A disabled control carries its reason beside it.** Nothing is disabled here.
- **The procurement policy numbers are server values** and never literal digits. **This
  screen writes `7` into two template expressions** (`:265`, `:325`) while the server
  already sent the answer — see S2.
- **No fixed-width label, badge or nav item.** Worst-case growth **3.75×**. This file
  has `max-width: 140px` on the deal label (`:234`) and `min-height: 220px` on every
  lane body (`:218`), against five lane titles that are two and three words long.
- **String interpolation exists; plurals do not.** `etaText` (`:139-144`) builds
  `` `${-r.days_left} ${t("days late")}` `` — a number glued to a translated word by
  concatenation. **`1 days late`** is what it renders, in four languages, with the
  number's position frozen in English word order.
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
  **S4 needs nothing new** — everything it asks for is already in the payload.
- **Do not write code.**

## 5 · Five states — every region, every time

| state | how it is drawn |
|---|---|
| **loaded** | the real data below |
| **empty** | the shared empty-state component |
| **error** | a danger alert with `role="alert"`, the raw message in monospace, and a "Try again" action |
| **forbidden** | a warning alert with `role="alert"`, a lock icon, and a route button |
| **not measurable** | a value that cannot be computed — say so, never render `0` |

Every region carries a test hook `data-region-state="loading|empty|error|forbidden"`.
**No CSS may bind to that attribute. Measured here: 0.**

**This screen's failure is that a failed load presents as an empty queue.** `load()`'s
`catch` fires a toast and **does not touch `data`** (`:46-50`). On a failed *first*
load `data` is still its initial `{ rows: [], lanes: {}, currency: "" }`, so
`totalCount` is `0` (`:118`) and the screen renders:

> **"No active customs declarations or won lots in the pipeline."**

A declarant reads that as *nothing to do today*. It means *the request failed*. The
toast that said so is gone in four seconds; the sentence stays.

**And on a failed *refresh* the opposite happens**, which is arguably right and is
certainly undrawn: `data` keeps its previous value, so the board shows sixty-second-old
data with nothing to say it is stale. Both need a drawing, and they are different
drawings.

**There is a third state hiding in the empty one.** The empty state is half in the
component and half beside it: an `EmptyState` (`:197-200`) followed by a loose
`<p class="text-secondary small">` explaining what will make items appear (`:201-203`).
Decide whether that sentence belongs inside the component's contract or outside it —
every other screen in the package will ask the same question.

## 6 · The screen

Route `/tender/customs`. One payload, `declarant_queue(company)`. Two views of it,
switched by a header toggle: **lanes** (default) and **table**.

Five lanes, derived server-side and never by the user (`tender.py:2300-2309`):

| lane | when |
|---|---|
| **Document Missing** | customs document requirements lack files or waivers |
| **Ready for GTD** | customs documents complete, no declaration yet |
| **Declared** | a Customs Declaration exists — Draft or Submitted |
| **Under Inspection** | Under Review · Under Inspection · Red Channel · Yellow Channel |
| **Released** | Approved · Released · Green Channel, or goods fully received |

### S1 — the live board that blanks itself every sixty seconds

`useAutoRefresh(load)` (`:56`). The composable is careful and well-written — read its
promises, because the screen breaks two of them:

> - Ticks every `intervalMs` (default 60 s) while the tab is visible.
> - PAUSES while the tab is hidden — a backgrounded board issues zero network requests.
> - Never overlaps: a still-running refresh skips the next tick.
> - **Swallows errors — an auto-refresh must never surface as an error toast**; the
>   next tick (or the page's own loader) retries.

**Broken promise one — the refresh blanks the screen.** `load()` sets
`loading.value = true` (`:43`), and the template's first branch is
`<div v-if="loading">` holding a skeleton (`:191-193`). Nothing distinguishes a first
paint from a background tick, so **every sixty seconds the whole board is replaced by
a skeleton and then redrawn**. Scroll position inside a lane is lost; whatever the
declarant was reading disappears mid-sentence.

**Broken promise two — the toast fires anyway.** The composable's `catch {}` only
catches what `refreshFn` throws. `load()` catches its own error and calls
`toast.error(...)` (`:47`) — so it never throws, the composable's swallow never runs,
and **a failed background refresh pops an error toast on a screen nobody touched.** The
composable's "silent by design" is defeated by every one of its six consumers.

**This is a module-wide finding, not a screen finding.** Six screens, same shape:
`DeclarantQueue`, `LogistBoard`, `DirectorBoard`, `MyTenders`, `RfqList`, `RfqDetail`.
**Prompt 05 drew `RfqList` and missed it.** Your answer here is the module's answer.

**Design the liveness vocabulary the module does not have.** Six screens refresh
themselves and **not one of them shows that it does.** No timestamp, no indicator, no
change signal. A declarant cannot tell whether they are looking at fresh data, or
whether a card moved lanes while they read. Draw:

1. **A refresh that does not blank.** What replaces the skeleton on a background tick —
   nothing at all, a quiet indicator, or something in between. Say what happens to a
   card the user is hovering when its lane changes underneath.
2. **A staleness signal.** "Updated 14:32" is the cheapest honest answer; decide whether
   this board needs more, and whether the answer is the same for a 5-lane queue as for
   an RFQ detail page.
3. **What a *failed* background refresh looks like** when it must not be a toast — the
   composable is right about that, and the screen needs a place to say "could not
   refresh, showing data from 14:32".
4. **Manual refresh, or not.** Mandate 8 forbids an Apply/Refresh button on a list
   screen with auto-apply filters. Decide whether that forbids one here, where the
   refresh is not a filter, and say why.

**One thing that is already right and must survive:** the composable pauses while the
tab is hidden and fires once on reveal. A design that adds a visible countdown or a
spinner ring has to keep working when the tab was backgrounded for an hour.

### S2 — the same seven days, in five places, and one twin ignores the answer

The server derives urgency and sends it (`tender.py:2276-2280`):

```python
risk = ("risk" if days is not None and days < 0
        else ("warn" if days is not None and days <= 7 else "good"))
```

and puts both `risk` and a second derived field, `due` (`"late"` / `"soon"` /
`"on_time"`), on every row.

**This screen uses neither.** It re-derives the same thing inline, twice:

```
:class="item.days_left != null && item.days_left < 0 ? 'text-red fw-bold'
      : (item.days_left != null && item.days_left <= 7 ? 'text-warning fw-semibold' : '')"
```

`:265` for the lane card and `:325` for the table, differing only in the weight classes.

**Its twin does the opposite.** `LogistBoard.vue:266` and `:321` read
`item.risk === 'risk'` — the server's field — and have **no warning tier at all**.

So a purchase order five days from its ETA is **orange on the customs board and plain
on the logistics board**, from the same row of the same payload. Neither screen is
wrong on its own; together they are two policies wearing one product.

**The number `7` lives in five places**: `tender.py:1651`, `:2279`, `:3125`, and this
file at `:265` and `:325`. §4's rule exists for exactly this, and here the server had
already answered.

**Draw the urgency vocabulary once**, from the server's three values, with severity
carried by **colour, shape and word** rather than colour alone — and say what
`on_time` looks like, because today it looks like nothing and "nothing" is also what a
missing ETA looks like (`etaText` returns `"—"` when `days_left` is `null`, `:140`).

**Then rule on the twin.** One vocabulary across 11 and 12, or a stated reason why a
logistics deadline is a different kind of deadline from a customs one.

### S3 — one screen, written twice

`DeclarantQueue.vue` (351) and `LogistBoard.vue` (346) have **identical import lists**
and differ in **80 and 75 lines respectively** — roughly **77 % identical**. What is
shared is not incidental:

| shared, verbatim or near | lines |
|---|---|
| load · error handling · `useAutoRefresh` wiring | ~15 |
| filters from the URL, `filterSummary`, `clearFilters` | ~10 |
| `viewMode` toggle and its header `btn-group` | ~20 |
| skeleton branch · empty-state branch | ~15 |
| the whole lane board: column grid, lane card, header, count badge, empty-lane note | ~40 |
| the item card: PO link, deal label, vendor line, metrics panel, actions row | ~55 |
| the whole table view | ~45 |

**What actually differs:** the API method, five lanes versus six, the lane labels and
colours, the metrics shown in the card's grey panel, and the `risk` question from S2.

**This is the design question, not a refactoring note.** Name the component: a
**read-only lane projection** that takes lanes, rows, a card body and two actions. Draw
its anatomy once. Then draw both boards as instantiations, and show what the second one
costs — because if the answer is "six lanes at 1280 px", the shared component has to
survive `col-12 col-md-6 col-lg` with six columns — roughly **193 px** of lane at 1280,
against **235 px** for five.

**Do not propose a generic board component that could draw anything.** The module has
one lane vocabulary already — screen 02's kanban, `stabler-modernist.css:369-384` — and
these two boards use **none of it**, having hand-built `card` + `card-header` +
`card-body` instead. Decide whether the read-only projection *is* that kanban with
dragging removed, or a different thing that must not look like it. The module has
already ruled that **drag-to-advance is forbidden on read-only projections**; if the two
look identical, that ruling is invisible to the user.

### S4 — what the server sends and the screen throws away

Every row in the payload carries this (`tender.py:2311-2330`):

| field | rendered? | note |
|---|---|---|
| `po`, `supplier_name`, `deal_label`, `tnved`, `customs_total`, `eta`, `days_left` | yes | |
| `missing_customs_docs_count` | yes | as *"3 docs missing"* |
| **`missing_customs_docs`** | **no** | **the list of which ones** |
| **`risk`** | **no** | S2 — re-derived inline instead |
| **`due`** (`late` / `soon` / `on_time`) | **no** | never read by either twin |
| `stage` | yes | table only |
| **`status`**, **`lane`** | **no** | *the same value as `stage`* |
| `customs_declaration`, `customs_declaration_status` | badge + `:title` | the status is in a tooltip |

**Three findings, in order of what they cost the user:**

**One — the declarant is told a number and must leave to learn the noun.** The card says
*"3 docs missing"* (`:238-240`). The three names are in the payload, unrendered. The
only way to see them is to open the document centre — screen 09, whose own S-questions
say that screen cannot take a file. Draw the list. It is the single highest-value thing
on this artboard and it costs nothing.

**Two — `stage`, `status` and `lane` are the same string, sent three times.** Pick one
in the design's vocabulary and say which. A payload that names one concept three ways
guarantees two of them drift.

**Three — every row is sent twice.** `out.append(row_item)` **and**
`lanes[lane_key]["items"].append(row_item)` (`tender.py:2332-2334`) are the same object,
serialised into both `rows` and `lanes`. So `rows` and the union of the lanes are
identical sets, and the client filters both separately (`:64`, `:105-117`). Note it as
a question about the payload's shape; **do not solve it** — it is a server change.

**And one thing the tooltip is hiding.** `customs_declaration_status` — *Under Review*,
*Red Channel*, *Green Channel* — is rendered as a `:title` on the declaration badge
(`:241`). §4's rule: a reason lives beside its control, not in a tooltip. On this screen
the channel colour is arguably the single most consequential fact about a declaration,
and it is invisible until hover — and unreachable on a phone.

### S5 — the view toggle that is not in the URL, on a screen made of URL state

Every filter this screen has comes from the route: `tenderRouteFilters(route.query)`
(`:61`), and `clearFilters` writes back to the route (`:156-158`). The screen is, in
that sense, entirely addressable — you can send someone a link to *late customs POs for
this deal* and they will see what you saw.

**Except which of the two views they see.** `viewMode` is a plain `ref("lanes")`
(`:38`). It is lost on refresh, it is not in the link, and it is not remembered. The one
piece of state that changes the whole page is the one piece that is not shareable.

Draw the answer, and while you are there, two smaller decisions in the same header:

- **`clearFilters` does `router.replace({ query: {} })`** (`:157`) — it wipes **every**
  query parameter, including any this screen does not own. Draw what "clear" means when
  the URL is shared state.
- **`filterSummary` renders raw parameter keys**: `` `${key}: ${value}` `` (`:62`),
  joined with `·` into the page's meta slot. So the user reads
  *"deal: CRM-DEAL-2026-0041 · due: late"* — machine keys, untranslated, against 3.75×
  growth. Draw what an active filter looks like when it is meant to be read.

### An architectural problem you must show, not solve

**The PO "link" is a `<span>`.** `:231` —
`<span class="fw-bold text-primary text-decoration-none cursor-pointer" @click="openPo(item.po)">`.
Not an anchor, not a button: no `href`, no `role`, no `tabindex`, no key handler, and
`text-decoration-none` on a class that is otherwise styled to read as a link. The table
below it repeats the pattern at row level (`:316`, `style="cursor: pointer"` with
`@click` and no role).

Screens 02, 09 and 10 each met a version of this and the rule is settled. This file is
the first to do it on a `<span>` that *looks* like a link, which is worse than a row
that looks like a row: it teaches the user that text of that colour is clickable, and
nothing else on the screen honours that.

## 7 · Data — use these rows, invent nothing

**Read this section before you draw.** These rows were derived by executing the lane
and risk logic in `tender.py:2270-2330` against `seed_tender_demo.py`, not transcribed
from a screen. **An earlier version of this section listed six purchase orders against
lots the seed does not create** (`UTY-2026-4291`, `UTY-2026-4277`) from vendors it does
not create; that table was replaced on 2026-09-02. Company currency **UZS**;
`moneyFractionDigits("UZS")` is 0.

The seed writes **five** purchase orders, all against the **two won lots**. Every demo
record carries a literal ` [DEMO]` suffix — that is real, on screen, and part of what
the layout has to survive. `days_left` is `eta − today`, and the seed sets each ETA as
an offset from the day it was run, so on a freshly seeded site the column below **is**
the offset.

| vendor | tender | HS code | customs | days left | `risk` | lane |
|---|---|---|---|---|---|---|
| Hebei Rail Parts [DEMO] | Qurilish materiallari kombinati [DEMO] | 7302 10 900 0 | 41 000 000 | **−6** | `risk` | **Document Missing** |
| Shandong Heavy [DEMO] | O'zbekiston temir yo'llari AJ [DEMO] | 8607 19 100 0 | 62 000 000 | **3** | `warn` | **Document Missing** |
| Temiryo'l ta'minot [DEMO] | Qurilish materiallari kombinati [DEMO] | — | — | **4** | `warn` | **Released** |
| UralVagonSnab [DEMO] | Qurilish materiallari kombinati [DEMO] | 7302 40 000 0 | 88 000 000 | 45 | `good` | **Document Missing** |
| Sanoat kompleks [DEMO] | O'zbekiston temir yo'llari AJ [DEMO] | — | — | 75 | `good` | **Document Missing** |

The card's tender label is the buyer's organisation, not the lot number — `_deal_label`
returns the deal's `organization`, so *Qurilish materiallari kombinati [DEMO]* is
**37 characters** in the default language.

**Eight things in this data the design must not smooth over:**

1. **Shandong Heavy is 3 days from its ETA and missing documents.** It is the row the
   whole screen exists for, and today its urgency is orange text and nothing else. The
   lane already says *Document Missing*; the card must say **which** — the payload
   carries `["License Copy / Certificate", "Customs Declaration (GTD)"]`.
2. **Hebei Rail Parts is six days past its ETA with nothing received**, and it is the
   most urgent thing on the board. Its twin, the logistics board, draws the same
   purchase order as **on time** — see prompt 12 §S1. Whatever urgency vocabulary you
   design here is read by someone who also reads that board.
3. **Three of the five lanes cannot be reached on demo data.** *Declared* and *Under
   Inspection* both require a **Customs Declaration**, and `seed_tender_demo.py` creates
   none. *Ready for GTD* requires zero missing customs documents, which never happens
   because both customs requirements are unverified ticks (below). So the board is
   **four cards in one lane and one in another**, with three empty columns — and no
   artboard in this package yet shows a lane layout under that load. Draw it.
4. **The two missing documents are the same two on every row, and both are ticked.**
   The seed writes them as `status: "ready"` with **no file attached**, which the parser
   records as `unverified` — never `done`. So the lane says *Document Missing* while the
   checklist behind it says *ready*, and nothing on this screen reconciles the two.
5. **Temiryo'l ta'minot is `Released` and painted `warn`.** It is fully received and
   out of customs; `risk` is derived from `days_left` with no knowledge of the lane, so
   a finished purchase order is drawn as *due soon* four days from an ETA that no longer
   matters. Lane position and urgency are two independent severities and the board shows
   one as a column and the other as text colour inside it. Say how they combine.
6. **Two rows have no HS code and no customs total** — the seed writes no landed charges
   at all when the customs amount is zero. Today those cells are `v-if`-ed away in the
   card (`:253`, `:257`) so the metrics panel silently shrinks: three facts on one card,
   one on another, with nothing saying anything is absent rather than zero.
7. **No row has a null ETA, so the demo cannot produce the *not measurable* state.** The
   guard is real — `days_left` is `None` for a purchase order with no `schedule_date`,
   `etaText` returns `"—"`, and the urgency expression renders **the same nothing an
   on-time row gets**. Draw that state; state plainly that seeded data cannot exercise
   it, which is exactly why it has survived.
8. **A lane can be empty, filtered to empty, or unreachable** — and *"No items in this
   stage"* says the same thing for all three. With a `deal` filter applied, four of five
   lanes say it, and nothing says the filter is why.

**Dates:** `dd.mm.yyyy` via `formatDate()`. **Money:** company currency only, one
currency for the payload; `moneyFractionDigits("UZS")` is 0.

## 8 · Vocabulary

**Lanes** — the module has a kanban vocabulary (`stabler-modernist.css:369-384`,
settled on screen 02) and this file uses **none of it**: `card` + `card-header` with a
`headerClass` colour + `card-body` with an inline `min-height: 220px` and an inline
`background-color: var(--tblr-bg-surface-tertiary, #f8fafc)`. Decide whether a
**read-only** lane is that component or a different one — see S3.

**Cards in a lane** — `card border shadow-xs item-card p-2 bg-white` inside a
`card-body` inside a `card`: three nested card frames, the same shape screen 10 has and
screen 01 settled a rule for.

**The metrics panel** — `p-2 rounded border-0 bg-light small` holding up to three
label/value rows (`:252-270`). It is a definition list drawn as flex rows; the layer has
no name for it, and screens 03, 09 and 10 each built their own. **Name it.**

**Status** — `ds-status` with the shared map. Here: three page-local maps for five
values, `bg-success` and `bg-green-lt` for the same lane, `bg-yellow-lt text-warning`
mixing two scales. **Zero** shared-map imports.

**Urgency** — a *second* severity, orthogonal to status, carried in colour only, with
its threshold hard-coded twice. It needs a name and three codes. See S2.

**Tables** — `ds-table` inside a mandatory `table-responsive` wrapper; numeric cells
`ds-td-num`. Measured: `ds-table` **0**, `table-responsive` **0**, `card-table` **1**.
The table view is **nine columns**.

**Toolbar / view switch** — no `ListToolbar`. The view toggle is a `btn-group` in the
page-head `#actions` slot with the active view as `btn-primary`. The layer has no
segmented control; screen 10 needs a tab strip it also lacks. **Decide whether these are
the same component**: a tab strip and a two-way view switch are close enough that the
module should not gain both by accident.

**Filter summary** — rendered into `TenderPage`'s `#meta` slot as raw `key: value`
strings. The layer has `ds-meta`; it has no filter chip.

**Loading** — `SkeletonRows :cols="5" :rows="4"` (`:192`) inside a `card card-body`.
**The default view is lanes, and this is a table skeleton.** The mandate is obeyed and
the shape is wrong: a five-column, four-row grey table appears where a five-lane board
is about to be. Draw the lane skeleton.

**Empty** — `EmptyState` plus a loose explanatory `<p>` beside it (`:196-204`), and a
per-lane inline note (`:219-221`) that is not the component at all.

**Actions** — `btn-xs` at four sites (`:277`, `:285`, `:336`, `:341`) — a size the
layer does not define; `ds-btn` has no `xs`. Two actions per card, two per row, both
outline or ghost, none primary.

**Forbidden here:** `class="badge bg-*"`; a page-local colour map; `card-table`;
`btn-xs`; a `<span>` or `<tr>` that is a click target without a role, a tabindex and a
key handler; a threshold digit in a template expression; a severity carried by colour
alone; a translated word concatenated to a number.

## 9 · Responsive

Draw at **1280**, **992** and **640** px.

- The lane grid is `col-12 col-md-6 col-lg` (`:208`) — so five lanes sit in one row
  only above `992`, become **two-up** between 768 and 992, and stack at 640. At 1280 a
  lane is roughly **235 px** wide; **prompt 12's board has six lanes in the same grid**,
  which is ~193 px. Design for the six.
- Each lane body carries `min-height: 220px` (`:218`) — so an empty board is five
  1 100 px-tall columns of nothing at 640.
- The item card truncates the deal label at `max-width: 140px` (`:234`) with the full
  text in a `:title` — unreachable on a phone, and 3.75× growth makes it worse.
- The table view is **nine columns** with **no `table-responsive` wrapper**. It will
  push the page sideways. Nothing may scroll the page horizontally.
- The header holds a two-button group plus a *Clear filters* button plus the filter
  summary in the meta slot. At 640 that is a page title, a summary line and three
  controls.

## 10 · Deliverables

1. **S1's refresh**: the board mid-background-tick, drawn — what changes, what does not,
   and what happens to a card whose lane changes while the pointer is on it.
2. **The liveness vocabulary**: a staleness indicator, a failed-refresh state that is
   not a toast, and a stated answer on whether a manual refresh control is allowed
   under mandate 8. **This is the module's answer, not this screen's** — six screens
   inherit it.
3. **The lane skeleton**, replacing the table skeleton that stands in front of a lane
   board today — plus the table skeleton for the table view, since both exist.
4. **S2's urgency vocabulary**: three server values, three codes each (colour, shape,
   word), `on_time` distinguished from *no ETA*, and a rule for what urgency means
   inside `Released`.
5. **A stated ruling on the twin's warning tier** — one vocabulary across 11 and 12, or
   a reason why not.
6. **S3: the read-only lane projection drawn once as a named component** — anatomy,
   lane header, card body slot, actions — with **both** boards drawn as instantiations
   and the six-lane case sized at 1280 and 992.
7. **A stated answer to whether the read-only projection is screen 02's kanban with
   dragging removed**, or a different component that must not resemble it.
8. **S4: the missing-document list on the card**, at 1280 and 640, including what it
   does when there are eleven of them.
9. **The declaration's channel out of its `:title`** — *Red Channel* is a severity, not
   a tooltip.
10. **All five states** — including the **error** state that today reads as an empty
    queue, the **stale** state after a failed refresh, and the page-level **forbidden**
    state the file has no drawing for.
11. **The empty lane distinguished from the filtered-to-empty lane.**
12. **S5**: the view toggle's home decided, `clearFilters`' scope decided, and the
    filter summary drawn as something a person reads.
13. **The metrics panel named** and given a place in the layer — three screens have
    built it independently.
14. **A decision on the view switch versus screen 10's tab strip**: one component or
    two, said once.
15. **The nine-column table at 640**, wrapped, with a stated answer for what it drops.
16. **`1 days late` fixed** — a form that survives four languages without plurals.
17. Every question your design raised, listed.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `DeclarantQueue.vue`, `LogistBoard.vue`,
`composables/useAutoRefresh.js` and `stabler/api/tender.py` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | **A background refresh does not replace the screen with a skeleton.** The loading flag a first paint sets is not the flag a tick sets — measured across all six consumers of `useAutoRefresh` | 6 / 6 blank | 0 / 6 |
| K2 | **A failed background refresh is not a toast.** `load()` catches its own error and calls `toast.error`, so the composable's documented swallow never runs | 6 / 6 toast | 0 / 6 |
| K3 | **The board says how fresh it is.** Six screens auto-refresh and none shows a timestamp or a change signal | 0 | asserted |
| K4 | **No urgency threshold is a literal in a template.** `7` appears at `:265` and `:325` while `risk` and `due` are already on every row | 2 | 0 |
| K5 | **Urgency comes from the server's field.** `risk` / `due` are read; the twin already reads `risk` and this file does not | 0 / 2 | 1 vocabulary |
| K6 | **Urgency is not carried by colour alone.** Three codes — colour, shape, word — and *no ETA* is distinguishable from *on time* | colour only | asserted |
| K7 | **No page-local colour map.** `LANE_CONFIGS.headerClass`, `LANE_CONFIGS.badgeClass` and `stBadge()` are three maps of five values; `released` uses two different scales | 3 / 0 | 0 / 1 |
| K8 | **The missing-document list is rendered, not just its count.** `missing_customs_docs` is sent on every row and read nowhere | 0 | asserted |
| K9 | **A failed load is not the empty state.** `catch` leaves `data` untouched, so an initial failure renders "No active customs declarations…" | 1 | 0 |
| K10 | **The skeleton matches the view it precedes.** A 5-column `SkeletonRows` stands in front of a five-lane board | 1 | 0 |
| K11 | **Nothing is a click target without a role, a tabindex and a key handler.** A `<span>` styled as a link (`:231`) and a `<tr>` with `cursor: pointer` (`:316`) | 2 | 0 |
| K12 | **The declaration's channel is beside the badge, not in its `:title`** | 1 | 0 |
| K13 | **The view mode survives a refresh and a shared link**, on a screen whose every filter already does | 0 | asserted |
| K14 | **The filter summary is readable text, not raw query keys.** `` `${key}: ${value}` `` at `:62` | 1 | 0 |
| K15 | **No number is concatenated to a translated word.** `etaText` produces `1 days late` | 3 sites | 0 |
| K16 | **The table view is inside `table-responsive`.** Nine columns, no wrapper | 0 | 1 |
| K17 | **No `btn-xs`.** The layer defines no `xs` size | 4 | 0 |
| K18 | Every region carries `data-region-state`, and no two of its branches can be true at once | 0 | = region count |
| K19 | **The two boards share one component.** 80 lines differ here and 75 there, out of 351 and 346 — the projection is drawn once and instantiated twice | 2 files | 1 + 2 |
| K20 | **Regression guards — already right, must stay so.** Zero `spinner-border` and three real `SkeletonRows` · `EmptyState` used at three sites · both actions routing inside the SPA (`:146-154`) rather than to Desk · lanes derived server-side and **not draggable** · the auto-refresh pausing while the tab is hidden and firing once on reveal | asserted | unchanged |

**K20's last item is the one a "live board" redesign will break.** The composable
issues zero requests while backgrounded and fires once on reveal; a countdown ring, a
polling indicator or a manual timer that keeps ticking in a hidden tab has traded a
correct behaviour for a decoration.

**K1–K3 are the module's criteria, not this screen's.** Six screens carry the defect;
prompt 05 shipped one of them. State plainly whether your answer works for an RFQ detail
page as well as for a five-lane board, because both will adopt it.

State plainly which of these your design satisfies, and name anything it cannot.
