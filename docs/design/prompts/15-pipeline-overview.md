# 15 · Pipeline overview, and the funnel drawn once

> `/tender/overview` · `stabler/public/js/pages/tender/TenderOverview.vue` (254 lines)
> **plus** `stabler/public/js/pages/tender/TenderFunnel.vue` (745 lines) — drawn
> here, and only here.
> Servers: `stabler.api.tender.tender_funnel` (`tender.py:2520`) +
> `stabler/api/_funnel.py` (195) · `tender_flow` (`tender.py:3556`) +
> `stabler/api/_tender_flow.py`
>
> **Nothing in this file is invented.** Every number was produced by executing
> `_funnel.summarise`, `_funnel.pipeline` and `_tender_flow.step_rows` against
> `stabler/maintenance/seed_tender_demo.py`.

---

## 0 · What this prompt owns

`TenderFunnel` has two hosts and the package decided it is drawn **once**, here,
where it is most of the screen. Prompt 14 owns the arrival, not the strip.

| | `TenderOverview` — **this prompt** | `DirectorBoard` — prompt 14 |
|---|---|---|
| props | `mode="full" pipeline-strip` | `pipeline-strip :selected="phase"` (mode defaults to `"full"`) |
| `@select` | `openPhase` → `router.push("/tender/portfolio?phase=…")` | `onPhaseSelect` → filters the table below |
| below it | a Process flow summary panel | a 13-row portfolio table |

`TenderOverview.vue:115-118` states the rule the whole package should inherit:
the strip appears in both places, but **it only selects where something under it
can be filtered.** Elsewhere it navigates to the screen that can.

**The `mode` prop is dead.** Both hosts resolve to `"full"` — one by default, one
explicitly — so `v-if="props.mode === 'full'"` (`TenderFunnel.vue:427`) guards a
branch that is always taken. 00-SETUP recorded this; it is confirmed here, and it
belongs to this prompt as a finding, not a refactor.

---

## Corrections this file owes the package

**The rule-under-the-number is not two implementations. It is three, and this is
the biggest.** Prompt 13 called it the desk's own idea; prompt 14 corrected that
to two. `TenderFunnel` carries the signature **fifteen times** on one component:
4 KPI counters (`ds-kpi-note` + `ds-kpi-q`), 11 stage boxes (`ds-stage-rule`),
plus a rule line inside each chevron popover and a source line under each panel.

And it makes the collision visible: **prompt 14's S1 is not a director-board
slip.** Two of the three false rule strings are *shared with this component* —
one of them correct here and false there, the other false in both. See S1.

---

## 1 · The product

Stabler is a tender operations SPA for a company bidding on Uzbek state railway
tenders and importing what it wins.

This screen exists because of a mistake worth reading (`TenderOverview.vue:3-8`):
`/dashboard` was for one day a **byte-identical copy of the operations desk** —
same component, same title, same numbers. Two screens showing the same thing make
both unnecessary. So the questions were split and written into the two page
titles:

- `/tender/desk` — **"What should I do today?"** (prompt 13)
- `/tender/overview` — **"Where the pipeline stands"** (this one)

Two blocks answer two different questions: `tender_funnel` says **how many and
where**; `tender_flow` says **how long it is taking**.

---

## 2 · The role gates — the module's best, and worth copying

Both blocks are gated **at the endpoint**, and the client mirrors the gate rather
than calling and catching a 403:

    canFunnel = views ∋ director | sourcing     (tender.py:2536)
    canFlow   = views ∋ director                (tender.py:3065)

The comment states the principle: *drawing a block, calling it, taking a 403 and
showing an empty panel is worse than not drawing it.*

And when a user has **neither**, the screen does not go blank. It renders a panel
titled **"Your work is on the operations desk"** with a link there, because — its
own words — *"Beyaz bir sayfa bir hata gibi okunuyor."* A white page reads like a
failure.

**This is the answer to prompt 14's P11**, already written, in this repository,
in this module. Prompt 14's board renders a permission refusal as *"No tenders
match these filters."* Prompt 15's screen renders it as a destination. Cite this;
do not reinvent it.

