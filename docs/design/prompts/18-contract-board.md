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
| 3 | Loading is skeleton, not spinner | **PASS since 2026-09-02** (C9) — a board-shaped skeleton in Bootstrap `placeholder` utilities. As measured it was `<span class="spinner-border text-primary">`, the only *board* among the four tender screens that spun; **three still do** — `BidPricing`, `TenderIntake`, `TenderDocumentsPanel`, none of them a board |
| 4 | Five states per region | **FAIL** — two, and one of them is wrong (S2) |
| 5 | State lives in the URL | **PARTIAL, better since 2026-09-02** — `?tender_only=1` now arrives with the funnel click, is shown as a badge and can be cleared (which writes the URL). `tenderRouteFilters` is still read-only: stage/period/risk/due/status/dates are never written back (S1) |
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
| Board | **5 since 2026-09-02** — skeleton · forbidden · no-company · error · empty (C7, C9) | — |
| A column | **1** — cards, or 40 px of nothing | empty |

### S2 — a failed load invited the user to create a stage · FIXED 2026-09-02

**Kept as measured, because it is the sharpest defect the package found and the
shape of the fix follows from the measurement.** As it stood:

    <div v-if="loading">…spinner…</div>
    <EmptyState v-else-if="!stages.length"
        icon="ti-layout-kanban"
        :title="t('No stages yet.')"
        :subtitle="t('Add a stage to start tracking contracts.')" />

`stages` is `[]` in five different situations: the request failed, the user lacks
the tender role, the company has `enable_tender` off, no company was selected
yet, or the board genuinely has no stages. **All five rendered the same invitation
to add a stage.**

Every other screen in the package fails into a sentence that is merely wrong
("No tenders match these filters"). This one failed into a **call to action for a
write the user is probably not entitled to perform** — and if they took it,
`so_stage_save` rejected them with a toast, which is the same channel that had
swallowed the original failure.

A race reached it without any failure at all: `load()` returns early when
`activeCompany` is falsy and there was no `watch` (S5), so a session resolving
its company after mount sat here permanently.

**What landed (C7, C8):** the ladder is OperationsDesk's — module gate, company
gate, error, then empty — with `!stages.length` asked **last**, because it is
true in all five situations and any rung below it is dead markup. The client gate
mirrors the server's exactly: `_require_tender` (`tender.py:41`) fails on the
role **or** the company's `enable_tender` flag, and `canAccessModule` ANDs those
same two (`session.js:52-64`). The failure moved off the toast onto the board
itself, tone `danger` against the gates' `warning`, with `role="alert"`. The
*Add stage* button in the header is hidden on the two states where the write is
already known to be refused — removing the invitation from the empty state while
leaving the button beside the title would have moved the defect four inches up.
It stays on `error`: a transient load failure does not remove the right to add a
stage. The S5 race is closed separately (C12).

**What this does not settle:** the refusal names the module, not the reason.
A reader without the role and a reader on a company with tender switched off see
the same sentence, and neither is told who can change it.

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

### S1 — the number you click and the list you get are filtered differently — **FIXED 2026-09-02**

`so_board` takes `tender_only`, and the flag does two things at once:

| `tender_only` | docstatus filter | deal filter |
|---|---|---|
| `0` (default) | **`docstatus: 1`** — submitted only | none — every Sales Order in the company |
| `1` | **`docstatus < 2`** — **drafts included** | `custom_crm_deal` must be set |

Two surprises in one parameter. The "tender only" mode was **narrower on one axis
and wider on the other**, and nothing on the client said so — the flag was read
from `route.query.tender === "1"` and never written, so there was no control for
it at all.

And the funnel's execution buckets — which count `docstatus: 1` Sales Orders
**tagged to a deal** — navigated here with a bare `router.push("/tender/board")`,
no query. So a user clicking a box reading *Procurement (PO) 1* landed on a board
showing every submitted contract in the company, tender-linked or not.

