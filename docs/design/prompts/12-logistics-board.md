# 12 · Logistics board

**Source:** `stabler/public/js/pages/tender/LogistBoard.vue` — 346 lines,
**0 `ds-*`, 2 `badge bg-` sites over three colour maps, 0 `spinner-border`,
3 `SkeletonRows`, 3 `EmptyState`, 16 bare `btn-*` (4 of them `btn-xs`),
0 `table-responsive`, 0 `ListToolbar`, 0 `aria-*`**.

**This prompt draws a difference, not a screen.** Prompt 11 drew the read-only lane
projection once, as a named component, from `DeclarantQueue.vue`. This file is that
same component with six lanes instead of five and a different payload behind it —
identical import lists, and by line count roughly three quarters the same file. **Do
not redraw the board.** Draw what is genuinely different, and instantiate 11's
component for the rest.

What is genuinely different is larger than "one more lane", and none of it was visible
until this file was measured on its own:

- **`risk` does not mean here what it means on 11.** Same field name, same payload
  shape, **different question** — and the customs board's answer is not available here.
  That is **S1**, and it corrects the record.
- **Four of the six lanes cannot be reached on a seeded site**, because the record that
  fills them is never created. That is **S2**.
- **The board's only money column is empty in every row**, by construction, and the
  word above it names half of what it would contain. That is **S3**.

---

## Corrections this file owes the package

Both were measured on 2026-09-01 while writing this prompt. Neither changes a decision
already taken; both change a sentence that is now wrong in a file someone will read.

**1 · `00-SETUP.md` and prompt 11 describe the twins' drift incorrectly.** The record
says *"the same PO five days from its ETA is orange on the customs board and plain on
the logistics board, from the same row of the same payload"*, framed as `LogistBoard`
lacking a warning tier that `DeclarantQueue` has.

Measured, that is not what is happening. The two endpoints derive `risk` from **two
different comparisons**:

| | `declarant_queue` | `logist_board` |
|---|---|---|
| field | `risk` | `risk` |
| values | `risk` · `warn` · `good` | `risk` · `good` |
| derived from | days between today and the PO's ETA (`< 0` → risk, `<= 7` → warn) | `not received and eta > delivery` — will the shipment arrive **after the promised deadline** |
| what it colours | the ETA | the **delivery deadline** |

They are two answers to two questions and they happen to share a field name. Adding a
`warn` tier to `logist_board` would not reconcile them, because there is nothing to
reconcile — it would invent a third meaning. The **observable symptom** in the record
stands (one board paints a row, the other does not); the **cause** stated there does
not.

**2 · Prompt 11's client-side half of that finding has been fixed and shipped.**
`DeclarantQueue` no longer re-derives urgency with a hard-coded `7` in two template
expressions — it reads the server's `risk` through a single `etaClass()`
(commit `26481f1`, on prod as of `746ece2`). Prompt 11's **K4** and **K5** are
satisfied for that file. The four remaining `7`s are server-side (`tender.py:1651`,
`:2279`, `:3125`) and **`LogistBoard` never had one** — it has no day arithmetic at all,
which is why it also has none of 11's `1 days late` defect. **K15 does not apply to
this screen.**

**3 · `seed_tender_demo.py` now writes document requirements.** `00-SETUP.md` records
that it creates none; it writes six per deal, with roles (`:571-597`). Exactly **one**
carries `role: "logistics"` — *CMR / Waybill* — and that single row is what puts every
un-received PO into this board's first lane. Prompt 09's separate finding, that the
seed creates no requirements, is the sentence that is now stale.

---

<!-- ═══════════ PASTE BELOW THIS LINE ═══════════ -->

You are designing **one screen** of an existing product, and most of it has already
been designed. Do not invent a design system. Do not write code. The deliverable is
design: artboards, states, and a written rationale for each decision you make.

## 0 · What you are extending

