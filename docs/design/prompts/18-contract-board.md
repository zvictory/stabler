# 18 · Contract board

> `/tender/board` · **`stabler/public/js/pages/sales/SalesOrderBoard.vue`** (192 lines)
> Server: `so_board` · `move_so_stage` · `so_stage_save` · `so_stage_delete`
> (`stabler/api/tender.py`)
>
> **Nothing in this file is invented.** Every number was produced by executing
> `so_board` against `stabler/maintenance/seed_tender_demo.py`.

---

## 0 · The screen three other prompts pointed at and none of them drew

This is the last screen in the package, and it is the one everything else exits
into:

| from | why it goes here |
|---|---|
| Prompt 14 · Director board | `useEscapeBack(null, "/tender/board")` |
| Prompt 17 · My tenders | `useEscapeBack(null, "/tender/board")` |
| Prompt 15 · Funnel | the four execution buckets — `if (st.kind === "so") router.push("/tender/board")` |

And it is `00-SETUP.md`'s coverage finding #3 made concrete: **a route in the
tender module rendering a file in the sales folder.** One route, one component,
two folders:

    router.js:41   import SalesOrderBoard from "./pages/sales/SalesOrderBoard.vue"
    router.js:295  { path: "/tender/board", name: "tender-board",
                     meta: { title: t("Contract board"), module: "tender" } }

There is **no `/sales/...` route for this component** — measured, it is mounted
once, under tender. Meanwhile its own Escape handler reads:

    useEscapeBack(null, "/sales"); // ESC → back (general app rule)

So the exit chain across the package is: director board → **Escape** → contract
board → **Escape** → `/sales`. Two prompts send the user here and this screen
sends them out of the module entirely.

The file is where it is because it was written for sales and adopted by tender.
Deciding whether it is *the tender contract board* or *the sales order kanban* is
the first design decision this prompt owes, and everything else follows from it —
including whether the trash-can button beside a column header should exist on a
screen the whole module escapes into.

---

## 1 · The product

Stabler is a tender operations SPA for a company bidding on Uzbek state railway
tenders and importing the goods it wins. After a win the lot becomes a **Sales
Order** — the contract with the buyer — and this board is where those contracts
are tracked from signature to payment.

Seven stages ship as defaults (`_DEFAULT_STAGES`, `tender.py`):

| # | stage | colour | flags |
|---|---|---|---|
| 1 | New | `#6c757d` | — |
| 2 | Procurement | `#f59f00` | — |
| 3 | Delivery | `#4263eb` | — |
| 4 | Acceptance | `#ae3ec9` | — |
| 5 | Invoicing | `#1098ad` | — |
| 6 | Paid | `#2f9e44` | `is_won` |
| 7 | Closed | `#adb5bd` | `is_closed` |

Prompt 15's four execution boxes are these seven folded by `_funnel.SO_BUCKETS`:
New → *contract*, Procurement → *procurement*, Delivery · Acceptance · Invoicing
→ *delivery*, Paid · Closed → *done*.

**A manager can add, rename, recolour and delete stages.** That makes the board's
palette *data*, not design — and it is the constraint that shapes this prompt
(S3).

---

## 2 · The gates, and the state they cannot reach

Three server gates, in order (`so_board`):

    _assert_company_scope(company)   # tenant isolation — reject a foreign company arg
    _require_tender(company)         # module role AND the company's enable_tender flag
    _require_company(company)

`_require_tender`'s docstring states the second half plainly: the flag check
exists *"so other tenants can't reach the board even by API."*

**The client renders none of them.** `load()` catches everything into
`toast.error` and leaves `stages` at `[]`. What `[]` renders is S2, and it is the
worst instance of a defect this package has now found on five screens.

---

## 3 · Nine mandates — measured

