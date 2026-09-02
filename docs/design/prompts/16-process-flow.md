# 16 · Process flow

> `/tender/flow` · `stabler/public/js/pages/tender/TenderFlow.vue` (228 lines)
> Server: `stabler.api.tender.tender_flow` (`tender.py:3539`) +
> `stabler/api/_tender_flow.py` (93) + `stabler/api/_tender_sla.py` (124)
> Shared labels: `stabler/public/js/pages/tender/flowLabels.js`
>
> **Nothing in this file is invented.** Every number was produced by executing
> `_tender_flow.step_rows` against `stabler/maintenance/seed_tender_demo.py`
> with the default thresholds, because the seed writes no `tender_stage_sla`
> row (measured: zero occurrences).

---

## Corrections this file owes itself — measured 2026-09-02 while closing W9–W17

Five claims below were made before the code was executed against them. None is
deleted; each says what it said, what is true, and how that was measured.

**1 · §5 and W11 said a genuinely empty pipeline renders "five column headers
over an empty `<tbody>`". It does not, and never did.**
`_tender_flow.step_rows` emits one row per `WORKING_STAGES` whatever the data
(`_tender_flow.py:37-52`), so a company with nothing waiting draws **five rows**
reading `0 · — · — · Empty`. Measured by calling `step_rows([], today)`. The
empty `<tbody>` belongs to the other three cases only — a failed load, an
unselected company, and never-loaded. The defect W11 names is real; its third
case was not. The empty pipeline needed a **sentence**, not a branch, and got
one: *"No deal is waiting in any step."*

**2 · S7 and deliverable 9 said `stage_sla`, "already on the wire", is how a
reader tells a tenant threshold from a default. It cannot be.**
`stage_sla_for` returns `dict(DEFAULT_STAGE_SLA_DAYS)` **verbatim** when a
company has no settings row (`stabler_settings.py:134-135`), so the payload is
byte-identical whether the tenant configured nothing or configured the default
numbers. Reading the key harder answers nothing. W16 was closed with a new
per-row `sla_source` computed in the pure module — and it is a claim about the
**value** (*matches the built-in default*), never about who typed it, because a
tenant who enters `14` for `sourcing` is genuinely indistinguishable from one
who enters nothing.

**3 · S4 said prompt 14's board "solved" the responsive problem with
`.board-scroll { overflow-x: auto }`. That rule, as written, does not engage.**
`.ds-table` is `width: 100%` (`stabler-modernist.css:389`) and its cells wrap,
so the table shrinks to whatever box it is given and the scrollbar never
appears. Measured on `DirectorBoard.vue` at this branch's fork point: the file's
only `min-width` is `200px` on `.board-phase-note` (`:320`), nothing on the
table. This screen's scroller therefore carries `min-width: 680px` on the table
inside it, and a test asserts no `min-width` escapes the scroller — a widened
element outside it moves the page instead, which is the same defect one level
up. **DirectorBoard is owed the same fix**; it is not this branch's to make.

**4 · S4 said the counter strip has "no phone rule either". The shared layer has
one.** `stabler-modernist.css:452-454` collapses `ds-kpis[data-cols="4"]` to two
columns at ≤992px. What S4 measured — zero `@media` in the component's own
`<style scoped>` — is true and is not the same statement.

**5 · S4 said `<style scoped>` "contains four rules". It contained ten.**
Counted 2026-09-02 on the pre-change file: `.flow-panel`, `.flow-state`, the
`data-bottleneck` stripe, `.flow-step`, `.flow-note`, `.flow-dash`,
`.flow-kpi-text`, `.flow-c-n`, `.flow-c-w`, `.flow-c-sla`. All ten were layout
or colour, which is the point S4 was making.

**6 · W15 said "three instances, not one", and named what was left. There were
four, and the fourth was in the diff that made the claim.** The unmeasured
counter read `{unmeasured} / {in_process} deals`, so a company with a single open
deal — the state every new tenant starts in — rendered **`1 / 1 deals`**. The
count in front of the noun is a ratio, not a quantity, and no plural rule can be
written for it; the caption is now the partitive *of the open deals*, which
agrees with nothing. Measured 2026-09-02 by calling `counters` with
`{in_process: 1, unmeasured: 1}`, now pinned in `tenderFlowCounters.spec.js`
("survives a company with exactly one open deal"). What W15's *Still not fixed*
list named — `10 open deals` and the three `{{ t("days") }}` sites
(`TenderFlow.vue:120,305,311,321`) — was accurate; the list's implication that
everything outside it had been cleared was not.

