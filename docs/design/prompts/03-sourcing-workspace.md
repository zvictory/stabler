# 03 · Sourcing workspace

**Source:** `stabler/public/js/pages/tender/SourcingWorkspace.vue` — 1039 lines,
**0 `ds-*`, 0 `tgm-*`**. Neither dialect. This screen is the third case: **plain
Bootstrap**, 20 `btn-*` sites, 13 hand-written badges, 2 `card-table`, 0
`table-responsive`.

**Why third:** the gate passed on 01 and 02 settled the language. This is the first
screen that has to be *translated into* it rather than reconciled with it — and it is
the largest surface in the module.

**What this prompt carries that the earlier two did not.** Screens 01 and 02 broke
rules by accident. This one breaks a rule **the repository documents twice and warns
about explicitly**, and it may be right to. See S2.

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

## 2 · The four roles

Gated server-side. The gate sits **at the endpoint, not in the navigation** — hiding
a menu item was already tried, and a user who knew the URL still got a 200.

| view | roles |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · Stabler Tender Director |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · Sales User · Stabler Tender Sourcing |
| `declarant` | System Manager · Stabler Admin · Sales Manager · Stabler Declarant · Stabler Tender Declarant |
| `logist` | System Manager · Stabler Admin · Sales Manager · Stabler Logist · Stabler Tender Logistics |

**This screen is the only one in the module that two views share unevenly**:
`sourcing` may edit and save the award decision; **only `director` may approve it**.
Both see the same screen. Design for that, it is not an edge case — see §6.

## 3 · Nine mandates — not negotiable

1. **No links into Frappe Desk** — no `/app/...`, no `window.open`.
2. Tables are striped by default; never hand-add `table-striped`.
3. Money renders **only** through `MoneyInput`; decimal count **only** from
   `moneyFractionDigits(currency)`.
4. Dates render **only** through `DateInput` + `formatDate()`; visible format
   `dd.mm.yyyy`.
5. **One** primary button per visual region. A second colour is not a second primary.
6. Amounts stay in **their own transaction currency**. No base or USD conversion.
7. Status badges come **only** from the shared status map. No page-local colour map.
8. List screens use the shared `ListToolbar` with auto-apply — no Apply/Refresh
   button; the search placeholder ends with `⌘K`.
9. Loading is a skeleton, never a bare spinner.

**Mandate 6 is the subject of this screen. Read S2 before you draw anything.**

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** Colour alone
  carries no information.
- **Text colour and fill/border colour are different tokens.** The bright orange
  "today" token measures 2.3:1 on white; there is a separate dark text token at 7:1.
- **The procurement policy numbers are server values.** They must **never** appear as
  literal digits in the design. **This screen already does it right** — it interpolates
  `{min}` and `{countries}` from `tenderPolicy` in two places. Keep that.
- **No fixed-width label, badge or nav item.** Measured worst-case interface-language
  growth is **3.75×** (`RFQs`, 4 characters → Uzbek `Narx so'rovlari`, 15).
- **String interpolation exists; plurals do not.** You cannot write "1 quotation /
  5 quotations". **This screen breaks that**, see §6.
- **A disabled control carries its reason beside it.** This screen's primary has
  **four** mutually exclusive reasons to be disabled and shows **none** of them.
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
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
**No CSS may bind to that attribute.**

**Measured on this file: `role="alert"` = 0. `aria-` = 0. In 1039 lines.** Four
`alert alert-warning`/`alert-danger` blocks exist and not one of them is announced.

## 6 · The screen

**Sourcing workspace.** Its one job: gather supplier quotations against a lot,
compare them, and record — with reasons — which one wins.