The **read-only lane projection** was drawn in the previous session, from the customs
queue: a lane grid, a lane header with a count, an item card with a metrics panel and
two routing actions, a table view of the same rows, a view toggle, and the liveness
vocabulary (staleness line, failed-refresh state, no manual Refresh button) that six
screens inherit.

**This screen is that component, instantiated a second time.** Your job is the
delta — the six-lane sizing, the payload that is different, and three defects that
belong to this file alone. If you find yourself redrawing the card anatomy, stop: it
is settled, and drawing it twice is how two boards become two components again.

## 1 · The product

**Mikas Tender** is the tender module of **Stabler**, a Vue 3 SPA used by an Uzbek
trading company. It follows a public tender from the moment a state buyer publishes
it, through pricing, bidding, award, purchase orders, customs clearance and delivery.

The SPA is built on **Tabler**, with a house layer called **`stbl-ds`** on top. That
layer already exists and is not up for redesign — you extend it, you do not replace
it. There is **no dark mode** (the shell is hard-coded `light`); do not invent one.

**This screen belongs to one role.** It is the logistician's window: every purchase
order whose goods are moving, grouped by how far along the journey they are. The
logistician does not create anything here. They read, and they leave for the screen
that can act.

## 2 · The role, and why the gate is simple here

Gated server-side, at the endpoint rather than in the navigation:

```
_require_tender_view("logist", company)        # tender.py:2343
```

One view, one call, no per-row gate. `logist` resolves to **System Manager · Stabler
Admin · Sales Manager · Stabler Logist · Stabler Tender Logistics**.

**The forbidden state is the whole page, not a region** — same as 11, and the opposite
of screen 09 where it was per row. The file has no drawing for it.

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

**Measured: this screen keeps 1, 2, 4 and 9, and breaks 5, 7 and 8** — the same profile
as its twin, with one difference worth drawing.

- **Mandate 7 — three colour maps for six lanes, and this file's are worse than 11's.**
  `LANE_CONFIGS[].headerClass` (`:67-110`), `LANE_CONFIGS[].badgeClass`, and `stBadge()`
  (`:129-137`). The header map and `stBadge()` agree; the **badge map names a different
  Tabler token family** for three of the six lanes: `delivered` is `bg-cyan-lt
  text-cyan` in the header and **`bg-info`** in the badge; `accepted` is `bg-green-lt`
  against **`bg-success`**; `booking` is `bg-yellow-lt text-warning` against
  **`bg-warning`**. Hue names and semantic names for the same lane, in the same file.
  **Zero** imports of the shared status map.
- **And the six lane labels are written twice.** `LANE_CONFIGS[].label` and `stLabel()`
  (`:139-147`) are the same six strings in two places — the lane header reads one, the
  table's Stage column reads the other.
- **Mandate 8** — no `ListToolbar`, no search, no `⌘K`. Filters arrive **from the URL
  only** (`tenderRouteFilters(route.query)`); there is no way to set one here, only to
  clear them all.
- **Mandate 5** — a two-button `btn-group` where the selected view is `btn-primary`
  (`:170-186`), plus a `btn-secondary` *Clear filters*. Three coloured buttons in one
  region, and the primary marks a *selection*, not an action.
- **Mandate 3 has something to catch here that 11 did not** — see S3. One money
  column, company currency, and `moneyFractionDigits("UZS")` is 0.

**Mandate 1 is kept the same way:** both actions route inside the SPA — `openPo` to
`purchasing-order` and `openDocCenter` to `tender-documents` (`:149-157`).

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** This screen
  carries it in **colour alone**, on one field, in two places (`:266`, `:321`).
- **A disabled control carries its reason beside it.** Nothing is disabled here.
- **No fixed-width label, badge or nav item.** Worst-case translation growth **3.75×**.
  This file caps the **lane title** at `max-width: 110px` (`:216`) — a cap its twin does
  not have — against six labels including *Border Crossed* and *In Transit*. It also
  carries the twin's `max-width: 140px` deal label (`:237`) and `min-height: 220px`
  lane body (`:221`).