**And one claim that has now expired rather than been wrong.** S2 measured
`_tender_sla.severity` and `overdue_by` as "alive in tests and dead in
production". That was true when written. `_tender_flow.step_rows` now calls both
— on the worst measured deal in each step — so the sentence needs a date on it.

---

## 0 · What this prompt owns

Prompt 15 draws the **summary strip** of this data — five cells, a count, a wait
and a state chip, inside `/tender/overview`. This prompt draws the **full table**,
and the two must not disagree: they read the same endpoint and share
`flowLabels.js` precisely so one step cannot have two names across them
(`flowLabels.js:3-6`).

What this screen adds over the strip: a `Worst` column, a per-step `unmeasured`
count, the threshold in days beside each state, and four counters.

This is the smallest screen in the package (228 lines) and the **least
layer-native** of the six tender boards — 34 `ds-*` against `TenderCrm`'s 107.
That is not the same as *worst*: it has no Bootstrap in it at all. It is thin
because it does one thing.

---

## 1 · The product

Stabler is a tender operations SPA for a company bidding on Uzbek state railway
tenders. A lot moves seen → go → sourcing → priced → submitted → won/lost.

Three screens divide one dataset by question, and this screen's own comment
states the split (`TenderFlow.vue:3-8`):

| screen | question |
|---|---|
| Director board (14) | **how much** |
| Tender CRM | **which deal** |
| **Process flow (this one)** | **WHERE did we get stuck** |

And the constraint under all three, in its own words: *"İki ekranın farklı sayı
göstermesi ikisine de güveni bitirir."* Two screens showing different numbers
destroys trust in both. This screen shares its deal set with `crm_board`
deliberately; only the aggregation differs.

**The design principle this screen was built around, and which must survive any
redesign** (`TenderFlow.vue:10-15`):

> ÖLÇÜLEMEYEN AÇIKÇA YAZILIYOR. […] onları ortalamaya sıfır gün diye katmak
> tıkanmış bir adımı sağlıklı gösterirdi. […] bir ortalamanın neye dayandığını
> gizlemek, sayının kendisinden daha kötü.

Deals moved before the stage clock existed have no stamp. They are excluded from
the averages **and counted out loud** — per step in the table, and again as a
counter. Hiding what an average rests on is worse than the average.

---

## 2 · The role, and the gate with nowhere to land

One line: `_require_tender_view("director", company)` (`tender.py:3553`), with
the reason written beside it — the board shows the company's whole pipeline and
its SLA table, it is only in the director's menu, so the gate is there too.

~~`load()` catches everything into `toast.error` and returns
(`TenderFlow.vue:38-40`). There is no error state, no forbidden state~~ — closed
2026-09-02 by W11/W12: a 403 becomes its own branch naming the director view,
anything else is written into the panel with `role="alert"`, and the toast is
gone (it scrolled away over a table that kept claiming a pipeline). `load()`
still returns early when `activeCompany` is falsy, which is now a branch of its
own rather than an empty table. See S3 for what it used to render.

---

## 3 · Nine mandates — measured

| # | Mandate | Measured |
|---|---|---|
| 1 | House layer, not Bootstrap | **PASS** — 34 `ds-*`, 0 `badge bg-`, 0 bare `btn-`, 0 `spinner-border`, 0 `table-responsive` |
| 2 | Every number carries its rule | ~~**ABSENT** — four counters, `ds-kpi-note` only, **no `ds-kpi-q` anywhere** (S1)~~ → **PASS** (W9, 2026-09-02): all four carry one |
| 3 | Loading is skeleton, not spinner | **PASS** — `<SkeletonRows :rows="5">` |
| 4 | Five states per region | ~~**FAIL** — two (S3)~~ → **PASS** for the table (W11/W12): loading · forbidden · no-company · error · table, plus a sentence for the empty pipeline. The counter strip is now two — drawn, or withheld |
| 5 | State lives in the URL | **N/A** — the screen has no filters, sorts or selections |
| 6 | Keyboard and screen reader reachable | ~~**FAIL** — **zero** `aria-*`, **zero** `role=`; the only interactive element is the Refresh button~~ → **PARTIAL** (W17): the scroller is `tabindex="0" role="region"` with a name, the panel reports `aria-busy`, both failure states carry `role="alert"`. **Rendered behaviour is unverified** — see W17 below |
| 7 | No raw identifiers in front of a human | **PASS** — the panel foot's `crm_deal · custom_tender_stage_entered_at` is a deliberate source line, consistent with 14 and 15 |
| 8 | Refresh is not a button | **FAIL** — a `Refresh` button and no `useAutoRefresh` |
| 9 | Freshness is the server's | **FAIL** — no timestamp at all |