`TenderFunnel.vue:358-360` states the intent in a comment: execution buckets
open the contract board, *"whose columns ARE that list."* They were not. The
columns were a different query, and the filter did not travel with the click.

**Fixed 2026-09-02 — three separate breaks, not one.** The acceptance row read
"the funnel arrives without `?tender=1`", which was true and not sufficient:

1. The funnel now pushes `{ path: "/tender/board", query: { tender_only: "1" } }`.
2. The board reads **`tender_only`**, not `tender`. Every other tender drill-down
   in the SPA — six list pages plus the router's own access guard, which grants
   tender-role users those pages *because* the query says `tender_only=1` — used
   that name already. The board was alone on its own spelling, so even a reader
   who typed the module's usual parameter got the unfiltered board in silence.
3. `so_board`'s flag is now **one axis**: it narrows to deal-linked orders and
   nothing else. The `{"docstatus": ["<", 2]}` branch is gone, so turning the
   filter on no longer ADDS the drafts. Fixing 1 and 2 alone would have landed
   the reader on a board holding rows the number never counted.

And because the funnel click now produces a mode nothing produced before, the
board says it is in one: the `bg-blue-lt` **Tender records** badge the six
sibling drill-downs already wear, plus a *Clear filter* control they do not have.
They can afford to omit it — each sits in a `ListToolbar` full of controls the
reader can already change. This board has no toolbar, so a badge alone would be a
filter you can enter and cannot leave except by editing the address bar.

**What this does not settle.** Two axes still separate the two queries, and both
are deliberate on the side that has them:

- **Closed contracts.** The board skips `status in ("Closed", "Cancelled")`; the
  funnel counts a submitted, deal-tagged order whatever its status — `bucket_so`
  says so on purpose (`_funnel.py:184-186`: hiding one "would silently shrink the
  serving number"). So a closed contract is still counted in the box and absent
  from the board. Reconciling it means changing one screen's deliberate
  behaviour, which is prompt 15's call, not this one's.
- **Permission scope.** The board filters per document with
  `frappe.has_permission`; the funnel reads through `frappe.get_all`, which does
  not. A reader who may not read an order sees it in the count and not on the
  board. The board is the correct side here; the funnel's count is the defect,
  and it is a permission question rather than a filter one.

The first of the two is now MEASURED, and the way it was measured is the point:
`tests/test_tender_board_funnel_integration.py` seeds a submitted deal-linked
order, a submitted unlinked one, a draft and a Closed one, then asserts
`funnel − board = exactly the Closed set` — so the gap is pinned in both
directions. A board that starts showing closed contracts turns that test red, and
so does a NEW divergence growing beside it, which is the half worth having.

The second is not. Observing it needs a restricted-user fixture, and
`_require_any_tender_view` may refuse such a user before the divergence is even
reachable — so it belongs in its own module rather than smuggled into that one.

Neither was visible on the seed data, and the reason is worth writing down: on
2026-09-02 both endpoints were called by hand against `genesis-test.local` and
returned the same answer, which was taken as agreement. The site held **no Sales
Order at all**. Two empty sets are equal no matter what either filter says — the
check could not have failed, so it proved nothing. `make check` cannot prove what
rows come back; neither can a run against a site with no rows.

### S3 — the palette is user data, concatenated as hex — FIXED 2026-09-02

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

**Answered 2026-09-02: derive the tone.** `composables/color.js` parses the
stored value (`#rgb`, `#rrggbb`, `#rrggbbaa`) and returns the four colours a
column needs; the alpha is arithmetic, not string concatenation, so the
shorthand and the eight-digit form work instead of silently producing a
five-or-ten-digit non-colour. Anything it cannot read falls back **whole** to the
neutral — the old code half worked on a CSS colour name, giving a coloured
number on a background that failed to render, which is worse than being wrong
consistently.

**The measurement changed the design.** The plan was "use the colour unless it is
bad". Measured against WCAG AA (4.5:1, the bar for small text, which a badge
count is): **not one of the seven seeded colours passes** as its own text on its
own 13 % tint. The best is *Delivery* at 4.18; *Closed* is 1.91 and *Procurement*
1.93. S3 called `#adb5bd` "already marginal" — every column was over the line. So
a conditional rule would have left the board exactly as it was.