| # | Mandate | Measured |
|---|---|---|
| 1 | House layer, not Bootstrap | **FAIL** — 1 `ds-*` (the `Add stage` button). `card` · `card-sm` · `card-header` · `badge` · `progress` · `btn-ghost-secondary btn-icon btn-sm` · `vstack` · `d-flex` · `bg-primary-lt`, plus eleven inline `style=` attributes |
| 2 | Every number carries its rule | **N/A** — no counters; the column header count and total carry no rule |
| 3 | Loading is skeleton, not spinner | **FAIL** — `<span class="spinner-border text-primary">`. Nine tender screens render `SkeletonRows` on load; **four render a spinner**, and this is the only *board* among them (the others are a form, a panel and a pricing sheet) |
| 4 | Five states per region | **FAIL** — two, and one of them is wrong (S2) |
| 5 | State lives in the URL | **PARTIAL** — `?tender=1` and `tenderRouteFilters` are read; nothing is ever written back, and the funnel arrives without either (S1) |
| 6 | Keyboard and screen reader reachable | **FAIL, hardest in the package** — zero `aria-*`, zero `role=`; the only way to move a card is an HTML5 drag (S4) |
| 7 | No raw identifiers in front of a human | **PASS** — the card title is the Sales Order id, which is what a user calls it |
| 8 | Refresh is not a button | **PASS by omission** — and worse: there is no refresh at all, and no `watch(activeCompany)` either (S5) |
| 9 | Freshness is the server's | **FAIL** — no timestamp, and the data can be arbitrarily old (S5) |

---

## 4 · Hard rules

- **No dark mode.**
- **Stage colours are user data.** Whatever you draw must survive a manager
  choosing seven similar greens, or one stage with no colour at all. Do not
  design a palette that only works with the seven defaults.
- **Lazy placement is deliberate and must stay legible.** A Sales Order with no
  `custom_board_stage` is drawn in the **first open stage** without being written
  there (`so.custom_board_stage or first_open`). The card's position is a
  suggestion until someone drags it. See S6 for why that matters off this screen.
- **Do not add a second write.** This board already performs three mutations —
  move a card, create a stage, delete a stage — more than any other screen in the
  package except the document centre.
- **`is_won` and `is_closed` are on the wire.** They are not rendered anywhere
  today. A board whose last two columns mean *won* and *dead* should say so.

---

## 5 · Two states, and the empty one asks for a write

| Region | Has | Missing |
|---|---|---|
| Board | **2** — `spinner-border`, then `EmptyState` **or** the columns | error, forbidden, no-company |
| A column | **1** — cards, or 40 px of nothing | empty |

### S2 — a failed load invites the user to create a stage

    <div v-if="loading">…spinner…</div>
    <EmptyState v-else-if="!stages.length"
        icon="ti-layout-kanban"
        :title="t('No stages yet.')"
        :subtitle="t('Add a stage to start tracking contracts.')" />

`stages` is `[]` in five different situations: the request failed, the user lacks
the tender role, the company has `enable_tender` off, no company was selected
yet, or the board genuinely has no stages. **All five render the same invitation
to add a stage.**

Every other screen in the package fails into a sentence that is merely wrong
("No tenders match these filters"). This one fails into a **call to action for a
write the user is probably not entitled to perform** — and if they take it,
`so_stage_save` will reject them with a toast, which is the same channel that
swallowed the original failure.

There is a race that reaches it without any failure at all: `load()` returns
early when `activeCompany` is falsy, and there is **no `watch`** (S5), so a
session that resolves its company after mount leaves the board permanently on
this screen.

Draw the four states this needs, and note the ordering trap: `v-else-if` on
`!stages.length` means every new state must come before it.

---

## 6 · The screen

`TenderPage :label="t('Tender')" :title="t('Contract board')"`. No `#meta`.
`#actions` holds one button: **Add stage**.

Then a horizontally scrolling row of 290 px columns. Each column is a `card`
header with a 3 px coloured top border carrying: a count badge tinted from the
stage colour, the stage name, the column's money total, and a **trash button**.
Below it, a stack of draggable cards.

Each card shows: the Sales Order id, a purple flag badge when it came from a
tender, the customer name, the contract value, the delivery date, and two 4 px
progress bars — **Delivered** (blue) and **Billed** (green).

Clicking a card leaves for `/sales/orders/<name>`.

---

### S1 — the number you click and the list you get are filtered differently

`so_board` takes `tender_only`, and the flag does two things at once:

| `tender_only` | docstatus filter | deal filter |
|---|---|---|
| `0` (default) | **`docstatus: 1`** — submitted only | none — every Sales Order in the company |
| `1` | **`docstatus < 2`** — **drafts included** | `custom_crm_deal` must be set |

Two surprises in one parameter. The "tender only" mode is **narrower on one axis
and wider on the other**, and nothing on the client says so — the flag is read
from `route.query.tender === "1"` and never written, so there is no control for
it at all.