---

## 4 · Hard rules

- **No dark mode.**
- **Never fold `unknown` into a number.** `days_in_stage` returns `None`, not 0,
  and the comment says why: *"'bilmiyoruz' ile 'sıfır gündür' aynı şey değil"* —
  zeroing an unstamped deal would invent a brand-new pipeline. Anything you draw
  keeps `—` distinct from `0`.
- **Never fold `empty` into `unknown`.** An empty step has no work; an unmeasured
  step has work and no clock. Five states, not three (`_tender_flow._state`).
- **Terminal stages have no threshold, on purpose.** `won` and `lost` are absent
  from `DEFAULT_STAGE_SLA_DAYS` rather than set to 0, because 0 would mean *zero
  patience* and mark every won deal late. A step with no threshold can never be
  late. Do not add a row for them.
- **A threshold of 0 means "stop tracking this step", not "revert to default"**
  (`stabler_settings.py:110-117`). An administrator who clears the field means to
  switch a step off; falling back would silently undo that.
- **Per-step thresholds, never one global.** `sourcing` takes weeks by nature and
  `priced` takes days; one number would paint the first permanently red and the
  second never (`_tender_sla.py:8-13`).
- This screen shows **no money**. Zero `formatMoney`. Keep it.

---

## 5 · Two states, where five belong

| Region | Has | Missing |
|---|---|---|
| Counter strip | **1** — always renders, zeros while loading | loading, empty, error, forbidden |
| Step table | **2** — `SkeletonRows`, then the table | error, forbidden, no-company, ~~**empty**~~ (correction 1: an empty pipeline was never one of these) |

**Closed 2026-09-02.** The strip is withheld rather than zeroed whenever there is
no payload; the table has loading · forbidden · no-company · error · table, in
that order, and an empty pipeline keeps its five rows and adds a sentence.

The empty case is the worst rendering in the package so far: `v-else` on the
table means a failed load, an unselected company, or a genuinely empty pipeline
all render **five column headers over an empty `<tbody>`** — no sentence, no
explanation, not even prompt 14's misleading *"No tenders match these filters."*
Above it, four counters read `0 · 0 steps · none today · 0`, which is exactly
what a **healthy** pipeline looks like.

**A failed load on this screen is indistinguishable from a company with nothing
stuck.**

---

## 6 · The screen

`TenderPage :label="Tender · Process view" :title="t('Tender process flow')"`.
`#meta` carries two sentences: *"Every number is read from an ERP record"* and
*"A step is late when its average wait passes the threshold set for that step"*.
`#actions` carries `Refresh`.

**Counter strip** — `ds-kpis data-cols="4"`:

| key | `data-sev` | label | value | caption | note |
|---|---|---|---|---|---|
| `in_process` | neutral | In process | `d.in_process` | open deals | across every working step |
| `stuck` | `crit` / `ok` | Over SLA | count of `state === "out"` | step / steps | average wait past the tenant's threshold |
| `bottleneck` | `today` / `ok` | Bottleneck | **a step label**, or *none today* | — | furthest past its own threshold, proportionally |
| `unmeasured` | `soon` / `ok` | Not measurable | `d.unmeasured` | deals | moved before the stage clock existed — left out of the averages |

**Step performance table** — `ds-table`, five columns:
Step · Open · Average wait · Worst · SLA.