The colour is therefore DARKENED until it passes, one 10 % step at a time (one to
five steps on the seeded palette; eight for near-white). Scaling all three
channels by a single factor keeps the ratios between them exact, so the hue
survives — `#f59f00` becomes `#915e00`, still unmistakably the orange column.
Substituting a fixed ink would have been fewer lines and would have thrown the
hue away on all seven columns at once; the test that fails if anyone does that is
`stageColor.spec.js`'s "keeps the hue while it darkens".

**Problem 1, answered 2026-09-02 — and the paragraph that stood here was wrong.**

It said `so_stage_save` "takes no colour argument". It does, and always has:
`so_stage_save(company, stage_name, position=0, color="", …)` with
`doc.color = color or doc.color`. The endpoint was never the missing half — the
BOARD never sent one. The consequence was the same and the diagnosis was not, so
the sentence is corrected rather than deleted.

**Measured first, and the measurement changed the fix again.** The obvious repair
is to swap the neutral for a grey that is not *New*'s. It does nothing. The badge
is a 13 % tint over white, so two greys converge: measured against *New*'s badge,
`--ds-info` (#8b95a5) reads 1.04:1, `--ds-tx3` 1.04, `--ds-ln2` 1.11 and *Closed*
1.08 — 1.00 being identical. There is no grey that reads as "unset" beside *New*.
Only **no fill** does, so an uncoloured stage is now rendered as uncoloured:
`transparent` badge, `--ds-ln2` rule, `--ds-tx2` count. That also deletes the
literal hex, which is what problem 1 actually complained about.

**And the real repair is upstream: a new stage is born with a colour.** The board
now sends one, generated rather than picked from a list — because a list cannot
clear the bar the board already sets for itself. Of the ten colours in the CRM's
own kanban palette (`Deals.vue`), **nine sit within 18° of a seeded stage's hue**
— `cyan` is 4° from *Invoicing*, `gray` 0° from *New*, `yellow` 2° from
*Procurement* — while the seeded seven are 40° apart at their own tightest
(*Invoicing* 188° / *Delivery* 228°). So `nextStageColor` puts each new stage in
the middle of the widest unused arc, at the median saturation and lightness of
the five chromatic seeded stages (81 % / 48 %), and ignores greys, which occupy
no hue: *New* is 7 % saturated and *Closed* 11 %.

On a full default board the eighth stage lands **55° from every seeded hue** —
better than the palette's own spacing — and the generator keeps working after a
stage is deleted or recoloured, which a fixed list stops doing on the first edit.

**What this does not settle.** The gap shrinks as the wheel fills: 55°, 46°, 30°,
28°. That is not a defect to fix later — on a board of fifteen stages there is no
set of fifteen distinguishable hues to hand out — but it does mean the guarantee
is "the best colour still available", not "always distinguishable". The manager
still cannot CHOOSE a colour from the board; that was the option not taken on
2026-09-02, and editing an existing stage's colour remains impossible from this
screen.

**The CRM kanban carried all three problems too — fixed 2026-09-02, same day.**
`Deals.vue` survived this section's first pass because the two boards store
colour differently: the CRM stores a NAME resolved through `KANBAN_COLORS`, this
board stores hex, so nothing that repaired one touched the other. Measured before
changing it, and it was worse here:

- **Problem 3, contrast:** 0 of the 10 palette colours clear AA as their own text
  on their own tint (yellow 2.58, purple 4.41) — the same result as this board's
  0 of 7. AND a fourth site this board does not have: the deal's money figure is
  printed in the column's colour on the **white card**, where 6 of 10 fail (green
  3.30, yellow 2.94, blue and cyan 3.68). The four that pass are the dark ones, so
  the defect was invisible to anyone whose columns happened to be red or purple.