And the funnel's execution buckets — which count `docstatus: 1` Sales Orders
**tagged to a deal** — navigate here with a bare `router.push("/tender/board")`,
no query. So a user clicking a box reading *Procurement (PO) 1* lands on a board
showing every submitted contract in the company, tender-linked or not.

`TenderFunnel.vue:358-360` states the intent in a comment: execution buckets
open the contract board, *"whose columns ARE that list."* They are not. The
columns are a different query, and the filter does not travel with the click.

### S3 — the palette is user data, concatenated as hex

    const colorOf = (s) => s.color || "#6c757d";
    :style="{ borderTop: `3px solid ${colorOf(s)}` }"
    :style="{ background: colorOf(s) + '22',
              color: colorOf(s),
              border: `1px solid ${colorOf(s)}55` }"

Three problems, in increasing order of consequence:

1. **The fallback is a literal hex** — and it is `#6c757d`, which is also the
   *New* stage's colour. An uncoloured stage is indistinguishable from *New*.
2. **Alpha is string concatenation.** `+ '22'` and `+ '55'` produce a valid
   8-digit hex only if the stored value is exactly 6 digits with a leading `#`.
   A 3-digit hex, an 8-digit hex, or a CSS colour name silently yields an invalid
   declaration and the badge loses its tint.
3. **Contrast is not checked anywhere.** `color: colorOf(s)` puts the raw stage
   colour on a 13 %-alpha version of itself. `#adb5bd` (the *Closed* default) on
   `#adb5bd22` is already marginal; a manager choosing a pale yellow makes the
   count unreadable.

The design owes a rule that survives arbitrary input: derive tone from the colour
rather than using it raw, or constrain the picker to a token set. Say which.

### S4 — a kanban that cannot be operated without a mouse

The only way to move a contract between stages is an HTML5 drag:
`draggable="true"` on the card, `@dragover.prevent` / `@drop` on the column.
Measured on the whole file: **zero `aria-*`, zero `role=`, zero keyboard
handlers.** There is no menu, no "move to" control, no arrow-key affordance.

**And the card is both the drag handle and a link.** The same element carries
`draggable="true"` and `@click="openSo(c.name)"`, with no drag-distance guard and
no `@click.stop`. A press that begins a drag and ends where it started opens the
Sales Order — the user tried to move a card and left the board instead.

The move itself is optimistic and rolls back correctly on failure
(`card.stage = prev` plus a toast), which is the right shape. What it lacks is
any in-place signal: the card jumps back with an explanation in a transient toast
in a different corner of the screen.

### S5 — the board never refreshes, and does not notice a company switch

    import { computed, onMounted, ref } from "vue";   // no `watch`
    onMounted(load);

No `useAutoRefresh`, no refresh button, and — alone among the tender screens —
**no `watch(activeCompany, load)`**. Every other board in the module re-fetches
when the active company changes. This one keeps rendering the previous company's
contracts until the user navigates away and back.

Combined with three mutations and multi-user drag-and-drop, a stale board is not
a cosmetic problem: two people moving cards see divergent boards until one of
them reloads by hand, and neither is told.

### S6 — the column total adds different currencies

    "contract_value": flt(so.rounded_total or so.grand_total),   # transaction currency
    "currency": so.currency,

The card is formatted correctly — `formatMoney(c.contract_value, c.currency, …)`,
each in its own currency. The column header is not:

    formatMoney(colTotal(s.name), currency, user.language)
    colTotal = Σ c.contract_value

`colTotal` sums the raw transaction-currency figures and labels the result with
the **session's** currency. A column holding one UZS contract and one USD
contract prints their numeric sum under the company's currency symbol.

This is the package's first **money-math** defect, as opposed to a labelling one.
`base_grand_total` exists on the same doctype and is what every other total in
the module uses — prompt 14's `_deal_landed`, prompt 10's *Total committed*, and
`_deal_revenue_actual` all read the base figure. Draw the total in a way that
cannot silently add unlike units: a base-currency sum, a per-currency breakdown,
or no total.

**A second, quieter disagreement.** The board applies lazy placement — an
unplaced Sales Order is *drawn* in the first open stage — while
`tender_funnel` reads `custom_board_stage` raw and `bucket_so(None)` folds it to
**contract**. With the seven default stages these agree, because the first open
stage is *New* and *New* is the contract bucket. Reorder the stages, or mark
*New* closed, and prompt 15's execution count and this board disagree about the
same order with nothing on either screen to explain it.

### S7 — three things the payload says and the board does not