The funnel's own gate is `_require_any_tender_view(("director", "sourcing"))`,
and the comment says why it is not narrower: a director board returning 403 while
the funnel embedded inside it leaked the same numbers.

---

## 3 · Nine mandates — measured across both files

| # | Mandate | `TenderOverview` (254) | `TenderFunnel` (745) |
|---|---|---|---|
| 1 | House layer | **PASS** — 27 `ds-*`, 0 `badge bg-`, 0 bare `btn-` | **PASS** — 64 `ds-*`, same zeros |
| 2 | Every number carries its rule | **N/A** — no counters of its own | **PASS in form, FALSE in one case** (S1) |
| 3 | Loading is skeleton, not spinner | **FAIL** — the word *"Loading…"* | **FAIL** — a panel foot reading *"Loading tender funnel…"* |
| 4 | Five states per region | **PARTIAL** — flow panel has error + loading + content, **no empty** | **FAIL** — loading, content, and *nothing* (S3) |
| 5 | State in the URL | **N/A** — this screen has none to keep | **PASS by design** — `selected` is a **prop**, and the comment says why: a component holding its own selection would drop a link-sharer onto an unfiltered table |
| 6 | Keyboard / SR reachable | 0 `aria-*`, 1 `role="alert"` | 2 `aria-*`, `role="button" tabindex="0" @keydown.enter` on funnel rows — **the module's best row-as-control** |
| 7 | No raw identifiers | source names are carried **as data** with a stated reason (`PIPE_SOURCE`) — then contradicted 170 lines later (S6) | — |
| 8 | Refresh is not a button | **FAIL** — a `Refresh` button; no `useAutoRefresh` on either file | — |
| 9 | Freshness is the server's | **FAIL** — no timestamp at all here | — |

---

## 4 · Hard rules

- **No dark mode.**
- **Do not redraw the funnel elsewhere.** This is the one place.
- **Do not move the phase notes to the server.** `PIPE_NOTES` lives on the client
  deliberately (`TenderFunnel.vue:277-279`): they are *translatable commentary,
  not data*, and the endpoint returns only numbers. Respect the split.
- **Bar width and percentage answer different questions** and must stay
  distinguishable: width is relative to the **first** rung, the percentage is
  conversion from the **previous** one (`:238-240`).
- **`lost` reached `submitted`, not `won`.** `_funnel.rank` says it plainly:
  ranking lost like won would make the last rung larger than the number of wins,
  *"a lie with a chart on it."* Any redesign of the funnel keeps this.
- **`full` is always a subset of `n`.** `_funnel.pipeline` clamps it, because a
  bar reading 6/4 fills to 150% and lies quietly.
- Zero `formatMoney` in either file. **This screen shows no money.** Keep it that
  way; money is prompts 10 and 14.

---

## 5 · States

| Region | Has | Missing |
|---|---|---|
| Funnel — before data | one line of text in a panel foot | a skeleton |
| Funnel — after a failed load | **nothing renders at all** (S3) | error, forbidden |
| Chevron strip | content only | empty (`pipeTotal = 0`) |
| Stage boxes | content only | empty |
| Conversion funnel | content only | empty, and the all-zero case |
| Where we lose them | **has a real empty** — *"No stage lost a lot in this window."* | — |
| Process flow | error (`role="alert"`), loading, content | **empty**, and the case where `steps` is `[]` renders a grid of nothing above a foot that says *"No step is past its own threshold today"* — good news, printed over an absence |
| Neither role | **a designed destination** (§2) | — |

---

## 6 · The screen

`TenderPage :label="`Tender · Overview`" :title="t('Where the pipeline stands')"`.
`#meta` carries two sentences: *"Every number is read from an ERP record"* and
*"Today's queue lives on the operations desk — this is the whole pipeline."*
`#actions` carries `Refresh` (which refreshes **both** blocks via the funnel's
`defineExpose({ load })`) and a link to the desk.