- **Problem 1, the fallback:** `colorHex` substitutes `#6b7280`, which is also the
  palette's own `gray` — an uncoloured column and a deliberately grey one rendered
  identically. Verbatim the same defect, in a second file.
- **Problem 2, concatenation:** latent, not live. `colorHex` only ever returned a
  six-digit hex from a closed list, so `+ '22'` did produce a valid colour. It is
  one non-palette hex from not doing so, which is why it went.

Four text sites now draw from `stageTone`; the tint is the harder surface, so the
same darkened value clears AA on the white card too (5.12–6.34) and no second
helper exists. One consequence for this board: the uncoloured tone was written
with house tokens (`var(--ds-ln2)`, `var(--ds-tx2)`) and is now CSS keywords —
those tokens resolve inside TenderPage's `.stbl-ds` and NOT under App.vue's plain
`.page`, where the CRM renders, and an undefined custom property invalidates the
whole declaration silently.

**The picker reported the wrong state, and that turned out to be the live half.**
`CRM Deal Status.color` is a **Select**, not free text: thirteen options — black,
gray, blue, green, red, pink, orange, amber, yellow, cyan, teal, violet, purple —
with a doctype default of `gray`. `KANBAN_COLORS` draws **ten** of the thirteen,
so `black`, `amber` and `violet` are legal, storable from the Frappe desk or the
CRM app's own screens, and unresolvable here. They fell to `colorHex`'s grey
fallback, which is itself one of the ten. The reader saw a grey dot in the ⋯
menu, opened the picker, and found no swatch selected: two surfaces disagreeing
about one column, neither of them right.

Fixed 2026-09-02 on Zafar's instruction ("seçicide de renksiz durumu göster"):
the menu dot and the picker both show a dashed hollow circle when the stored
colour is not one the palette can draw. Shown, **not** offered — the Select has
no blank option, so there is no valid value to write and the indicator is a
`span`, not a button.

**Then the three were added** ("eksik üç rengi de ekle"), so the picker now draws
all thirteen: `amber` `#d97706` and `violet` `#7c3aed` — Tailwind 600, which is
what the CRM app's own `parseColor` renders (`text-${color}-600`) — and `black`
`#111827`, gray-900, because that app maps black to its darkest ink token rather
than to pure black and this palette is Tailwind throughout.

Adding them **costs separation, measured**: purple/violet reads ΔE 10.6 on the
darkened count colour and yellow/amber 13.2, against the palette's previous
worst pair, orange/red, at 21.2 — and under about 10 is where two colours stop
being tellable apart. It is still right, because the alternative was never
"keep them apart": all three were rendering AS GREY, a separation of zero from a
colour already on the board. And 600 is the widest shade available, not merely
the faithful one — violet-700 reads 9.1 and amber-700 drops to 9.0 against
orange. `amber` is squeezed between yellow and orange by definition; that is
what the name means on this wheel.

The uncoloured indicator stays: an empty colour is still reachable, and it is
now the only thing it reports.

`currentColor` and not a house token, for the reason above: this component
renders under App.vue's plain `.page`.

**Still not unified, and deliberately not:** the CRM stores colour names, this
board stores hex. Sharing one palette would need one of them to change what it
writes to the database. The probability bar keeps the grey fallback on purpose —
it is a FILL, not text, and a fill of nothing is invisible.

### S4 — a kanban that cannot be operated without a mouse — FIXED 2026-09-02

The only way to move a contract between stages was an HTML5 drag:
`draggable="true"` on the card, `@dragover.prevent` / `@drop` on the column.
Measured on the whole file: **zero `aria-*`, zero `role=`, zero keyboard
handlers.** There was no menu, no "move to" control, no arrow-key affordance.

**And the card was both the drag handle and a link** — the same element carried
`draggable="true"` and `@click="openSo(c.name)"` with nothing between them.

**What was done.**