Three regions, top to bottom (the file's own docstring, `:2-8`):

1. **RFQ strip** — the RFQs raised for the deal, with an "Ask for quotation" action.
2. **Quotation comparison table** — nine columns, the heart of the screen. Drafts can
   be edited (a drawer) and submitted.
3. **Award panel** — where the winner is chosen, reasons are written, and directors
   approve. `sourcing` edits and saves; **`director` approves**.

Plus an **unassigned quotations** table (seven columns) for quotations that exist but
are not yet attached to this deal.

### S2 — the question this screen exists to answer

**How do you compare five bids from three countries without converting them?**

The comparison table has nine columns. Two of them are conversions:

| column | currency |
|---|---|
| Total | the quotation's own |
| **Sticker price ({base})** | **converted** |
| Landed estimate | the quotation's own |
| **Delivered total ({base})** | **converted** |

Mandate 6 says: *"Amounts must render in their original transaction/account currency
only. Do not convert totals or display base-currency/USD equivalent sub-lines."*

The repository documents **exactly two** exceptions to that rule, and describes both
the same way: **one `≈` line**, from a live rate, **never replacing** the
transaction-currency total, and — verbatim — *"Do not copy this pattern to other
screens without the same justification."* One is the Sales Order footer; one is the
Journal Entry residual. It also says, of the pattern this screen uses:
*"The per-row `→ base` hints it replaced are not covered by either exception and must
not come back."*

This screen has **9 base-currency sites**: two column headers, five per-row values,
and two inside the award panel — including the banner that says *"selected bid is
+X over the cheapest"*, which is arithmetic across currencies and cannot be done
without conversion.

**So one of two things is true, and you must say which:**

- **(a) The screen is wrong.** Comparison happens in each bid's own currency and the
  base columns come out. Then draw how a user picks between a bid in CNY and a bid in
  RUB without the product doing the arithmetic for them.
- **(b) The rule needs a third documented exception,** written to the same standard as
  the other two: what it is, why this screen and no other, what it may never do, and
  what makes it disappear. Draft that paragraph. It is the deliverable, not a footnote.

Draw **both**. Recommend one. **"It depends" is not an answer, and neither is
silence** — this rule has been broken by nine sites for long enough that nobody
notices any more, which is exactly why it is being asked now.

**One measurement you must not skip:** in the only data that exists, **every
quotation is in the same currency**. The seed sets no per-quotation currency, so the
two base columns render the same numbers as the two transaction columns in every
demo row. **The screen's most contested feature is invisible in the only data anyone
ever looks at.** Design for what happens when it is not.

### A second decision that is yours — the row's action cell

The comparison table's action cell carries **four buttons in four different colours**
(`btn-ghost-secondary`, `btn-ghost-primary`, `btn-outline-success`, `btn-ghost-danger`
— `:630`, `:639`, `:646`, `:653`), per row, in the ninth column of a nine-column
table. Mandate 5 allows one primary per region. Decide whether a table row is a
region, say why, and draw the answer.

### An architectural problem you must show, not solve

The award panel's footer holds a **blue** `Save draft decision` and a **green**
`Approve decision` side by side (`:972`, `:987`). Mandate 5's second sentence exists
for exactly this: *a second colour is not a second primary*. But they are also **two
different people's actions** — `sourcing` saves, `director` approves — and only one of
them is ever enabled for a given user. Draw it; the underlying question of whether one
screen should carry both people's actions is not yours to close.

### Three accessibility findings — surface them, do not smother them

1. **Zero `aria-` attributes and zero `role="alert"` in 1039 lines.** Four alert
   blocks announce nothing.
2. **The primary is disabled for four different reasons and names none of them**
   (`isAwardSaveDisabled`, `:351-358`): saving in progress · no supplier selected ·
   no selection reason · policy exception required but unchecked or unjustified. The
   user sees one grey button and no cause. **Draw which reason is showing.**
3. **The forbidden state does not exist — the screen just disappears.** The award
   panel is `v-if="canSourcingView"` (`:750`) and the unassigned table is
   `v-if="canSourcingView && …"` (`:678`). A user without the view sees no panel and
   no explanation. Hiding, not refusing.

## 7 · Data — use these rows, invent nothing

Two lots, chosen because they are the two halves of the policy question. Every number
below is generated by `stabler/maintenance/seed_tender_demo.py` and reproduced here.

**Quotation amounts are `round(value × (0.92 + i × 0.03))`** (`:376`) — the seed's own
comment says a single-priced set would not test a comparison screen. **Suppliers are
dealt round-robin across countries** (`:227`), so quotation count and country count
break independently.

### Lot A · `UTY-2026-4308` — the policy is satisfied

Signal va aloqa boshqarmasi · value **920 000 000** · **19 days** at the sourcing
stage against a limit of **14** · bid deadline **today** · 5 quotations, 3 countries.

| # | supplier | country | total | note |
|---|---|---|---|---|
| 1 | Temiryo'l ta'minot | Uzbekistan | 846 400 000 | **cheapest** |
| 2 | Hebei Rail Parts | China | 874 000 000 | |
| 3 | UralVagonSnab | Russian Federation | 901 600 000 | |
| 4 | Sanoat kompleks | Uzbekistan | 929 200 000 | |
| 5 | Shandong Heavy | China | 956 800 000 | |

Valid till: **deadline + 30 days**. Transaction date: **7 days ago**.
**Landed charges: none.** No purchase order exists for this lot, so "Landed estimate"
and "Delivered total" have nothing behind them — draw what that column shows.

### Lot B · `UTY-2026-4309` — the policy is **not** satisfied

Qurilish materiallari kombinati · value **410 000 000** · **26 days** at stage against
a limit of 14 · bid deadline **in 25 days** · 3 quotations, **1 country**.

| # | supplier | country | total |
|---|---|---|---|
| 1 | Temiryo'l ta'minot | Uzbekistan | 377 200 000 |
| 2 | Sanoat kompleks | Uzbekistan | 389 500 000 |
| 3 | Toshkent metall | Uzbekistan | 401 800 000 |

**This lot forces the policy-exception path open**: 3 quotations against a minimum of
5, 1 country against a minimum of 2. Both required textareas appear, and the primary
stays disabled until both are filled. **This is the lot to draw the award panel with.**

All three of B's quotations carry **the same transaction date — today** — because the
seed clamps it (`min(deadline − 7, today)`, `:357`) and this lot's deadline is in the
future. A "Date" column that is identical in every row is a column doing no work.

### Four things in this data the design must not smooth over

1. **The cheapest bid is not necessarily the winner**, and the screen already knows —
   it draws a warning when the selected bid is dearer, quantified. That warning is
   the most valuable thing on the screen and it is currently a Bootstrap alert with
   no role.
2. **Country count comes from `Supplier.country`, not from the supplier's name**
   (`seed_tender_demo.py:191-192`). If that field is empty the count reads 0 with
   five quotations sitting on screen. Draw the state where the count and the visible
   rows disagree.
3. **`{{ rfqs.length }} {{ t("RFQs") }}`** (`:467-469`) — a count and a noun
   concatenated. With one RFQ it reads "1 RFQs". This is the string the whole product
   uses as its i18n worst case (**3.75×** growth). Fix it without inventing plurals.
4. **Nothing on this screen is paginated.** Two tables, no pager, no limit.

**Currency:** the source data names none. Amounts arrive with the record and the site
default. **Do not hard-code a symbol.**

## 8 · Vocabulary

**Tables** — `ds-table`, and a `table-responsive` wrapper is **mandatory**. Numeric
cells are `ds-td-num`. Row emphasis is `tr[data-sev]` plus a `ds-chip[data-tone]` in
the row. Striped is the default: the migrating class is `ds-table table`, and
`card-table` goes.

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it.
Its own root is a `<tbody>`, so putting it inside one renders `<tbody><tbody>`.
**Measured: this screen does exactly that, twice** (`:576`, `:714`). Two correct
shapes: `<SkeletonRows v-if="loading" />` as a sibling of `<tbody v-else>`, both
direct children of `<table>`; or a whole-block `v-if`/`v-else` swap.

**Sections** — `ds-form-section`, **adjacent stack**: sections sit flush inside one
bordered card, divided by their own heads, no nested card frames. Settled on screen 01.

**Drawer** — `ds-drawer[data-size="lg"]` (760 px) for anything carrying a line table;
**542 px is the default for everything else**. Settled on screen 02. Parts:
`-backdrop`, `-head`, `-title`, `-kicker`, `-close`, `-body`, `-foot`. Read-only
summaries are `ds-deflist`.

**Files** — `ds-file-list[data-mode="edit"|"read"]` with `-row`, `-name`, `-meta`.
One component, two modes. Settled on screen 01 as D14.

**Policy counter** — `ds-meter` (a meter, not a badge). Squares count quotations,
circles count countries, a dashed square marks the one still missing. Four states
that must look different: nothing gathered · short · short by one · met.

**Status** — `ds-chip[data-tone]`, resolved through the shared status map
(`getStatusBadgeClass`, `composables/status.js`). **Measured: this screen imports it
0 times and hand-writes 13 badges, one of them a page-local ternary colour map at
`:727-728`.**

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Small is
`ds-btn[data-size="sm"]` (34 px); icon-only is `ds-btn[data-icon="1"]` (40 px square).
Waiting is a **label swap** plus `aria-busy="true"` plus `disabled` — **never a
spinner inside a button. Measured: 2 spinners inside buttons** (`:976`, `:991`).
A selection control that is not an action is `ds-seg` with `aria-pressed`.

**Forbidden here:** hand-written `class="badge bg-*"`; any page-local badge factory;
`spinner-border`; `card-table`; `form-switch` — **measured 1, and it is the policy
exception toggle** (`:928`), the single most consequential control on the screen;
`btn-xs`; `ds-table-wrap`; `ds-form-grid[data-cols="3"]`.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. **A nine-column comparison table is the
whole problem on this screen.** It has no `table-responsive` wrapper today, so it
pushes the page sideways. Wrapping it stops that but does not make it readable at
640 px — solve that explicitly. Nothing may scroll the page horizontally; wide content
scrolls inside its own container.

## 10 · Deliverables

1. The screen at 1280 / 992 / 640, loaded, with lot **4308**'s five quotations.
2. All five states — including the **forbidden** state the screen does not have, and
   the "Landed estimate" column with nothing behind it.
3. **Both** answers to S2, each drawn, with trade-offs and a recommendation. If you
   recommend (b), the drafted exception paragraph is part of the deliverable.
4. The award panel drawn against lot **4309** with the policy-exception path open,
   both required textareas, and the primary disabled — **showing which of its four
   reasons is currently blocking**.
5. The row action cell resolved: four buttons, four colours, one region.
6. The Save/Approve pair resolved for both a `sourcing` user and a `director`.
7. The RFQ count badge fixed without inventing plurals, drawn at the 3.75× worst case.
8. The nine-column table at 640 px.
9. Every question your design raised, listed. A screen this ambiguous that produces no
   questions has been answered by guessing.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's test suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
**The working pattern for this very screen already exists**:
`stabler/public/js/tests/sourcingAwardPanel.spec.js` — it reads the `.vue` as text,
pulls the decision expressions out and runs them. Extend it; do not replace it.

Do not propose a criterion that needs a browser. Every number below was measured from
`SourcingWorkspace.vue` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | Every table sits inside a `table-responsive` wrapper, and `card-table` is gone. This is the overflow the council named by name | 0 / 2 | 2 / 0 |
| K2 | `SkeletonRows` is a **sibling** of `<tbody>`, never a child. Two live `<tbody><tbody>` cases | 2 | 0 |
| K3 | Status resolves through `getStatusBadgeClass`; zero hand-written `class="badge bg-*"` and zero page-local colour maps | 0 imports / 13 badges | 1 / 0 |
| K4 | Zero `spinner-border`. Waiting is a label swap with `aria-busy` | 2 | 0 |
| K5 | Zero `form-switch`. The policy-exception toggle is a real control from the layer | 1 | 0 |
| K6 | The policy threshold never appears as a literal digit — already correct in both places, so a **regression guard** | ✓ | ✓ |
| K7 | Every alert carries `role="alert"`; the screen has at least one `aria-describedby` binding the disabled primary to its reason | 0 / 0 | 4 / 1 |
| K8 | The forbidden state renders an explanation instead of nothing: no region is gated by a bare `v-if="canSourcingView"` with no `v-else` | 2 bare | 0 |
| K9 | No count is concatenated with a bare noun. `{{ n }} {{ t("RFQs") }}` is the live case | 1 | 0 |
| K10 | Base-currency rendering is **either** absent **or** covered by a documented exception naming this file. Whichever S2 concludes, the test asserts it — a rule broken by nine sites and covered by nothing is the state that must not survive | 9 sites / 0 exceptions | asserted |

State plainly which of these your design satisfies, and name anything it cannot.