- **String interpolation exists; plurals do not.** Nothing on this screen concatenates
  a number to a translated word — it has no day arithmetic. Do not introduce one.
- **The procurement policy numbers are server values** and never literal digits. This
  file writes none, and must not gain one.
- **No new backend field, doctype or migration.** Raise it as a **question**. S1 and S2
  both end in a question the design must state and must not answer with a schema.
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

**This screen inherits its twin's failure and states it more plausibly.** `load()`'s
`catch` fires a toast and does not touch `data`, so a failed *first* load leaves the
initial `{rows: [], lanes: {}}` and the screen renders:

> **"No active shipments or won lots in the pipeline."**
> *"When a tender deal is awarded or a purchase order is raised, shipment requirements
> will appear here."*

Two sentences, and the second one **explains the emptiness** — so a logistician reads a
failed request as *nothing has shipped yet*, with a paragraph confirming it. The
customs board's version of this sentence is one line; this one argues its case.

**The empty state is again half in the component and half beside it** — an `EmptyState`
(`:200-203`) followed by a loose `<p class="text-secondary small">` (`:204-206`).
Prompt 11 raised whether that sentence belongs inside the component's contract and
deliberately did not settle it. **This screen is the reason it has to be settled**: two
instantiations, two hand-written paragraphs, and the paragraph is where the misleading
sentence lives.

**Not measurable is the state this board needs most.** See S1.

## 6 · The screen

Route `/tender/logistics`. One payload, `logist_board(company)`. Two views of it,
switched by a header toggle: **lanes** (default) and **table**.

Six lanes, derived server-side and never by the user (`tender.py:2431-2445`):

| lane | when |
|---|---|
| **Planning** | goods not received, no freight booking, or logistics documents outstanding |
| **Booking** | a Freight Booking exists with status *Booked* or *Pending* |
| **In Transit** | Freight Booking status *In Transit* |
| **Border Crossed** | *Border Crossed* · *Crossed Border* · *Customs Cleared* |
| **Delivered** | Freight Booking status *Delivered* |
| **Accepted** | `per_received >= 100` |

The lane derivation is an `if/elif` chain and **`received` wins over everything** — a
fully received PO is *Accepted* whatever its freight booking says.

### S1 — one field name, two questions, and neither of them is "is this late"

`logist_board` sends `risk` on every row (`tender.py:2458`):

```
late = bool(not received and eta and delivery and eta > delivery)
"risk": "risk" if late else "good"
"due":  "late" if late else "on_time"
```

Two fields, one boolean, and the client reads `risk` and **never reads `due`**.

The screen colours the **delivery deadline** with it — `text-red fw-bold` on the card
(`:266`), `text-red` in the table (`:321`) — and colours nothing else. So the question
this board asks is: *will this shipment arrive after the date we promised?*

The customs board asks a different question with the same field name: *how many days
until the ETA*, three tiers, painted on the ETA. **Both boards read the same purchase
orders from the same helper** (`_po_rows_for_views`, called at `:2233` and `:2345`), so
the same row genuinely renders differently on the two screens — but not because one is
missing a tier.

**Three things follow, and the design must show all three.**

1. **A missed ETA is invisible on this board.** `late` compares the ETA to the
   *deadline*, not to *today*. A purchase order whose ETA was six days ago, with nothing
   received, is `risk: "good"` and draws plain — while the same row on the customs board
   is red. **The seed contains exactly this row** (see §7, Hebei Rail Parts). Nothing on
   the logistics board can express *overdue*.
2. **Absence renders as reassurance.** `late` requires `eta and delivery`. A PO with no
   ETA, or a deal with no delivery deadline, evaluates to `False` → `"good"` → the
   deadline draws in the default colour, identical to a shipment comfortably on time.
   **This is the *not measurable* state, on the one field the board conveys urgency
   with**, and it has no drawing.
3. **`due` is a second name for the same boolean and is sent to nobody.** Along with
   `stage` · `status` · `lane` — three names, one value — and `event_date`, unread.