- The card is now `role="button"` + `tabindex="0"`, with Enter and Space opening
  the order. That half is not new here: the sibling kanban
  (`TenderCrm.vue:568-580`) already made exactly this choice, and for a stated
  reason — Firefox will not drag a real `<button>`, so a div carries the role.
- **← and → move the focused card one stage.** This IS new: no screen in this
  repository had a keyboard move, and the CRM board's stage stepper is a
  read-only `<span>` list (`TenderCrm.vue:838-848`), so there was nothing to
  copy. The rules it follows are asserted rather than left to be inferred — one
  stage per press, `.prevent` so the scrolling strip does not slide instead, no
  wraparound at either end, and the focus is put back on the card where it
  landed (`nextTick` + `querySelector` + `focus()`, the shape the item tables
  already use, `SalesOrderFormClassic.vue:578`).
- The drop and the two arrows now go through **one** `moveCard`. Two copies
  would mean two rollbacks, and the one nobody exercises is the one that rots.
- The card announces itself: `aria-label` names the order, its stage, and what
  the arrows do. A focusable div otherwise reads as "button" and nothing else.

**A correction to what this prompt claimed.** It said a press that begins a drag
and ends where it started opens the Sales Order. That was reasoned, not
measured, and the HTML5 drag model says the opposite: a browser does not fire
`click` after a completed drag. The two failure modes that DO reproduce are
different ones, and both are worse:

- a press that nudges the card a few pixels never reaches the browser's drag
  threshold, so no drag starts at all and the release arrives as an ordinary
  click — the reader reaches for a contract and leaves the board;
- on a touch screen `draggable` does nothing whatever, so **every** attempted
  drag was a tap that navigated away.

The guard is a pointer-distance check (6 px of slack, because a hand on a
trackpad moves one or two on any real click) plus a flag set on `dragstart` —
the latter guards the case the spec says cannot happen, which is one fewer
browser behaviour this board bets on.

**What this does not settle.**

- **The rollback is still only a toast.** The move is optimistic and rolls back
  correctly, but the card jumps back with its explanation in a transient message
  in a different corner of the screen. Unchanged, and not in C10 or C11.
- **Discoverability for a sighted keyboard user.** The arrows are announced to
  assistive technology and nowhere else. A visible hint on every card is a
  design change no acceptance row asks for, so it was not made.
- **The board is still not a list or a grid to assistive technology.** The cards
  are buttons; the columns carry no accessible name beyond their visible header,
  and there is no announcement that a move happened.
- **None of it is verified in a real browser.** The tests are DOM-less
  (`vitest.config.mjs`). The one link the component's own source cannot vouch
  for — that `.arrow-left` actually reaches `ArrowLeft` — IS measured, by
  compiling the card's real tag with `@vue/compiler-dom` and checking Vue's
  `hyphenate(event.key)` contract, because a modifier typo raises no error and
  would leave every other test in the file green while the feature did nothing.

### S5 — the board never refreshes

**Half of this section was fixed on 2026-09-02 and the correction is recorded
here rather than deleted.** As measured, the file read:

    import { computed, onMounted, ref } from "vue";   // no `watch`
    onMounted(load);

No `useAutoRefresh`, no refresh button, and — alone among the tender screens —
**no `watch(activeCompany, load)`**. Switching company kept the previous
company's contracts on screen; a session that resolved its company *after* mount
never loaded at all, because `load()` returns early on a falsy company, and the
board sat on the S2 empty state telling the reader to add a stage.

That half is closed (C12). The board now watches the active company, and carries
a request token the four read-only siblings do not: it is the only board in the
module that writes, and it mutates `cards` in place during an optimistic drag, so
a late answer from the previous company would repopulate the board underneath the
reader's hand.

**What stands:** there is still no `useAutoRefresh` and no refresh control of any
kind, and the board still has three mutations and multi-user drag-and-drop. Two
people moving cards see divergent boards until one of them reloads by hand, and
neither is told. The freshness stamp added alongside C12 makes the staleness
*legible* (C20); it does not make it *go away*. Design what a board with three
writers and no refresh should do about that.