The Step cell adds a second line when `row.unmeasured` — *"{n} without a stage
stamp — not averaged"*. The SLA cell stacks a `ds-sla` chip with the state and a
line reading *"threshold {n} days"*, or *"not tracked"* when `sla_days` is null.
Panel foot: *"Thresholds come from Stabler Settings, per company"* and, in mono,
`crm_deal · custom_tender_stage_entered_at`.

---

### S1 — the one screen about thresholds is the one that dropped the rule line

Prompts 13, 14 and 15 measured three carriers of the module's signature — *every
number carries its own query*. This is the fourth screen with a `ds-kpis` strip
and it is the **only one with no `ds-kpi-q` at all**. Four counters, four human
notes, zero queries.

The absence is loudest on `Bottleneck`, whose value is *the answer to a
computation the reader cannot see*: `_tender_flow.bottleneck` picks the step
exceeding its threshold by the greatest **ratio**, not the greatest difference,
and the code explains why — *"30 günlük eşiği 3 gün aşan `submitted` ile 3 günlük
eşiği 3 gün aşan `priced` aynı değil, ikincisi iki katına çıkmış demektir."*

On seed data that choice **changes the answer**: `sourcing` is 8,5 days over and
`priced` is 4 days over, but `priced` is the bottleneck because 7,0 / 3 = 2,33×
beats 22,5 / 14 = 1,61×. A reader looking at the table will pick the wrong step
and has nothing on screen to correct them.

**Draw the rule lines.** `ratio to threshold, worst` under Bottleneck is not
decoration here; it is the difference between the counter being right and the
counter being believed for the wrong reason.

### S2 — the `Worst` column has no verdict, and the verdict already exists unused

Four of five columns carry a state. `Open` is a plain count; `Average wait` gets
`ds-wait[data-state]`; `SLA` gets the `ds-sla` chip. **`Worst` is a bare number.**

And the function that would judge it is written, documented and **called by
nothing in the application**:

    _tender_sla.severity(stage, entered_at, today, overrides) -> crit|today|soon|info
    _tender_sla.overdue_by(stage, entered_at, today, overrides) -> int

Measured: the only references to either outside their own module are in
`stabler/tests/test_tender_sla.py`. `_tender_flow` imports the module and uses
`days_in_stage` and `sla_for`; the other two public functions are alive in tests
and dead in production.

**True on 2026-09-02 when written; no longer true the same day.** W10 closed by
calling both from `_tender_flow.step_rows`, on the WORST measured deal in each
step — so the column's verdict and the module's own rule are one implementation.

On seed data the column is not idle decoration — every one of its four numbers
would carry a verdict:

| step | worst | threshold | `severity` would say | `overdue_by` |
|---|---|---|---|---|
| Intake — file opened | 3 | 3 | **today** — at the limit | 0 |
| GO / NO-GO decision | 5 | 5 | **today** — at the limit | 0 |
| Quotation gathering | 26 | 14 | **crit** | **12** |
| Bid pricing | 8 | 3 | **crit** | **5** |

Two steps whose *average* reads *At the edge* contain a deal sitting exactly on
its threshold, and the screen says nothing. A step's average being fine is not
the same as no deal in it being late — and this screen exists to find late work.

Decide what `Worst` is for. Either it earns a state, or it earns a link to the
deal it describes, or it goes.

### S3 — headers over nothing

See §5. Draw the four states this table does not have, and note the ordering
trap: `v-if="loading"` / `v-else` means the table is the fallback for
*everything*, so any new state must come before it, not after.

The reference implementations are both in this repository: `OperationsDesk`
renders five distinct branches in one panel (prompt 13 §5), and `TenderOverview`
writes its failure **into the panel** because two requests fire on open and the
reader must see which one fell over (prompt 15 §2).

### S4 — five columns and not one line of responsive CSS

Measured: **zero** `@media`, **zero** `overflow-x`, zero `table-responsive`.
~~`<style scoped>` contains four rules, all layout.~~ **Ten rules** — recounted
2026-09-02, see correction 5. All ten are layout or colour, which is the claim
this sentence was making.

Prompt 14's board has the same problem and ~~solved it~~ **wrote a container
that does not engage** (correction 3: no `min-width` anywhere, and `.ds-table`
is `width: 100%` with wrapping cells) — `.board-scroll {
overflow-x: auto }`, with the comment *"Dokuz sütunlu tablo dar ekrana sığmıyor;
sayfayı değil TABLOYU kaydır."* Scroll the table, not the page. **This screen
scrolls the page.** Five columns is fewer than nine, which is why nobody noticed.