Then, top to bottom: **chevron strip** → **4 KPI counters** → **11 stage boxes in
4 groups** → **conversion funnel + losses, side by side** → **process flow strip**.

---

### S1 — the same counter, twice, with the same rule and different numbers

`/tender/portfolio` renders **ten counters**: the director board's six, then this
component's four, because `DirectorBoard` does not pass `mode` and the default is
`"full"`.

Two pairs collide. Measured on seed data:

| | board (prompt 14) | funnel (this prompt) |
|---|---|---|
| label | **Active tenders** | **Open pipeline** |
| caption | *lots in the pipeline* | *lots in the pipeline* — **identical** |
| note | *seen through to awaiting result* | *seen through to awaiting result* — **identical** |
| rule | `tender_lot · result = null` | `stage ∉ (won, lost)` |
| **value** | **13** | **10** |

The board's printed rule describes what **the funnel** does. The funnel's number
is the one that matches both rules. Two counters, one page, three lines of
identical copy, and the wrong number is the one whose rule is wrong.

| | board | funnel |
|---|---|---|
| label | **Risk** | **Risk** |
| caption | *deadline risk* | *deadline risk* |
| note | *needs action today — lands on the desk* | *needs action today — lands on the desk* |
| rule | `deadline < 48h · act_now` | `deadline < 48h · act_now` — **the same string** |
| **value** | **2** | **1** |

Both call `_deal_deadlines(...)["risk"] == "risk"`, which is **`days < 0`** on any
milestone — not 48 hours, in either place. They differ because the funnel scopes
the computation to open non-`seen` stages (`tender.py:2610-2612`) while the board
counts every deal, won ones included. **The identical rule string is false twice
and describes neither behaviour.**

A third pair agrees today by accident: **Result / win rate** is `66.7%` on both,
but the funnel windows won/lost to the last `days` (default 90) while the board
counts all time. On a fresh seed every result is inside the window. On a real site
they diverge, silently, under the same label and the same rule string.

The funnel's own comment saw this coming (`:73-76`):

> Bu dört sayı PENCEREYE bağlı (son N gün). Direktör panosunun altı sayacı
> portföyün tamamını sayıyor — **aynı isimli olanlar bile aynı sayı DEĞİL.**

It knew, and it wrote a note under the number instead of preventing the
collision. **Prevent it.** Options to draw and choose between: scope stated in
each counter, one strip instead of two on the shared page, or a host that tells
the funnel not to draw counters (which is what `mode` was for, before it died).

### S2 — three names for the same five stages, on one page

`flowLabels.js` exists specifically so two screens cannot name a step
differently — its comment says giving one step two names *"iki sayının farklı
görünmesi ikisine de güveni bitirir."* It has one caller pair. Meanwhile this
page carries three vocabularies:

| stage | chevron strip (`PIPE_LABELS`) | stage box (`GROUPS`) | flow strip (`STEP_LABELS`) |
|---|---|---|---|
| `seen` | Intake | Under review | Intake — file opened |
| `go` | GO decision | GO — awaiting sourcing | GO / NO-GO decision |
| `sourcing` | Sourcing | Collecting quotations | Quotation gathering |
| `priced` | Pricing | Priced — ready to bid | Bid pricing |
| `submitted` | Bid submitted | Bid submitted | Bid submitted |

Three of the five differ in all three places, **within one scroll**. Decide
whether the difference carries meaning (the chevron is a phase, the box is a
state, the flow step is a queue) or is drift. If it carries meaning, the design
must show that it does. If it is drift, one vocabulary wins.

### S3 — the funnel's failure state is to not exist

    <div v-if="loading && !data">…</div>
    <template v-else-if="data"> …everything… </template>

`load()` catches into `toast.error` and leaves `data` at `null`
(`TenderFunnel.vue:47-60`). So a failed funnel request renders **no element at
all** — and on `/tender/portfolio` the phase strip and four counters simply are
not there, above a table that still lists thirteen rows.

Compare the sibling block on this very screen: `loadFlow()` writes `flowError`
into the panel *"because the board fires two requests on open and it must be
visible on screen which one fell over"* (`TenderOverview.vue:57-59`). **The right
answer is already on the page, ten lines away, in the other half.**