### S6 — the column total adds different currencies — **FIXED 2026-09-02**

    "contract_value": flt(so.rounded_total or so.grand_total),   # transaction currency
    "currency": so.currency,

The card is formatted correctly — `formatMoney(c.contract_value, c.currency, …)`,
each in its own currency. The column header is not:

    formatMoney(colTotal(s.name), currency, user.language)
    colTotal = Σ c.contract_value

`colTotal` sums the raw transaction-currency figures and labels the result with
the **session's** currency. A column holding one UZS contract and one USD
contract prints their numeric sum under the company's currency symbol.

This was the package's first **money-math** defect, as opposed to a labelling one.

**Fixed as a per-currency breakdown** (`colTotals`, `SalesOrderBoard.vue`): the
header prints one line per currency present in the column, ordered by currency
code, and nothing at all for an empty column. A single-currency column — every
column on the seeded data — renders the same one line it rendered before.

The obvious alternative was the base-currency sum, and the paragraph that used
to stand here argued for it: `base_grand_total` exists on the same doctype and
is what every other total in the module reads — `_deal_landed` (`tender.py:585`),
`_deal_revenue_actual` (`:1084`), the AP/AR totals (`:972`). That argument was
weaker than it looked here, for three reasons.

- `.claude/rules/10-frontend.md` renders amounts in their own currency and grants
  exactly **three** documented exceptions — the Sales Order footer `≈` line, the
  Journal Entry residual, and the Sourcing workspace's *Delivered total*. Each was
  argued for a screen that cannot do its job without the conversion. A kanban
  column header is not that screen, so this route would have needed a fourth.
- The module's other base-currency totals are **cross-deal aggregates**, where one
  number is the entire product. This total sits directly above the very cards it
  sums, each already labelled in its own currency — so a breakdown is legible in a
  way an aggregate's would not be, and a conversion beside unconverted cards would
  invite exactly the subtraction that does not work.
- `so_board` does not send `base_grand_total` (`tender.py`, `so_board` fieldset):
  it sends `currency` and the transaction-currency `contract_value`. The breakdown
  is a client-only change; the base sum would have needed the server too.

**What this does not settle.** A column holding four currencies now prints four
lines and grows the header. That is honest and it is also noisier — if it becomes
a real complaint on real data, the conversion route is still open, and it should
be taken as a fourth documented exception with its reasoning written down, not as
a quiet `× rate`.

**A second, quieter disagreement.** The board applies lazy placement — an
unplaced Sales Order is *drawn* in the first open stage — while
`tender_funnel` reads `custom_board_stage` raw and `bucket_so(None)` folds it to
**contract**. With the seven default stages these agree, because the first open
stage is *New* and *New* is the contract bucket. Reorder the stages, or mark
*New* closed, and prompt 15's execution count and this board disagree about the
same order with nothing on either screen to explain it.

### S7 — three things the payload says and the board does not

- **`is_won` / `is_closed` — FIXED 2026-09-02.** Returned by `_stages()` and
  rendered nowhere: the *Paid* column meant won and the *Closed* column meant
  dead, and both looked like the five ordinary ones between them. The header now
  carries a chip for each, in words — "Won" and "Closed", which are the doctype's
  own labels rather than a second vocabulary invented for the screen. Two
  separate `v-if`s, not a `v-else`: both are Check fields a manager can set
  together, and an alternative would hide one of the two facts with no sign it
  had. Nothing had pinned the payload either; `tests/test_tender_stage_flags.py`
  now does, including that the default seven still exercise both flags — a
  default set where nothing is won means the chips are never drawn and C15 is
  satisfied only in principle.

  Accepted, not solved: on the default board this renders "Closed [Closed]". The
  alternative is suppressing a chip when it matches the stage's NAME, which is a
  rule that stops working the moment either is translated.