~~The counter strip is `data-cols="4"` with no phone rule either~~ — **the
shared layer has one** (correction 4: two columns at ≤992px,
`stabler-modernist.css:452-454`); what is absent is a rule in this component.
And one of the four holds a text value, not a number (below) — which W14 removed
along with `flow-kpi-text`, by putting the ratio in the counter and the name on
the row.

### S5 — the bottleneck is a three-pixel shadow

The bottleneck row is marked `:data-bottleneck` on the `<tr>` and painted by:

    .ds-table tr[data-bottleneck="1"] td:first-child {
        box-shadow: inset 3px 0 0 var(--ds-crit);
    }

The comment defends the restraint — colouring the whole row would make the
numbers harder to read — and it is right about that. But the row itself never
says the word. The only place the bottleneck is *named* is a counter above the
table, whose value is a **step label rendered inside `ds-kpi-val`** with an
override class (`flow-kpi-text`) because a name is not a number.

So the screen states its single most important finding twice, in two shapes,
and connects them nowhere: a word in a counter, a stripe on a row, and the
reader joining them. Meanwhile `data-bottleneck` sits on the `<tr>` while the
paint is on `td:first-child` — a hook one level away from what it styles.

### S6 — manual pluralisation, in a stack that ships Russian

    cap: stuck === 1 ? t("step") : t("steps")

The i18n layer has interpolation and **no plural support** — this is the module's
workaround for that. It is correct for English and wrong for Russian and Uzbek,
which need a third form for 2–4 versus 5+. With five working steps the counter
can read `2`, `3`, `4` or `5`, so the wrong form is reachable, not theoretical.

`ru.csv`, `uz.csv`, `uzc.csv` and `tr.csv` all ship. Design the counter so it does
not need a plural — *"Over SLA · 2 of 5 steps"* has no plural problem and says
more.

### S7 — the payload carries the thresholds and the screen drops them

`tender_flow` returns `"stage_sla": overrides` (`tender.py:3612`). Measured:
**zero consumers in the SPA.** The second unread payload key found in this
module, after `generated_at` (prompt 13, correction 2).

**Still zero, and correctly so — see correction 2.** Reading `stage_sla` cannot
answer this section's own question: it is the defaults dict verbatim for a
company with no settings row. W16 closed with a per-row `sla_source` instead.
The key remains genuinely unread.

Each row does show its own `threshold {n} days`, so nothing is *wrong* — but the
panel foot promises *"Thresholds come from Stabler Settings, per company"* and
nothing on screen distinguishes a tenant's override from the built-in default
(seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30). A director reading
`threshold 14 days` cannot tell whether their company chose it.

The same key is the only way to explain the `not tracked` state honestly: a
threshold of 0 means an administrator **switched that step off**, and the screen
currently renders that identically to a step that was never configured.

---

## 7 · Data — derived by execution, invent nothing

`step_rows` buckets by the **stored** `custom_tender_stage`, and only over
`WORKING_STAGES = (seen, go, sourcing, priced, submitted)` — the seed's two won
lots and one lost lot are dropped before any arithmetic. Ten deals, five steps,
two each. No `tender_stage_sla` row exists, so every threshold is the default.

`days_in_stage` = today − `custom_tender_stage_entered_at`, which the seed writes
as `today − moved_days` and **deliberately omits for the two `submitted` lots**
(`seed_tender_demo.py:690`) so the *not measurable* row exists in demo data
the way it will on a real site.

**The table, exactly:**

| Step | Open | Average wait | Worst | SLA | threshold |
|---|---|---|---|---|---|
| Intake — file opened | 2 | **2,0** days | 3 days | At the edge | 3 days |
| GO / NO-GO decision | 2 | **4,5** days | 5 days | At the edge | 5 days |
| Quotation gathering | 2 | **22,5** days | 26 days | **Over SLA** | 14 days |
| Bid pricing | 2 | **7,0** days | 8 days | **Over SLA** ← bottleneck | 3 days |
| Bid submitted | 2 | **—** | — | **Not measurable** | 30 days |