**What the design must produce:** a severity vocabulary for *this* board's question,
with three codes (colour, shape, word), in which **on time**, **will miss the
deadline**, **ETA already passed**, and **cannot be determined** are four visibly
different things. Say which of them the server can already answer (two), which needs a
comparison the client can make from data it already has (one — today against `eta`),
and which is a question for the backend. **Do not propose a new field.**

**And state the ruling prompt 11 deferred**: one urgency vocabulary across both boards,
or two — with the reason. The honest answer may be *two vocabularies, because they are
two questions*; if so, say how a person who reads both boards is meant to know that.

### S2 — six lanes, and four of them cannot be reached

Every lane except *Planning* and *Accepted* is selected by a **Freight Booking**:

```
elif fb_status == "Delivered":                                    → delivered
elif fb_status in ("Border Crossed", "Crossed Border", ...):      → border
elif fb_status == "In Transit":                                   → transit
elif fb and fb_status in ("Booked", "Pending"):                   → booking
```

`seed_tender_demo.py` **creates no Freight Booking**. The doctype exists
(`stabler/stabler/doctype/freight_booking`); the demo data never writes one. So on a
seeded site `fb` is always `None`, and the chain can only ever produce:

- **Accepted** — `per_received >= 100`
- **Planning** — everything else, via the missing-documents branch or the final `else`

**Two of six lanes carry every row; four are permanently empty.** This is the same
class of finding as prompt 05's *the seed creates no RFQ at all* — the surface exists,
the record it projects does not.

It also means the lane the board opens on is **misnamed in the general case**. The
final `else` reads `lane_key = "booking" if fb else "planning"`, so a purchase order
with complete documents and no freight booking lands in *Planning* — not because
anything is being planned, but because nothing has been booked. The file's own header
comment covers this (*"pending files/waiver **or booking needed**"*); the lane label
does not.

**What the design must produce:** a lane header that can say **why** a lane is empty —
*nothing here* is not the same as *nothing can ever be here on this data* — and a
stated answer for whether a six-lane board whose middle four are structurally empty
should still draw six columns at 1280. Prompt 11 asked for *empty* to be distinguished
from *filtered to empty*; this screen adds a third: **unreachable**. Draw all three.

**And the one thing that would explain a lane is a tooltip.** `freight_booking_status`
— *Booked* · *In Transit* · *Border Crossed* · *Delivered*, the literal value the lane
chain branches on — is rendered **only** as a `:title` on a blue badge (`:244`), and
only on rows that have no missing documents. **The field that decides which lane a card
sits in is reachable by hovering it.** This is the same defect prompt 11 found on the
customs declaration's channel, on a field with more consequence: the channel described
a row, this one places it.

**And name the question this raises for the product**, without answering it with a
schema: a Freight Booking is the only thing that moves a row out of *Planning*, and
nothing in this module creates one.

### S3 — the only money on the board is zero, and the word above it is wrong

The card's metrics panel and the table both show one figure, labelled **Transport**,
rendered through `formatMoney` in company currency. The server derives it
(`tender.py:2384`):

```
transport = sum(c["amount"] for c in charges if c["type"] in ("transport", "loading"))
```

**Two defects, and they compound.**

1. **The label names one of the two types it sums.** The figure is transport *plus
   loading*; the column says *Transport*. This is the third time this package has caught
   a name promising something the code does not do — screen 09's `upload_tender_document`
   is a bind, screen 10's `l.amount` is server-owned. **Mandate 6's sibling problem**:
   the number is right and the word is not.
2. **The seed writes only `{"type": "customs"}` landed charges** (`:415-424`). No
   `transport`, no `loading` — so the sum is **`0` for every row on a seeded site**. And
   because the card guards on `v-if="item.transport"`, zero is falsy: **the Transport
   line is not rendered at all**, and the table prints `—`. The board's single
   distinguishing column is absent from every card, and the metrics panel silently
   shrinks — the same defect 11 found on the customs board's HS code and customs total,
   here applied to the board's *only* figure.