- **The tender link was an icon in a tooltip — FIXED 2026-09-02.** `<span
  class="badge bg-purple-lt" :title="t('From tender')"><i class="ti ti-flag">
  </i></span>` — the fact that a contract came from a tender, on the tender
  module's own board, was reachable only by hovering, which on a touch device
  means not at all. It was the **fourth instance in the package**, after prompt
  11's *Red Channel*, prompt 12's `freight_booking_status`, and prompt 10's
  evidence line. The badge now reads `⚑ Tender`. The icon stays — beside a word
  it helps scanning, instead of one it is a puzzle — and the `:title` goes,
  because a second wording of the same fact is the one that drifts.
- **`per_delivered` drove a filter nobody can see — FIXED 2026-09-02.**
  `filteredCards` derived `status: per_delivered >= 100 ? "delivered" :
  "delivery_pending"` on the client and fed it to `filterTenderRows`. The rule
  was not wrong: `tender_dashboard` applied the identical `flt(so.per_delivered)
  >= 100` in Python, which is the whole point — two copies of one rule, in two
  languages, with nothing holding them together, the same defect commit
  `26481f1` removed from the customs queue one screen earlier. It now lives once,
  in `_funnel.delivery_state`, beside the module's other pure classifications;
  `so_board` sends the word and both the board and the dashboard read it from
  there.

  Writing it cost a lesson worth recording. `tender.py` imports `_funnel`
  **locally, inside four separate functions**, and has no module-level import at
  all. The first version of this change called `_funnel.delivery_state` from two
  more functions and every source-text assertion stayed green while BOTH
  endpoints raised `NameError` on the first request. A regex cannot see scope, so
  the guard that catches it parses the AST instead
  (`tests/test_tender_delivery_state.py`).

  Still true, and untouched: the filter this feeds has no control on this screen.
  It can only arrive in the URL.

