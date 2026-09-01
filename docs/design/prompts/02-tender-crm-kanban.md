# 02 · Tender CRM kanban

**Source:** `stabler/public/js/pages/tender/TenderCrm.vue` — 916 lines,
**107 `ds-*` sites**, 0 `tgm-*`. The module's reference screen.
**Why second:** it is the intake drawer's home, and **both dialects live in this one
file** — a native `ds-drawer` at `:578-721` and `TenderMasterDrawer` (all `tgm-*`)
mounted at `:753`. One screen, two languages. That is why brief question **S1** is
answered here.

**Correction this prompt carries:** Phase A §1.3 records **one** live
`<tr role="button">` in the module (`TenderDocuments.vue:257`). Re-measured with a
multi-line-aware search, there are **two** — the second is `TenderCrm.vue:535`, spread
across lines and therefore invisible to a single-line grep. That is the same failure
mode Phase A had already caught and corrected once in its own version 1.

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

The first three entries of every row are the same three people — an administrator
sees all four windows. **This screen belongs to `sourcing`**; a director sees it too.

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

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** Colour alone
  carries no information.
- **Text colour and fill/border colour are different tokens.** The bright orange
  "today" token measures 2.3:1 on white; there is a separate dark text token at 7:1.
  Never put a bright severity colour on body text.
- **The procurement policy numbers are server values.** They must **never** appear as
  literal digits in the design. This screen already does it right — copy that, see §7.
- **No fixed-width label, badge or nav item.** Measured worst-case interface-language
  growth is **3.75×** (`RFQs`, 4 characters → Uzbek `Narx so'rovlari`, 15). Four
  languages ship: en, ru, uz, tr — plus `uzc` (Uzbek Cyrillic), no longer selectable
  but still rendered, and it must not break. **A kanban lane header is the worst place
  in the product for this** — it holds a count and a label side by side in a narrow
  column.
- **String interpolation exists; plurals do not.** You cannot write "1 quotation /
  5 quotations".
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
- **Do not write code.**

## 5 · Five states — every region, every time

| state | how it is drawn |
|---|---|
| **loaded** | the real data below |
| **empty** | the shared empty-state component, in its **compact** form inside a kanban column — a lane with no cards is a normal condition, not an error |
| **error** | a danger alert with `role="alert"`, the raw message in monospace, and a "Try again" action |
| **forbidden** | a warning alert with `role="alert"`, a lock icon, and a route button |
| **not measurable** | the fifth state — see §7, it is present in this data |

Every region carries a test hook `data-region-state="loading|empty|error|forbidden"`.
**No CSS may bind to that attribute.**

## 6 · The screen

**Tender CRM kanban.** Its one job: show every live tender as a card in the lane that
matches its stage, and let a sourcing user open, edit or advance one.

**What is on it today**

- **Lanes come from the server**, not from a hard-coded list. A lane header carries a
  **count** and a **label**; below it a rule carries the **lane total** in monospace.
- Six lanes are classified post-win: `po_created`, `customs`, `transit`, `delivered`,
  `invoiced`, `done`.
- **A card carries:** title · id (monospace) · buying organisation · a foot with
  either the contract value or the words *"no value yet"*, and a deadline stamped with
  a severity derived from risk · and a **policy meter**.
- **There is a list view as well as the kanban**, over the same filtered cards.
- **A deal drawer** opens on card click. Its footer holds: `Edit tender` (the single
  primary) · `Sourcing comparison` · `Doc Center` · `PO Control` · `Close` · and a
  conditional `Delete`. **Six actions, one primary.** Judge whether the
  one-primary-per-region rule actually survives that, and say so.

### The question this screen exists to answer — S1

**How do three dialects become one?** Two separate sub-questions; do not merge them.

**(a) The nine classes whose names match but whose measurements do not.**
`ds-*` already has a class doing the same job, at a different size:
width **720 px ↔ 542 px**, z-index **1050 ↔ 41**, title **18 px ↔ 22 px**, section
frame **present ↔ absent**. Which value wins? Did the intake drawer need 720, or is
542 enough? **This decision reaches every other screen that uses `ds-drawer`** — and
you have a working `ds-drawer` to compare against **in this very file**, at
`:578-721`. Look at it before deciding.

**(b) The six classes with no equivalent.** `tgm-file-chip`, `tgm-file-list`,
`tgm-file-name`, `tgm-sec-num`, `tgm-drawer-dialog`, `tgm-drawer-content`. The last
two are Bootstrap modal scaffolding — `ds-drawer` brings its own shell, so those are
**deleted, not renamed**. Are the remaining four a genuine gap in `ds-*`? If so, what
should be added?