- **`is_won` / `is_closed`** — returned by `_stages()`, rendered nowhere. The
  *Paid* column means won and the *Closed* column means dead; both look like
  ordinary columns.
- **The tender link is an icon in a tooltip.** `<span class="badge bg-purple-lt"
  :title="t('From tender')"><i class="ti ti-flag"></i></span>` — the fact that a
  contract came from a tender, on the tender module's own board, is reachable
  only by hovering. **Fourth instance in the package**, after prompt 11's *Red
  Channel*, prompt 12's `freight_booking_status`, and prompt 10's evidence line.
- **`per_delivered` drives a filter nobody can see.** `filteredCards` derives
  `status: per_delivered >= 100 ? "delivered" : "delivery_pending"` on the client
  and feeds it to `filterTenderRows` — a client-side re-derivation of a server
  fact, which is the exact defect commit `26481f1` removed from the customs queue
  one screen earlier. Here it survives, and the filter it feeds has no control on
  this screen at all: it can only arrive in the URL.

### S8 — `window.prompt()`

    async function addStage() {
        const name = (window.prompt(t("New stage name")) || "").trim();

A native browser dialog, in a Vue SPA that ships `useConfirm()` — which this same
file imports and uses for **delete**. So the destructive action gets the house
dialog and the creative one gets the browser's.

`window.prompt` cannot be styled, cannot be translated below the message string
(its OK/Cancel come from the browser locale, not the app's four), offers no
validation before submission, no colour or position field, and is suppressed
outright by some browsers. It is also the only place in the package where a user
types into something the design system cannot see.

---

## 7 · Data — derived by execution, invent nothing

`_ensure_default_stages()` inserts the seven stages above on first load. The seed
creates **two** Sales Orders, both submitted (`order.submit()`,
`seed_tender_demo.py:538`), both tagged to a deal, both with an explicit
`custom_board_stage`. `per_billed` is written directly (`:540`); **`per_delivered`
is never touched, so it is 0 on both.**

Arriving from anywhere in the module means `tender_only = 0`, so the filter is
`docstatus: 1` with no deal restriction — which on seed data is the same two
orders.

**The board:**

| column | cards | column total |
|---|---|---|
| New | — | 0 |
| **Procurement** | **1** — UTY-2026-4315's order | **1 650 000 000** |
| Delivery | — | 0 |
| Acceptance | — | 0 |
| **Invoicing** | **1** — UTY-2026-4314's order | **2 270 000 000** |
| Paid | — | 0 |
| Closed | — | 0 |

**The two cards:**

| | Invoicing column | Procurement column |
|---|---|---|
| deal | UTY-2026-4314 [DEMO] | UTY-2026-4315 [DEMO] |
| customer | Qurilish materiallari kombinati [DEMO] | O'zbekiston temir yo'llari AJ [DEMO] |
| contract value | 2 270 000 000 | 1 650 000 000 |
| delivery date | today + 30 | today + 60 |
| tender flag | ✔ (tooltip only) | ✔ (tooltip only) |
| **Delivered** | **0 %** | **0 %** |
| **Billed** | **60 %** | **0 %** |

**Five of seven columns are empty, and three of the four progress bars have zero
width.** The `Delivered` bar is 0 % on both cards, so the blue bar never appears
at all — the row renders as a label, a `0%`, and 4 px of empty track.

`filterTenderRows` classifies both cards `delivery_pending`.

**States you cannot exercise from this data:**

1. A card in *New* — i.e. lazy placement (both seeded orders carry an explicit
   stage).
2. A card without the tender flag — the seed creates no non-tender Sales Order.
3. A non-zero `Delivered` bar, or a `delivered` status.
4. `EmptyState` — the defaults guarantee seven stages.
5. A stage with no colour, or a manager-created stage.
6. Anything in *Paid* or *Closed*, so `is_won` and `is_closed` are untestable
   from the demo.

**Ninth consecutive screen with states the seed cannot reach**, and the largest
count of them in the package. Label everything you draw from this list as
constructed.

---

## 8 · Vocabulary

| Term | Means, exactly |
|---|---|
| **stage** | a board column. Manager-defined: name, position, colour, `is_won`, `is_closed`. **Not** company-scoped — `_stages()` and `_ensure_default_stages()` take no company, while `so_stage_save`/`so_stage_delete` accept one and use it only as a gate |
| **lazy placement** | a Sales Order with no `custom_board_stage` is drawn in the first non-closed stage without being written there |
| **contract value** | `rounded_total or grand_total`, in the order's **own** currency (S6) |
| **Delivered / Billed** | `per_delivered` / `per_billed`, ERPNext percentages |
| **tender_only** | drafts **in**, non-tender orders **out** — one flag, two axes, no control (S1) |
| **`is_won` · `is_closed`** | *Paid* and *Closed* by default; on the wire, rendered nowhere |

---

## 9 · Responsive

Measured: zero `@media`. The layout is
`d-flex gap-3 align-items-start overflow-auto` with `min-height: 65vh` and fixed
290 px columns — so the board scrolls horizontally by construction, which is the
right instinct and the only screen in the package that got it for free.

What is unspecified: a phone. Seven 290 px columns is 2 030 px of horizontal
scroll on a 390 px screen, with drag-and-drop as the only way to move a card and
no touch equivalent. Specify it, or say explicitly that this board is desktop-only
and make the small-screen view read-only rather than broken.

---

## 10 · Deliverables

Artboards, 1440×900 unless stated.

1. **The board, populated** — seven columns, the two cards of §7 in *Procurement*
   and *Invoicing*, correct totals, five empty columns.
2. **Where this file lives** (§0) — one artboard arguing the decision: tender
   contract board or sales kanban, and what the Escape target should be.
3. **The four missing states** (S2) — error, forbidden, no-company, and a genuine
   empty — with the "add a stage" invitation appearing only in the last.
4. **An empty column** — 40 px of nothing is not a state.
5. **A stage colour system that survives user input** (S3) — including no colour,
   two near-identical colours, and a pale one.
6. **Moving a card without a mouse** (S4), and the press-that-becomes-a-click
   fixed.
7. **The column total, honest** (S6) — base-currency sum, per-currency
   breakdown, or no total. Pick one.
8. **`is_won` and `is_closed`, shown** (S7) — *Paid* and *Closed* as what they
   are.
9. **The tender flag out of the tooltip** (S7).
10. **Add stage, in the house dialog** (S8) — name, position and colour in one
    form, replacing `window.prompt`.
11. **Staleness** (S5) — what a board with three writers and no refresh should
    say about how old it is.
12. **Mobile, 390×844** — or the explicit read-only decision.
13. **An annotation board** carrying §7's six unreachable states, since this
    screen has more of them than any other in the package.

Keep the artboards you rejected.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| C1 | Seven default stages render in `position` order | passes |
| C2 | The two seeded orders land in *Procurement* and *Invoicing* with totals 1 650 000 000 and 2 270 000 000 | passes |
| C3 | A card with no `custom_board_stage` is drawn in the first open stage and not written there | passes |
| C4 | A rejected move returns the card to its previous stage | passes |
| C5 | Deleting a stage that still holds orders is refused | passes — server-side |
| C6 | Orders with status *Closed* or *Cancelled* never appear | passes |
| C7 | A failed load is distinguishable from a board with no stages | **fails** — both invite a write (S2) |
| C8 | A user without the tender role sees a refusal | **fails** — same branch |
| C9 | Loading renders a skeleton | **fails** — spinner, while the eight sibling boards use `SkeletonRows` |
| C10 | A card can be moved between stages from the keyboard | **fails** — drag only, 0 `aria-`, 0 `role=` (S4) |
| C11 | A press that does not move the card does not navigate away | **fails** — drag and click share the element (S4) |
| C12 | Switching the active company reloads the board | **fails** — no `watch` (S5) |
| C13 | A column total never adds two currencies | **fails** — transaction-currency sum under the session currency (S6) |
| C14 | The board's filter matches the number that navigated to it | **fails** — the funnel arrives without `?tender=1` (S1) |
| C15 | *Paid* and *Closed* are distinguishable from ordinary columns | **fails** — `is_won` / `is_closed` unrendered (S7) |
| C16 | "From tender" is legible without hovering | **fails** — icon plus `:title` (S7) |
| C17 | `status` is the server's classification, not the client's | **fails** — re-derived from `per_delivered` (S7) |
| C18 | Creating a stage uses the app's own dialog | **fails** — `window.prompt` (S8) |
| C19 | A stage colour the manager chose cannot make its own count unreadable | **fails** — raw colour on a 13 % tint of itself (S3) |
| C20 | The board says how old it is | **passes for the timestamp** (2026-09-02) — `generated_at`. It still never refreshes (C12), which is what makes the stamp worth reading |