### S8 — `window.prompt()` — FIXED 2026-09-02

    async function addStage() {
        const name = (window.prompt(t("New stage name")) || "").trim();

A native browser dialog, in a Vue SPA that ships `useConfirm()` — which this same
file imports and uses for **delete**. So the destructive action gets the house
dialog and the creative one gets the browser's.

`window.prompt` cannot be styled, cannot be translated below the message string
(its OK/Cancel come from the browser locale, not the app's four), offers no
validation before submission, no colour or position field, and is suppressed
outright by some browsers — in which case it returns null, `addStage` returns
early, and the stage is silently never created with nothing on screen to say so.

**FIXED 2026-09-02.** `useConfirm` gained a second entry point, `prompt()`, on
the same state as `confirm()` — ConfirmHost is 130 lines of focus management,
Escape handling and a tab trap, and a parallel PromptHost would be a second copy
of every one of them; this repository has already measured what that costs. The
host draws a field only when one was asked for, focuses it rather than a button
(a native prompt puts the caret in the field), submits on Enter through the same
path as the button, refuses a required field that is empty, and keeps the field
in the tab cycle. `prompt()` resolves the trimmed text or **null** — cancel and
"typed nothing" are different intentions, a distinction `window.prompt` itself
drew and one it would be odd to lose while replacing it.

**Still true of the package, and outside C18:** eleven other call sites use
`window.prompt` — seven of them the same "Reason for the status correction:"
across `imports/`, plus two in `hr/CorrectionsQueue.vue` whose own comment says
"A proper note input would require a modal; here we use window.prompt for
brevity." They now have somewhere to go. None of them was touched.

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
| **tender_only** | non-tender orders **out**, and nothing else — one flag, one axis since 2026-09-02. Arrives from the funnel, shown as a badge, clearable. It was two axes: drafts **in** as well (S1) |
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
3. ~~**The four missing states** (S2)~~ — landed 2026-09-02. What is still open:
   the refusal says only that the module is denied, not whether the role or the
   company flag denied it, nor who can change either.
4. **An empty column** — 40 px of nothing is not a state.
5. ~~**A stage colour system that survives user input** (S3) — including no
   colour, two near-identical colours, and a pale one.~~ **Done 2026-09-02** —
   parsed not concatenated, darkened to WCAG AA, uncoloured rendered as
   uncoloured, and new stages generated into the widest unused hue arc.
6. **Moving a card without a mouse** (S4), and the press-that-becomes-a-click
   fixed.
7. ~~**The column total, honest** (S6) — base-currency sum, per-currency
   breakdown, or no total. Pick one.~~ **Done 2026-09-02** — per-currency
   breakdown, for the three reasons under S6.
8. **`is_won` and `is_closed`, shown** (S7) — *Paid* and *Closed* as what they
   are.
9. **The tender flag out of the tooltip** (S7).
10. **Add stage, in the house dialog** (S8) — name, position and colour in one
    form, replacing `window.prompt`.
11. **Staleness** (S5) — the board now says how old it is; it still has no
    refresh and three writers. What should it do when the stamp goes cold?
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
| C7 | A failed load is distinguishable from a board with no stages | **passes** (2026-09-02) — five rungs, `!stages.length` last (S2) |
| C8 | A user without the tender role sees a refusal | **passes** (2026-09-02) — `canAccessModule('tender')`, which mirrors the server's role-or-flag gate |
| C9 | Loading renders a skeleton | **passes** (2026-09-02) — four column placeholders at the board's own width. Not `SkeletonRows`: its root is a `<tbody>` |
| C10 | A card can be moved between stages from the keyboard | **✔ 2026-09-02** — `tabindex=0` + `role=button`, Enter/Space open, ← / → move one stage with no wraparound, focus restored where the card lands. Drop and arrows share one `moveCard` (S4) |
| C11 | A press that does not move the card does not navigate away | **✔ 2026-09-02** — 6 px pointer-distance guard plus a `dragstart` flag. The reproduction this prompt originally gave was wrong; the two that do reproduce are a sub-threshold press and any touch device, where `draggable` does nothing at all (S4) |
| C12 | Switching the active company reloads the board | **passes** (2026-09-02) — plus a request token, so a superseded company's answer cannot land (S5) |
| C13 | A column total never adds two currencies | **✔ 2026-09-02** — one line per currency, sorted by code; the session currency is no longer read by this screen (S6) |
| C14 | The board's filter matches the number that navigated to it | **✔ 2026-09-02, measured on real rows** — `tests/test_tender_board_funnel_integration.py` (bench) seeds four orders that separate every filter the pair applies and asserts `board(1) − funnel = ∅`, `funnel − board(1) = exactly the Closed set`, and that the chevron's number equals the list it drills to. The by-hand check earlier that day said "equal" only because the test site held **no Sales Order at all**. Per-document read permission is still unmeasured (S1) |
| C15 | *Paid* and *Closed* are distinguishable from ordinary columns | **✔ 2026-09-02** — a "Won" / "Closed" chip per flag, two independent `v-if`s, the doctype's own labels (S7) |
| C16 | "From tender" is legible without hovering | **✔ 2026-09-02** — the badge reads `⚑ Tender`; icon kept, tooltip removed (S7) |
| C17 | `status` is the server's classification, not the client's | **✔ 2026-09-02** — one rule in `_funnel.delivery_state`; `so_board` sends it, the dashboard counts by it, the client re-derives nothing (S7) |
| C18 | Creating a stage uses the app's own dialog | **✔ 2026-09-02** — `useConfirm().prompt()`, the same host `deleteStage` already used; field focused, Enter submits, empty refused (S8) |
| C19 | A stage colour the manager chose cannot make its own count unreadable | **✔ 2026-09-02** — parsed, tinted with real alpha, and darkened until it clears WCAG AA on its own tint; hue preserved. None of the seven seeded colours passed before (S3) |
| C20 | The board says how old it is | **passes for the timestamp** (2026-09-02) — `generated_at`. It still has no refresh of any kind, which is what makes the stamp worth reading (S5) |