Draw **at least two ways** to resolve (a), write the trade-offs of each, recommend one
and give the reason. "It depends" is not an answer.

### An architectural problem you must show, not solve

`.ds-drawer` has **z-index 41**. The Bootstrap modal band starts at **1040**. The
drawer lives on the same page as real modals. Your design has to make clear which
surface sits above which, but the fix itself is an open decision and not yours to
close.

### Two accessibility tensions — surface them, do not smother them

1. **The card is a `<div role="button" draggable="true">`, on purpose.** The file's
   own comment gives the reason: Firefox will not drag a real `<button>`. Keyboard
   access was bolted on with `tabindex` and Enter/Space handlers. So the code traded
   semantics for drag, knowingly.
2. **The list view's row is a `<tr role="button">`** with `tabindex="0"` and an Enter
   handler. That pattern is on the module's forbidden list; the replacement is a real
   focusable control inside the row, plus a click handler on the row for the mouse.

The hard part is that **one answer has to cover both** — the draggable card is the
harder case. Draw it.

## 7 · Data — use these rows, invent nothing

Thirteen lots, **seven stages, exactly two lots per stage** (the last stage has one).
Do not write "Acme Corp / Lot-001 / $1,000"; that tests nothing.

| lane | lot | buyer | days at stage | quotes / countries | value |
|---|---|---|---|---|---|
| seen | `UTY-2026-4301` | O'zbekiston temir yo'llari AJ | 1 | 0 / 0 | — |
| seen | `UTY-2026-4302` | Toshkent vagon ta'mirlash zavodi | 3 | 0 / 0 | — |
| go | `UTY-2026-4305` | O'zbekiston temir yo'llari AJ | 4 | 1 / 1 | 1 840 000 000 |
| go | `UTY-2026-4306` | Signal va aloqa boshqarmasi | 5 | 0 / 0 | 640 000 000 |
| sourcing | `UTY-2026-4308` | Signal va aloqa boshqarmasi | **19** | 5 / 3 | 920 000 000 |
| sourcing | `UTY-2026-4309` | Qurilish materiallari kombinati | **26** | 3 / 1 | 410 000 000 |
| priced | `UTY-2026-4310` | O'zbekiston temir yo'llari AJ | **8** | 6 / 2 | 3 150 000 000 |
| priced | `UTY-2026-4311` | Neft mahsulotlari bazasi | **6** | 5 / 2 | 780 000 000 |
| submitted | `UTY-2026-4312` | Neft mahsulotlari bazasi | **none** | 4 / 2 | 480 000 000 |
| submitted | `UTY-2026-4313` | Toshkent vagon ta'mirlash zavodi | **none** | 5 / 2 | 1 120 000 000 |
| won | `UTY-2026-4314` | Qurilish materiallari kombinati | 40 | 5 / 2 | 2 270 000 000 |
| won | `UTY-2026-4315` | O'zbekiston temir yo'llari AJ | 55 | 6 / 3 | 1 650 000 000 |
| lost | `UTY-2026-4316` | Signal va aloqa boshqarmasi | 48 | 5 / 2 | 890 000 000 |

**Currency:** the source data names none — zero occurrences. Amounts arrive with the
record and the site default (most likely UZS). **Do not hard-code a symbol.**

### Four things in this data that the design must not smooth over

**1 · Stage age is already overrun in two lanes.** The stage thresholds are
seen 3 · go 5 · sourcing 14 · priced 3 · submitted 30 days. So `4308` at 19 days and
`4309` at 26 days are both **past** the 14-day sourcing threshold, and both priced
lots are past the 3-day one. The board must be able to say that without a colour
being the only thing saying it.

**2 · The fifth state is here.** `4312` and `4313` carry **no stage stamp at all**.
Anything that averages stage age must read **"Not measurable"** and
**"{n} without a stage stamp — not averaged"** — never a number, never a zero.

**3 · The policy meter has one genuinely interesting case.** Seven lots satisfy the
procurement policy and six do not. The one worth designing for is **`4312`: it clears
the country requirement and misses the quotation count by exactly one.** A board that
draws it the same as `4301` (nothing gathered at all) has thrown away the only
information a sourcing user needs.

**This screen already implements the server-value rule correctly**: the meter's fill
state is set only when both conditions hold, and its text reads
`{count} / {threshold-from-server}` with a **dash fallback** when the policy has not
loaded. Keep that. It is the pattern every other screen should copy.

**4 · All three deadline severities are on this one board.** `4305` was due
**yesterday**; `4308` is due **today**; `4310` is due **in two days**. The rest run
from +6 to +32 days. Colour is not enough — each needs a shape and a word too.

## 8 · Vocabulary