The `Bid submitted` row also renders its second line: *"2 without a stage stamp
— not averaged"*. No other row does.

**The four counters:** In process **10** · Over SLA **2 steps** · Bottleneck
**Bid pricing** · Not measurable **2 deals**.

**Why the edges are edges.** `_state` calls it `edge` at
`average >= limit - max(1, limit // 4)`, floored at one day so a short threshold
still warns: `seen` warns from 2 days of a 3-day limit, `go` from 4 of 5. Both
seeded steps land exactly on that boundary — 2,0 and 4,5 — which is what makes
them the two rows a design must render legibly, not the red ones.

**States you cannot exercise from this data, on any of the five rows:**

1. `empty` — every step holds two deals.
2. `in` (*Within*) — the seed puts two steps at the edge and two over.
3. `not tracked` — no `tender_stage_sla` row exists, so `sla_days` is never null.
4. A bottleneck of `none today` — `priced` always qualifies.

Label any of these you draw as constructed. **Seventh consecutive screen with a
state the demo data cannot reach.**

---

## 8 · Vocabulary

| Term | Means, exactly |
|---|---|
| **step** | one of the five working stages. This screen and prompt 15's strip share `flowLabels.js`; the funnel on that same page calls them **phases** and its stage boxes give them a third set of names — prompt 15 §S2 |
| **open** | deals sitting in that step now, stamped or not |
| **average wait** | mean of the **measured** waits only, one decimal |
| **worst** | the longest measured wait in that step — the only number on screen with no verdict (S2) |
| **not averaged** | this deal has no stage stamp, so it is counted in `open` and excluded from the average |
| **within · at the edge · over SLA** | average vs. that step's own threshold; the edge is the last quarter, floored at one day |
| **empty vs. not measurable** | no work waiting vs. work waiting with no clock. Never one word |
| **not tracked** | threshold 0 — an administrator switched this step off. Not the same as unconfigured (S7) |
| **bottleneck** | the step over its threshold by the greatest **ratio**. Ratio, never difference (S1) |

---

## 9 · Responsive

There is none (S4). Specify:

- the five-column table on a phone — scrolling **the table**, following
  `.board-scroll`
- the four-counter strip, one of which holds a step name rather than a number
- the second line inside the Step and SLA cells, which is where the row's height
  comes from

---

## 10 · Deliverables

Artboards, 1440×900 unless stated.

1. **The table, populated** — the five rows of §7 exactly, both edge states, both
   over-SLA states, the `—` row with its "2 without a stage stamp" line, and the
   bottleneck marked.
2. **Rule lines for four counters** (S1) — especially `Bottleneck`, whose rule is
   *ratio, not difference*, and which picks a different step than a reader would.
3. **`Worst` with a verdict** (S2) — using `severity` / `overdue_by`, which exist.
   Two of the four seeded values sit exactly on their threshold; show that.
4. **Table · four missing states** (S3) — error, forbidden, no-company, empty —
   and note that each must precede the `v-else`.
5. **`Within` and `empty` and `not tracked`**, drawn as **constructed** rows,
   since seed data cannot reach them (§7).
6. **Mobile, 390×844** (S4) — table scroll, counter strip, two-line cells.
7. **The bottleneck, said once** (S5) — one place, named, not a stripe plus a
   word in a different region.
8. **A counter that needs no plural** (S6).
9. **Default vs. tenant override** (S7) — ~~using `stage_sla`, which is already on
   the wire~~ (correction 2: it cannot answer this), and the honest rendering of
   a step switched off. **"Switched off" is not sayable either** — `stage_sla_for`
   reads each field as `int(getattr(row, f"sla_{stage}_days", 0) or 0)`
   (`stabler_settings.py:137`), so an unmigrated child-table column fabricates
   the same 0 as a cleared field. Draw the CONSEQUENCE — a step with no
   threshold can never be late — not the decision.
10. **This screen beside prompt 15's strip** — same data, two densities, proving
    they cannot disagree.
11. **An annotation board** listing the two unread payload keys the package has
    now found (`generated_at`, `stage_sla`) and the two dead SLA functions.