### S4 — the server refuses the optimistic lie; the client tells it anyway

`_tender_flow._state` distinguishes `empty` from `unknown` and explains why at
length: an empty step has no work waiting, an unmeasured step **has work and no
stamp**, and folding them together shows a possibly-blocked step as idle. Counting
`unknown` as *within* would be *"ekranın en dürüst olması gereken yerinde iyimser
bir yalan."*

`stateLabel` honours it — the chip reads **"Not measurable"**. Then:

    const stepTone = (row) => {
        if (row.state === "out") return "crit";
        if (row.state === "empty") return "mute";
        return null;
    };

`unknown` falls through to `null` — **the same tone as `in`**. On seed data the
`Bid submitted` step holds two lots with no stamp and renders with the exact
colour of a healthy step, beside a `—` where the number should be. The word is
honest and the pixels are not.

`edge` gets no tone either, though `waitState` colours the wait figure for both
`out` and `edge`. So a step at the edge is coloured on one of its two numbers.

### S5 — one lot, two stages, one screen

The funnel derives a stage from intake facts (`_funnel.classify`, precedence
`result > submitted > priced > sourcing > go > seen`). The flow reads the
**stored column** first: `stage = stored or _funnel.classify(...)`
(`tender.py:3582-3583`).

On seed data they disagree about **UTY-2026-4305**: its stored
`custom_tender_stage` is `go`, and `classify` puts it in `sourcing` because it has
one supplier quotation and no pricing. So this screen counts the same lot in
**GO decision** in the flow strip and in **Sourcing** in the chevron strip,
simultaneously — under a component whose first comment line promises *"Every deal
is counted in exactly one stage."*

It is counted in exactly one stage **per mechanism**, and there are two
mechanisms. Show it or reconcile it; do not let both numbers stand unexplained.