**Kanban** — `ds-kanban` > `ds-col` > `ds-col-head` (with `ds-col-n` for the count and
`ds-col-t` for the label) / `ds-col-rule` / `ds-card` (with `-t`, `-id`, `-org`,
`-foot`). Lane urgency is `ds-col-head[data-sev]`.

**Note the trap:** `ds-col-n` is styled only by the selector `.ds-col-head .ds-col-n`.
On a table `<th>` it does nothing — the numeric cell class is `ds-td-num`.

**Drawer** — `ds-drawer[data-size="lg"]` (760 px) with `-backdrop`, `-head`, `-title`,
`-kicker`, `-close`, `-body`, `-foot`. Read-only summaries inside it are `ds-deflist`.

**Table** — `ds-table`, and a `table-responsive` wrapper is **mandatory**. Numeric
cells are `ds-td-num`. Row emphasis is `tr[data-sev]` plus a `ds-chip[data-tone]` in
the row. Striped is the default: the migrating class is `ds-table table`.

**Policy counter** — `ds-meter` (a meter, not a badge).

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Small is
`ds-btn[data-size="sm"]` (34 px); icon-only is `ds-btn[data-icon="1"]` (40 px square).
A disabled control carries **its reason beside it**. Waiting is a **label swap** plus
`aria-busy="true"` plus `disabled` — never a spinner inside a button. A selection
control that is not an action is `ds-seg` with `aria-pressed`.

**Forbidden here:** hand-written `class="badge bg-*"` or a bare `class="badge"` with a
separate binding; any page-local badge factory; `spinner-border`; `btn-xs`;
`ds-table-wrap` (the wrapper is `table-responsive`); `form-switch` in new markup;
`ds-form-grid[data-cols="3"]`.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. A seven-lane kanban at 640 px is the real
problem on this screen — solve it explicitly rather than letting the board scroll off
the edge, and show what happens to the lane header when its label is four times
longer. Nothing may scroll the page horizontally; wide content scrolls inside its own
container.

## 10 · Deliverables

1. The board at 1280 / 992 / 640, loaded, with all thirteen lots in their lanes.
2. All five states — including a lane whose empty state is normal, and the
   "Not measurable" treatment for the two unstamped lots.
3. **Both** answers to S1(a) — which drawer measurements win — each drawn, with
   trade-offs and a recommendation.
4. S1(b) resolved: the four remaining orphan classes either mapped into `ds-*` or
   proposed as additions, with reasons.
5. The policy meter drawn in **four** conditions: nothing gathered (`4301`), fails
   both (`4309`), **clears countries and misses count by one (`4312`)**, and fully
   satisfied (`4310`). These must be visibly different from one another.
6. The three deadline severities drawn with colour **and** shape **and** word.
7. One answer to the accessibility tension that works for **both** the draggable card
   and the list row.
8. The drawer footer redrawn: six actions, one primary — or your argument for why it
   should be fewer.
9. Every question your design raised, listed. A screen this ambiguous that produces no
   questions has been answered by guessing.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's test suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`. The
working pattern reads the `.vue` as text, pulls the decision expressions out and runs
them.

Do not propose a criterion that needs a browser. Every number below was measured from
`TenderCrm.vue` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | Every `ds-table` sits inside a `table-responsive` wrapper. Three tables, **no wrappers** today — this is the mandate the screen breaks most quietly | 3 / 0 | 3 / 3 |
| K2 | Zero `<tr role="button">`. **Search multi-line** — the one live case has the attribute four lines below the opening tag, which is exactly how the earlier count missed it | 1 | 0 |
| K3 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K4 | The policy threshold never appears as a literal digit; the meter binds a server value **with a dash fallback**. Already correct — a **regression guard**, and the pattern every other screen copies | ✓ | ✓ |
| K5 | The list view uses the shared `ListToolbar` — mandate 8, auto-apply, no Apply/Refresh button | 0 | 1 |
| K6 | The draggable card has an accessible name and a keyboard path that the source can prove — not a `tabindex` bolted onto a `<div>` with nothing announcing it | — | asserted |
| K7 | No page-local badge factory and no hand-written `class="badge bg-*"`; status comes from the shared map | 0 | 0 |
| K8 | No fixed width on any lane header, badge or nav item in the source. Seven lanes × a label that can quadruple is where this screen fails first | — | 0 |
| K9 | A lot with no stage stamp renders the unknown state, never `0`. Runs against `4312` and `4313` | n/a | 2 |
| K10 | No `spinner-border`, no `form-switch`. Both already 0 — regression guards | 0 / 0 | 0 / 0 |

K4 and K7 are already green. They are in the list because this screen is the reference
the other sixteen copy, and a reference that silently regresses takes the copies with it.

State plainly which of these your design satisfies, and name anything it cannot.