So on the data anyone will actually see, the metrics panel contains **the ETA and the
deadline and nothing else**, and the card is thinner than its customs twin for a reason
no one is told.

**What the design must produce:** the label corrected to what it sums; **zero, absent
and not-yet-classified drawn as three different things** rather than as a missing row;
and a metrics panel whose height does not depend on how much of it is populated.

### An architectural problem you must show, not solve

**`out.append(row_item)` and `lanes[lane_key]["items"].append(row_item)` put the same
object into the payload twice** (`:2469-2471`). `rows` and the union of the lanes are
identical sets; the client filters them separately (`filteredRows` and `filteredLanes`
each run `filterTenderRows` over their own copy). Prompt 11 raised it on the customs
board. It is the same line of code, in the same shape, in the second endpoint. **Raise
it again; it is a server change and it is not yours to make.**

## 7 · Data — use these rows, invent nothing

**Read this section before you draw.** The rows below were derived by executing the
lane and risk logic against `seed_tender_demo.py` on **01.09.2026**, not transcribed
from a screen. Company currency **UZS**; `moneyFractionDigits("UZS")` is 0.

The seed creates **five** purchase orders, across the **two won lots** — `UTY-2026-4314`
(buyer *Qurilish materiallari kombinati*) and `UTY-2026-4315` (buyer *O'zbekiston temir
yo'llari AJ*). The card's tender label is the buyer's name, not the lot number
(`_deal_label` returns the deal's `organization`).

| vendor | tender | PO ETA | deadline | received | `risk` | Transport | lane |
|---|---|---|---|---|---|---|---|
| Hebei Rail Parts | Qurilish materiallari kombinati | **26.08.2026** | 01.10.2026 | 0 % | `good` | *(absent)* | **Planning** |
| UralVagonSnab | Qurilish materiallari kombinati | 16.10.2026 | 01.10.2026 | 0 % | **`risk`** | *(absent)* | **Planning** |
| Shandong Heavy | O'zbekiston temir yo'llari AJ | 04.09.2026 | 31.10.2026 | 40 % | `good` | *(absent)* | **Planning** |
| Sanoat kompleks | O'zbekiston temir yo'llari AJ | 15.11.2026 | 31.10.2026 | 0 % | **`risk`** | *(absent)* | **Planning** |
| Temiryo'l ta'minot | Qurilish materiallari kombinati | 05.09.2026 | 01.10.2026 | **100 %** | `good` | *(absent)* | **Accepted** |

Purchase order ids follow Frappe's `PUR-ORD-{YYYY}-{#####}` series and depend on the
site's counter — identify rows by vendor, not by a number you have made up.

**Seven things in this data the design must not smooth over:**

1. **Four cards in one lane, one in another, and four empty lanes.** That is the whole
   board. Draw it — a six-column grid holding two populated columns is what a
   logistician opens every morning, and no artboard in this package shows a lane layout
   under that load.
2. **Hebei Rail Parts is the row S1 exists for.** Its ETA passed **six days ago** and
   nothing has been received; `risk` is `good` because 26.08 is before the 01.10
   deadline, so the card draws entirely in the default colour. The same purchase order
   is **red on the customs board**. One payload, two screens, opposite readings — and
   the logistics board is the one that is wrong about the world.
3. **Shandong Heavy is 40 % received and the board cannot say so.** `received` is sent
   as a boolean (`per_received >= 100`); the percentage never leaves the server. A
   part-delivered shipment renders identically to one that has not left the factory.
   *Not measurable* is the wrong answer here — the value exists and was thresholded
   away. Raise it.
4. **Every Transport figure is absent, on all five rows**, for the reason in S3. Do not
   draw a populated Transport column and do not draw an empty cell that looks like a
   value of zero.
5. **Every row's one logistics document is an unverified tick.** The seed's
   `role: "logistics"` requirement is *CMR / Waybill*, written as `status: "ready"` with
   **no file attached** — which the parser records as `unverified`, never `done`. So
   `missing_logistics_docs` is `["CMR / Waybill"]` on all four *Planning* rows, and the
   card shows a count, never the noun. The payload has been carrying the name all along
   and no board has ever rendered it.
6. **Two vendor names are three words of Uzbek and two are two words of Chinese
   transliteration** — *Temiryo'l ta'minot*, *Qurilish materiallari kombinati* against
   *Hebei Rail Parts*. The 110 px lane cap and the 140 px deal cap are both hit by the
   real data, in the default language, before any translation growth.
7. **Both deadlines are lot-level, not PO-level.** Three purchase orders share
   01.10.2026 because they belong to one deal. The board draws the deadline per card, so
   the same date appears three times in one lane with nothing saying it is one promise,
   not three.

**Dates:** `dd.mm.yyyy` via `formatDate()`. **Money:** one currency for the whole
payload, from the company.

## 8 · Vocabulary

**Lanes.** Instantiate prompt 11's projection. The only vocabulary question that is
genuinely new is the **lane header at six columns**: 11's header carries an icon, a
title and a count pill at ~235 px; here it has ~193 px and one label is *Border
Crossed*. Decide whether the header wraps, drops the icon, or the count moves — and say
it once, for both boards, since a component that behaves differently at five and six
lanes is two components again.

**The six lane names** are `Planning · Booking · In Transit · Border Crossed ·
Delivered · Accepted`. They are a journey, and the customs board's five are a
*process* — the same component is carrying two different kinds of sequence. Say whether
that matters to the lane header's design.

**The status map.** Both boards must import one shared map. Six values here, five
there, with `Accepted` and `Released` being different words for *the goods are ours
now*. State whether that is one token or two.

## 9 · Responsive

Draw at **1280**, **992** and **640** px.

- The lane grid is `col-12 col-md-6 col-lg` (`:211`) — six lanes in one row only above
  `992`, **three-up then two-up** between 768 and 992, stacked at 640. At 1280 a lane is
  roughly **193 px** against the customs board's 235. This is the case prompt 11 was
  told to size for; this is where it is checked.
- `min-height: 220px` per lane body means an empty board is **six** 1 100 px columns of
  nothing at 640 — and four of them are empty on real data.
- The lane title truncates at `110 px` (`:216`), the deal label at `140 px` (`:237`),
  both with the full text in a `:title` — unreachable on a phone.
- The table view is **eight columns** with **no `table-responsive` wrapper**. Nothing
  may scroll the page horizontally.
- `SkeletonRows :cols="6"` (`:195`) stands in front of both views — matching the lane
  count by coincidence and the table's eight columns not at all.

## 10 · Deliverables

**Do not restate prompt 11's deliverables.** These are the ones this screen adds.

1. **S1's severity vocabulary** — four distinguishable outcomes (on time · will miss
   the deadline · ETA already passed · cannot be determined), three codes each, with a
   stated source for every one of them and no new backend field.
2. **The cross-board ruling**: one urgency vocabulary or two, and how a person reading
   both boards knows which question they are looking at.
3. **The six-lane grid at 1280 and 992**, with the lane header resolved at ~193 px.
4. **Three kinds of empty lane** — nothing here · filtered to nothing · cannot be
   reached on this data — drawn distinctly.
5. **S3's metrics panel**: the label corrected to what it sums, and zero · absent ·
   unclassified as three drawings, in a panel whose height does not tell you how much
   data it has.
6. **The missing-document list on the card** — the names, not the count — reusing 11's
   answer and showing it under this board's single-item case rather than eleven.
7. **The freight booking's status out of its `:title`** — it names the lane, and the
   lane is the board's primary axis.
8. **A part-received shipment drawn**, or a stated reason the design cannot, given that
   the server sends a boolean.
9. **The failed-first-load state**, which here is a two-sentence empty state that
   argues the wrong case.
10. **A ruling on the loose paragraph** beside the empty state — inside the component's
   contract or outside it. Prompt 11 raised it; two instantiations now depend on it.
11. **The forbidden state at page level**, which the file has no drawing for.
12. **The eight-column table at 640**, wrapped, with a stated answer for what it drops.
13. Every question your design raised, listed — including the two this prompt refuses
    to settle: what creates a Freight Booking, and whether `due` should exist at all.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: the working pattern reads the `.vue` as text, pulls the decision
expressions out and runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Prompt 11's **K1–K3** (background refresh, failed-tick toast, staleness) and **K18–K20**
(region state, one shared component, the read-only regression guards) apply to this
screen unchanged and are not restated. **K15 does not apply** — this file has no day
arithmetic. Everything below was measured from `LogistBoard.vue`,
`DeclarantQueue.vue`, `stabler/api/tender.py` and `seed_tender_demo.py` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| L1 | **An ETA that has already passed is visible.** `late` compares ETA to deadline, never to today; a six-day-overdue PO renders as on time | 0 | asserted |
| L2 | **Urgency distinguishes *cannot be determined* from *on time*.** A missing ETA or deadline yields `"good"` | 1 rendering | 2 |
| L3 | **Urgency is not carried by colour alone.** One colour, on one field, at `:266` and `:321` | colour only | 3 codes |
| L4 | **No page-local colour map.** Three maps of six values; `delivered` · `accepted` · `booking` name a different token family in the badge than in the header | 3 / 0 | 0 / 1 |
| L5 | **The lane labels are defined once.** `LANE_CONFIGS[].label` and `stLabel()` are the same six strings | 2 | 1 |
| L6 | **The board's money column names what it sums.** *Transport* is transport **+ loading** | 1 | 0 |
| L7 | **Zero, absent and unclassified are three renderings.** `v-if="item.transport"` erases the row; the seed makes that every row | 1 | 3 |
| L8 | **An unreachable lane is distinguishable from an empty one.** Four of six lanes require a Freight Booking and nothing creates one | 0 | asserted |
| L9 | **The freight booking's status is rendered, not hovered.** `freight_booking_status` selects the lane and appears only in a `:title` (`:244`) | 1 | 0 |
| L10 | **The missing-document list is rendered, not just its count.** `missing_logistics_docs` is sent on every row and read nowhere | 0 | asserted |
| L11 | **A failed load is not the empty state** — and here the empty state carries a second sentence explaining the emptiness | 1 | 0 |
| L12 | **No fixed-width label.** `max-width: 110px` on the lane title, `140px` on the deal label, against real names that already exceed both | 2 | 0 |
| L13 | **The skeleton matches the view it precedes.** `:cols="6"` in front of a six-lane board and an eight-column table | 1 | per view |
| L14 | **Nothing is a click target without a role, a tabindex and a key handler.** A `<span>` styled as a link (`:234`) and a `<tr>` with `cursor: pointer` (`:315`) | 2 | 0 |
| L15 | **No `btn-xs`.** The layer defines no `xs` size | 4 | 0 |
| L16 | **The table view is inside `table-responsive`.** Eight columns, no wrapper | 0 | 1 |
| L17 | **The view mode survives a refresh and a shared link**, on a screen whose every filter already does | 0 | asserted |
| L18 | **The two boards share one component.** Identical import lists; 90 lines differ here and 75 there, out of 346 and 361 | 2 files | 1 + 2 |
| L19 | **Regression guards — already right, must stay so.** Zero `spinner-border` · three real `SkeletonRows` · `EmptyState` at three sites · both actions routing inside the SPA (`:149-157`) · lanes derived server-side and **not draggable** | asserted | unchanged |

**L18 is the one that decides whether this prompt succeeded.** The twins were ~77 %
identical when the package began, and the customs-board fix that shipped in the
meantime moved them *further apart* — 90 differing lines where there were 80. Every
divergence in this file that your design does not fold back into one component is a
third copy waiting to be written.

State plainly which of these your design satisfies, and name anything it cannot.