**Resolution (2026-09-02, F15):** reconciling the two mechanisms was
considered and rejected. `stage = stored or _funnel.classify(...)` is
deliberate, not an oversight —
`test_tender_flow_source.py::test_the_stored_stage_wins_over_the_derived_one`
pins it explicitly ("if the user moved the card by hand, the screen should
show that; derivation is only for deals that haven't been moved"), and
`move_deal_stage` (`tender.py:3034-3090`) shows the mechanism it protects: a
director's kanban drag writes `custom_tender_stage` **and**
`custom_tender_stage_entered_at` together, and the flow's own SLA wait-time
reads that timestamp. Forcing the flow to always re-derive would silently
discard both the manual placement and the moment it happened — a real feature,
not a bug standing in for one.

**"Show it" was chosen instead.** `TenderOverview.vue`'s process-flow panel now
carries a disclosure line beside the stage grid, naming the mechanism: the
flow strip keeps a manually set stage when one exists, the chevron above
always recomputes it, so a manually moved deal can legitimately read
differently in the two. F15 (§11) is corrected below from "fails" to reflect
this: the row's literal wording ("a lot appears in exactly one stage per
screen") is still false for a manually moved lot, **on purpose** — what F15
now measures is this section's own closing sentence, not the literal wording:
*"show it or reconcile it; do not let both numbers stand unexplained."*

### S6 — a popover nothing announces, and a principle contradicted 170 lines later

The chevron's second layer — the quote-set completeness bar, the phase note and
the rule — lives in `<span v-if="hovered === c.key" class="pipe-pop">`. It is
better than a `title` (it opens on `@focus` too), but it is not in the DOM until
then, so nothing announces it and it cannot be printed or linked to.

**Resolution (2026-09-02, F16):** a second, independent `.pipe-info` button was
added inside `.pipe-cell`, wired to a new `toggleDetails(row)` that only ever
writes `hovered` — never `pick()`, never `select`. Being a native `<button>`,
it is keyboard-reachable on its own (Tab + Enter/Space), and being a separate
tap target from the chevron button — whose own `@click="pick(c)"` already
selects and navigates in the same gesture — it gives a touchscreen a path in
that carries no navigation side effect. `aria-expanded` reports open/closed.
One piece is still short of "announces": the button carries no `aria-label`,
because the only text that would describe it is a *new* `t()` key, and
`test_tender_dashboard_i18n.py`'s completeness guard requires a new key to
already be translated in all five `translations/*.csv` before landing — out of
scope for this change. The glyph (ℹ) is its only accessible name until that
key is added.

And `PIPE_SOURCE` is carried as data with a careful comment — a source name is
not a translatable sentence, and bare text trips the guard that requires every
text node to pass through `t()`. Then `TenderFunnel.vue:478` writes
`tender_lot · quotation · sales_order · purchase_order` **as bare template text**
in the very next panel.

---

## 7 · Data — derived by execution, invent nothing

Stage classification (`_funnel.classify`) over the seed's 13 lots:

    seen 2 (4301, 4302) · go 1 (4306) · sourcing 3 (4305, 4308, 4309)
    priced 2 (4310, 4311) · submitted 2 (4312, 4313) · won 2 (4314, 4315) · lost 1 (4316)

**The four counters:** Open pipeline **10** · Result **66,7%** (2 won / 1 lost) ·
Execution **2** active contracts · Risk **1**.

`urgent` = 1, and it is **UTY-2026-4305** alone: its bid deadline was yesterday,
and it is the only open non-`seen` lot whose worst milestone is past due.

**The eleven stage boxes, in their four groups:**

| group | box | n | rule |
|---|---|---|---|
| **Decision** — 3 lots | Under review | 2 | `intake ✓ · go_no_go = ""` |
| | GO — awaiting sourcing | 1 | `go_no_go = go · SQ = 0` |
| **Sourcing — cost first** — 5 lots | Collecting quotations | 3 | `SQ > 0 · no pricing` · chip **"2 below policy"** |
| | Priced — ready to bid | 2 | `bid_pricing ✓` |
| **Bidding** — 5 lots | Bid submitted | 2 | `submitted_at ✓ · result = ?` · **no urgency chip** (`submitted_urgent` = 0) |
| | Won | 2 | `result = won` |
| | Lost | 1 | `result = lost` |
| **Contract & execution** — 2 lots | Contract (SO opened) | **0** | `stage = New` |
| | Procurement (PO) | 1 | `stage = Procurement` |
| | Delivery / service | 1 | `Delivery \| Acceptance \| Invoicing` |
| | Completed (paid) | **0** | `stage = Paid \| Closed` |

Only two Sales Orders exist and they are the only submitted documents the seed
creates (`seed_tender_demo.py:538`), so **two of the four execution boxes are
structurally zero**. Sixth consecutive screen with a region that cannot populate.

**The conversion funnel** (`reached[step]`, cumulative; `lost` ranks as
`submitted`):

| rung | n | bar width | conversion | drop |
|---|---|---|---|---|
| Lots seen | **13** | 100% | *start* | — |
| GO decision | **11** | 85% | 85% | −2 |
| Sourcing started | **10** | 77% | 91% | −1 |
| Bid submitted | **5** | 38% | 50% | **−5** |
| Won | **2** | 15% | 40% | −3 |

Foot: **66,7%** win rate · 3 resolved · 2 won.

**Where we lose them**, sorted by drop — the first has no tone, the rest `today`:

1. **−5 · Bid submitted · 50% conversion** — *"Priced but never submitted — the bid window closed on a finished price."*
2. **−3 · Won · 40%** — *"Submitted and lost — the bid was in, the result went the other way."*
3. **−2 · GO decision · 85%** — *"Seen but never decided — the GO/NO-GO queue is where they stalled."*
4. **−1 · Sourcing started · 91%** — *"Decided but sourcing never started — not one quotation was collected."*

**The chevron strip** — total **10 in the pipeline**; `full` is the count meeting
the 5-quote / 2-country rule:

| phase | n | full | bar |
|---|---|---|---|
| Intake | 2 | 0 | 0% |
| GO decision | 1 | 0 | 0% |
| Sourcing | 3 | 1 | 33% |
| Pricing | 2 | 2 | **100%** |
| Bid submitted | 2 | 1 | 50% |

**The process flow strip** (`_tender_flow.step_rows`, stored stage, SLA defaults
seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30):

| step | open | avg days | SLA | state |
|---|---|---|---|---|
| Intake — file opened | 2 | 2,0 | 3 | At the edge |
| GO / NO-GO decision | 2 | 4,5 | 5 | At the edge |
| Quotation gathering | 2 | 22,5 | 14 | **Over SLA** |
| Bid pricing | 2 | 7,0 | 3 | **Over SLA** ← **bottleneck** |
| Bid submitted | 2 | **—** | 30 | **Not measurable** |

`in_process` = 10, `unmeasured` = 2. The bottleneck is `priced` on **ratio, not
difference** — 7,0 / 3 = 2,33× beats sourcing's 22,5 / 14 = 1,61× — and
`_tender_flow.bottleneck` explains exactly that choice.

**States you cannot exercise from this data:** every `empty` step (all five hold
work), the funnel's all-zero case, *"No stage lost a lot in this window"*, and the
`submitted_urgent` chip. Label any of these you draw as constructed.

---

## 8 · Vocabulary

| Term | Means, exactly |
|---|---|
| **phase** | one of the five open stages the chevron walks: seen · go · sourcing · priced · submitted. `won`/`lost` are excluded on purpose — *they are results, not phases, and putting them on a left-to-right progress strip would render loss as progress* (`_funnel.py:30-33`) |
| **rung** | a funnel step, read as **"reached at least this stage"** — cumulative, not exclusive |
| **conversion** | this rung ÷ the previous rung |
| **width** | this rung ÷ the **first** rung |
| **drop** | previous rung − this rung. Only drops > 0 are listed; a zero is noise |
| **complete quote set** | ≥ `MIN_QUOTATIONS` (5) quotations from ≥ `MIN_COUNTRIES` (2) countries — both halves, always |
| **window** | `days`, default 90, max 366. Applies to won/lost and the funnel, **not** to open stage boxes: an open tender is open |
| **in · edge · out** | wait vs. that step's own SLA. `edge` is the last quarter, floored at one day |
| **empty vs. not measurable** | no work waiting vs. **work waiting with no stamp**. Never one word (S4) |
| **bottleneck** | the step exceeding its own SLA by the greatest **ratio** |

---

## 9 · Responsive

Measured: `TenderOverview` has one media query, `TenderFunnel` has two. The
chevron strip is a horizontal row of five buttons plus a total, with a popover
anchored to each. The stage grid uses `data-cols` 2 / 2 / 3 / 4 per group. The
funnel and losses sit in `funnel-2col`.

The phone case is unaddressed and is the hard one: a five-cell chevron with
hover-only content has no touch equivalent at all. Specify what a phone user sees
instead of the popover — that is a design decision, not a breakpoint.

---

## 10 · Deliverables

Artboards, 1440×900 unless stated.

1. **`/tender/overview`, populated** — every number in §7, in order: chevron,
   4 counters, 11 stage boxes, conversion funnel + losses, flow strip.
2. **The collision, drawn** (S1) — `/tender/portfolio` with all **ten** counters
   as it renders today, beside your fix. Show the two "Risk" values, 2 and 1.
3. **One vocabulary, or three with a reason** (S2) — the five stages named across
   the three surfaces.
4. **Funnel · the states it has none of** (S3) — failed load, forbidden, empty —
   using the flow panel's in-panel error as the model.
5. **`Not measurable`, coloured honestly** (S4), beside `empty`, `edge`, `in`,
   `out`, so the five are distinguishable at a glance.
6. **The two-stage lot** (S5) — 4305 in `GO decision` and `Sourcing` at once, and
   how the screen admits it.
7. **The chevron popover without hover** (S6) — the touch and keyboard answer.
8. **Skeletons** for both blocks, replacing *"Loading tender funnel…"*.
9. **"Your work is on the operations desk"** — the neither-role panel, redrawn as
   the reference forbidden state for the whole package (§2).
10. **Mobile, 390×844** — chevron, stage grid, funnel bars.
11. **An annotation board** carrying the S1 collision and the correction at the
    top of this file.

Keep the artboards you rejected.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| F1 | The five funnel rungs read 13 / 11 / 10 / 5 / 2 with conversions 85 / 91 / 50 / 40 | passes |
| F2 | `lost` counts toward `submitted` and not toward `won` | passes |
| F3 | The losses panel is sorted by drop, biggest first, zeros omitted | passes |
| F4 | `full` never exceeds `n` in the chevron | passes — clamped server-side |
| F5 | The chevron's number and the host's filtered row count come from one pass | passes — `rows` and `pipeline` share it |
| F6 | Clicking the selected phase again clears the selection | passes |
| F7 | A user with neither role gets a destination, not a blank page | passes |
| F8 | A user without the flow role never triggers the flow request | passes |
| F9 | Each funnel row is reachable and openable from the keyboard | passes — `role="button" tabindex="0" @keydown.enter` |
| F10 | No two counters on one page share a label, a caption and a rule while showing different numbers | **passes** — `TenderFunnel`'s `mode` default flipped `"full"` → `""`; a silent host (DirectorBoard) now gets the chevron only, TenderOverview keeps the full render by asking for `mode="full"` explicitly (fixed 2026-09-02; DirectorBoard's own six counters are prompt 14's row, not this one) |
| F11 | A counter's rule line describes what it counted | **passes for this screen's counter** — TenderFunnel's `urgent` rule now reads `any milestone · days < 0`, matching `_milestone()`'s actual `status = "risk"` condition; no 48h threshold exists anywhere in the computation (fixed 2026-09-02). DirectorBoard carries the same fact under different wording (`worst(bid,contract,po_eta,delivery).days < 0`, prompt 14) — a convergence pass across the two screens is still open |
| F12 | One stage has one name per screen | **passes** — the chevron (`pipeline` computed) and the stage boxes (`GROUPS` computed) both import `stepLabel` from `flowLabels.js` instead of keeping independent literals; the second copy, `PIPE_LABELS`, is deleted rather than left dead (fixed 2026-09-02) |
| F13 | A failed funnel load renders something | **passes** — a new `error` ref, cleared at the top of every `load()` attempt, is written in the catch branch instead of a toast; a new `v-else-if="error"` panel renders it with `role="alert"` (fixed 2026-09-02) |
| F14 | `Not measurable` is visually distinct from `Within` | **passes** — `stepTone` now returns `"mute"` for `unknown`, the same tone `empty` already gets and the same one the SLA badge already uses for this state; `edge` still gets no tone in `stepTone` (a separate, narrower gap this row does not name) (fixed 2026-09-02) |
| F15 | A lot appears in exactly one stage per screen | **passes, disclosed not reconciled** — 4305 (and any manually moved deal) can still legitimately appear in two; the flow panel now says why instead of leaving it unexplained (S5, corrected 2026-09-02) |
| F16 | The chevron's second layer is reachable without a pointer | **passes, one gap noted** — a second, independent `.pipe-info` button (native `<button>`, wired to its own `toggleDetails(row)`) opens and closes `.pipe-pop` without ever calling `pick()` or emitting `select`, so touch and keyboard both reach it on their own tap target; `aria-expanded` reports open/closed. No `aria-label`: `test_tender_dashboard_i18n.py`'s `test_every_dashboard_copy_key_has_a_nonempty_translation` requires a new `t()` key to already carry a non-empty entry in all five `translations/*.csv`, out of scope for this change — the visible glyph (ℹ) is the button's only accessible name until that key is added (fixed 2026-09-02) |
| F17 | Loading renders a skeleton | **fails** — a line of text, in both blocks |
| F18 | The screen says how fresh it is | **passes for the timestamp** (2026-09-02) — the older of the flow's and the funnel's `generated_at`. The manual `Refresh` button is untouched |