Keep the artboards you rejected.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| W1 | The five rows read 2,0 / 4,5 / 22,5 / 7,0 / — with worsts 3 / 5 / 26 / 8 / — | passes |
| W2 | `won` and `lost` produce no row and can never be late | passes |
| W3 | An unstamped deal is counted in `open` and excluded from the average | passes |
| W4 | The per-step unmeasured count is rendered where the average is missing | passes |
| W5 | The bottleneck is chosen by ratio, not difference | passes — server-side |
| W6 | Threshold 0 renders as *not tracked*, not as a default | passes |
| W7 | Loading renders a skeleton | passes |
| W8 | This screen and the overview strip name every step identically | passes — shared `flowLabels.js` |
| W9 | Every counter states the rule that produced it | ~~**fails** — none do (S1)~~ → **passes** (2026-09-02) — four `ds-kpi-q` lines, untranslated, executed in `tenderFlowCounters.spec.js` |
| W10 | `Worst` carries a state, or says why it does not need one | ~~**fails** (S2)~~ → **passes** — `worst_state` / `worst_over` from `_tender_sla.severity` and `overdue_by`, silent where there is no threshold or no measurement |
| W11 | A failed load is distinguishable from an empty pipeline | ~~**fails** — headers over nothing (S3)~~ → **passes** — a failure replaces the table and withholds the strip; an empty pipeline keeps both and adds a sentence. See correction 1: the two were never the same rendering. **Disclosed cost:** the catch sets `data = null`, so a transient blip on Refresh discards a payload the director was reading and they must press it again. Kept deliberately — `Last read` is derived from `data.generated_at`, so a retained payload would print a pre-failure timestamp beside a panel saying nothing could be read, and the table is replaced by the error branch either way |
| W12 | A user without the director view sees a refusal | ~~**fails** — same branch~~ → **passes at the screen**. The 403 is turned into its own branch naming the director view. **The gate itself is untested here** — `_require_tender_view` needs a bench (`test_tender_view_gates`), and this branch could not run `make test-bench` |
| W13 | The table scrolls on a phone; the page does not | ~~**fails** — no responsive CSS at all (S4)~~ → **CSS in place, layout unverified** — `.flow-scroll` + `min-width: 680px` on the table inside it, asserted at source. No jsdom in this repository, so no test lays out a 390px viewport |
| W14 | The bottleneck is named in one place, in words | ~~**fails** — a stripe and a distant counter (S5)~~ → **passes** — the word is on the row; the counter carries the ratio the rule is made of. The stripe stays, in the same cell as the word |
| W15 | No user-facing string is pluralised by a ternary | ~~**fails** — `step` / `steps` (S6)~~ → **passes** — `2 / 5`, and the whole `? t(…) : t(…)` shape is banned file-wide (it caught the Refresh button too). **Four instances, not one — and this row twice miscounted them** (correction 6). The first pass shipped a third in the fix itself — `Worst`'s verdict read `{n} days over`, i.e. **"1 days over"** for any deal a single day past its threshold, which is the routine value of `overdue_by` when the state is `crit`. The second pass shipped a fourth: the unmeasured counter's `{u} / {n} deals` renders **`1 / 1 deals`** for a company with one open deal. Both found in review, corrected to `over by {n}` and to the partitive *of the open deals*: **nothing that has to agree with a number may follow it**, and a count that is one half of a ratio can never be pluralised at all. **Still not fixed:** `10 open deals` (`TenderFlow.vue:120`) and the three `{{ t("days") }}` sites (`:305,311,321`) hardcode an English plural for `n = 1`; they are the file's pre-existing convention and this row does not cover them. That list is what remains, not proof that nothing else was missed — it was accurate and still sat beside a live fourth instance |
| W16 | A reader can tell a tenant threshold from a default | ~~**fails** — `stage_sla` unread (S7)~~ → **passes, with a stated limit** — see correction 2. A tenant who types the default number is indistinguishable, and the wording never claims otherwise |
| W17 | Any interactive element is reachable by keyboard and announced | ~~**fails** — 0 `aria-*`, 0 `role=`~~ → **attributes in place, behaviour unverified** — `environment: "node"`, no jsdom, no `@vue/test-utils`: nothing here fires a key or reads a name aloud. The Refresh button was already a real `<button>` and always was reachable |
| W18 | The screen says how fresh it is | **passes for the timestamp** (2026-09-02) — `generated_at`. The manual `Refresh` button is untouched |
