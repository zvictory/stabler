# 10 · PO control board

**Source:** `stabler/public/js/pages/tender/PoControlBoard.vue` — 765 lines,
**0 `ds-*`, 4 `badge bg-`, 3 `spinner-border`, 1 `form-switch`, 17 bare `btn-*`,
0 `ListToolbar`, 0 `aria-*`, 0 `SkeletonRows`**.

**But 765 lines is not the screen.** One route renders **six components and 1,696
lines**, and none of them uses a single `ds-*` class:

| component | lines | what it is here |
|---|---|---|
| `PoControlBoard.vue` | 765 | the shell, the board, and the landed-cost editor |
| `TenderIntake.vue` | 365 | the **orphan** (ADR-304), embedded at `:368` |
| `BidPricing.vue` | 287 | landed + margin → the price we bid |
| `TenderDocumentsPanel.vue` | 186 | screen 09's data, drawn as a card grid |
| `TenderDocumentChain.vue` | 48 | purchase and sales execution, side by side |
| `TenderWorkspaceTabs.vue` | 45 | the tab strip — a component the layer does not have |

**First:** this is where the tender's money is decided. The vendor comparison ranks by
**landed** cost, and the landed figure is composed by hand in a modal that is the
densest control surface in the module — one table cell can hold a `MoneyInput`, a
currency select, an FX rate field, a fetch button, a `DateInput`, a converted preview
and a provenance line, and a customs line opens a second row with six more controls.

**Second, and it is the reason this screen is drawn carefully:** that modal's footer
prints a **Landed total that omits charges it is displaying one row above**. The
module wrote down the rule this breaks — *"a charge shown at its unconverted number
reads as CHEAP and hands the tender to the wrong vendor"* — and then broke it in the
total rather than in the line. That is **S1**.

**Third:** the route is **five screens behind one tab strip**, and `stbl-ds` has no tab
component — `nav-tabs` is **0** in `stabler-modernist.css`. This screen adds one, and
it is the second genuinely new component in the package after screen 02's.

**Fourth:** this screen owes the package **two rulings** that other prompts deferred to
it — which vocabulary `TenderDocumentsPanel` speaks (prompt 09's S5), and whether
`TenderIntake` is connected or removed (ADR-304). Both are **S6**.

**Scope.** `BidPricing.vue` is drawn here because this is its only call site and the
roadmap has no other slot for it — but it is bounded to one question, not a full screen.
`TenderDocuments.vue` (the standalone document centre) is prompt **09** and is not
redrawn here; only the panel that mirrors it.

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

**This screen is post-award.** The tender is won; the question is no longer *what do we
bid* but *what did it actually cost, from whom, and has it arrived*.

## 2 · The roles, and the one gate that is different here

Gated server-side. The gate sits **at the endpoint, not in the navigation** — hiding
a menu item was already tried, and a user who knew the URL still got a 200.

| view | roles |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · Stabler Tender Director |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · Sales User · Stabler Tender Sourcing |
| `declarant` | System Manager · Stabler Admin · Sales Manager · Stabler Declarant · Stabler Tender Declarant |
| `logist` | System Manager · Stabler Admin · Sales Manager · Stabler Logist · Stabler Tender Logistics |

**The finance tab is the module's only role-conditional region**, and it is conditional
on data rather than on a claim the client makes: `tender_workspace` includes a
`finance` key **only** if `_can_view_tender_finance()` passes server-side
(`tender.py:1007`), and the client derives the tab list from whether that key exists
(`:122`). Nothing is hidden by CSS and nothing is hidden by a role check in the browser.

**Draw the two tab strips.** A user who may see finance gets five tabs; a user who may
not gets four, and there is no fifth tab greyed out. That is correct and it is the only
place in the module that does it this way — say so on the canvas, because every other
screen in this package hides things worse.

**Writing is gated separately and more tightly.** The landed plan writes through
`_po_scope(po, write=True)` (`tender.py:495`), which checks the PO's company **and**
`frappe.has_permission("Purchase Order", "write")`. So a user may open this board, read
every number, and be refused at Save. **That is the fourth state, and the screen has no
drawing for it.**

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

**Measured: this screen breaks 7, 8 and 9, and it breaks 6 in a component it hosts.**

- **Mandate 7** — `badgeMeta()` (`:137-141`) is a page-local colour map with six
  entries, plus a `partial:NN` prefix parser, plus three more hand-written badges in
  the comparison table (`:481-483`) and two policy badges in the quotations card
  (`:377-378`). **Zero** imports of the shared status map.
- **Mandate 8** — the deal picker is a bare `Typeahead` in a card (`:344-362`). No
  `ListToolbar`. Its placeholder does end with `⌘K`, which is the mandate's smallest
  half honoured while the larger half is absent.
- **Mandate 9** — three `spinner-border` (`:556`, `:758`, and the save button), **zero**
  `SkeletonRows`, and a fourth variant nobody else in the package invented: loading
  drawn as an **`EmptyState` with a loader icon** (`:537`).
- **Mandate 6** — `PoControlBoard` itself keeps it: the card prints
  `formatMoney(c.amount, c.currency || ccy)` (`:433`), each PO in its own currency. But
  `TenderDocumentChain.vue:40` prints `formatMoney(row.grand_total, currency)` — the
  document's **own-currency** figure labelled with the **tender's** currency. See S4.

**It keeps mandates 1, 3 and 4 well, and that is worth naming.** `openPo()` routes to
`/purchasing/orders/:name` inside the SPA (`:143`) rather than to Desk; the editor uses
`MoneyInput` at **7** sites and `DateInput` at **3**; `formatDate()` at every date.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.**
- **A disabled control carries its reason beside it.** The Save button is disabled only
  while saving or loading (`:757`) — never for the two conditions the server will
  actually refuse. See S2.
- **The procurement policy numbers are server values** and never literal digits. This
  screen does it correctly: `tenderPolicy.minQuotations` and `tenderPolicy.minCountries`
  are interpolated into the badge text (`:377-378`). Copy that pattern; do not
  regress it.
- **No fixed-width label, badge or nav item.** Worst-case growth **3.75×**. The editor
  has **six** fixed column widths (`:560-566`: 20 % · 13 % · 22 % · auto · 15 % · 15 % ·
  40 px) and four fixed pixel widths inside the customs row (`110`, `90`, `90`, `150`),
  plus `max-width:74px` on the currency select and `max-width:64px` on the voucher-type
  select. Four of the five tab labels are two words.
- **String interpolation exists; plurals do not.**
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
  **S1 needs no new field at all** — the number it wants is already computed on the
  client, one function away from the total that ignores it.
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

**This screen's fifth-state failure is arithmetic, not a counter.** A landed charge
whose rate is missing cannot be valued. The server says so in writing
(`tender_landed_math.py`):

> `None` is returned, never a number, when a currency is named without a usable rate.
> The caller must keep that line out of any total. Falling back to the raw figure would
> drop a 1 200 USD charge into a so'm total as 1 200, and falling back to zero would
> make the charge free; **both read as CHEAP and both hand the tender to the wrong
> vendor.**

The client's `convertedPreview()` (`:227-233`) obeys this exactly — it returns `null`,
and the cell renders a red *"Enter an exchange rate"*. **The footer then adds that line
in as zero anyway**, because it sums a different field. So the module's own rule is
honoured at the line and broken at the total, in the same modal, eighty lines apart.

**Draw the not-measurable total.** A landed total with one unvalued line inside it is
not a smaller number — it is not a number. Say so where the figure would be, and keep
the vendor comparison from ranking on it.

## 6 · The screen

The route is `/tender/po-control?deal=…&tab=…`. Above the tabs sits a deal picker; the
tab is a query parameter, so every tab is linkable and the browser's Back button walks
between them.

| tab | renders |
|---|---|
| `overview` | `TenderIntake` (the orphan) + `BidPricing` |
| `documents` | `TenderDocumentsPanel` — screen 09's data as a card grid |
| `vendor-po` | quotations card · 4 KPI cards · 4 status lanes · vendor comparison table |
| `delivery` | `TenderDocumentChain` — purchase and sales, three stages each |
| `finance` | 4 metric cards — AP, AR, planned margin, actual margin |

### S1 — the landed total omits the charge it is showing

This is the largest question on the screen and the only one in the package that is
arithmetic the user can watch go wrong.

**The two numbers.** The editor holds one array, `editorLines`. Each line has two money
fields that mean different things:

| field | meaning | who writes it |
|---|---|---|
| `amount_original` | the figure as the forwarder quoted it — 1 200 USD | the user |
| `amount` | the same charge in **company currency** | **the server**, at save |

The server is explicit about why (`tender.py:319-321`):

```python
# `amount`/`actual` stay the company-currency figures every consumer sums.
# Deriving them here — the one chokepoint both reads and writes pass
# through — is what stops the two from ever disagreeing.
```

**The footer sums `amount`** (`:154`):

```js
const editorCharges = computed(() => editorLines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0));
const editorLanded  = computed(() => (Number(editorBase.value) || 0) + editorCharges.value);
```

So while the modal is open, for any line quoted in a foreign currency:

| the line | `amount_original` | `amount` | the cell shows | the footer counts |
|---|---|---|---|---|
| **newly added**, USD 1 200 @ 12 800 | 1 200 | `null` | `= 15 360 000` | **0** |
| **edited**, was 1 000 now 2 000 | 2 000 | *the old* 12 800 000 | `= 25 600 000` | **12 800 000** |
| unvalued — currency set, no rate | 1 200 | `null` | *"Enter an exchange rate"* | **0** |
| company currency | — | 3 200 000 | 3 200 000 | 3 200 000 |

**Say the severity accurately, because it changes the fix.** The stored plan is
**correct** — `saveEditor` sends `amount_original` and the server re-derives `amount`
at the chokepoint, and the save filter was already fixed for exactly this reason
(`:322-325`: *"Filtering on `amount` alone silently dropped every such line on save"*).
So this is **not** data corruption. It is worse-placed than that: **the number is right
in the database and wrong on the screen where the decision is made.** The user picks a
vendor by reading a total, and the total is only true after they save and reload.

**Both fixes are presentational and need no new field:**

- **(a)** the totals sum `convertedPreview(l)` — the function that already sits in the
  file, already obeys the rule, and already returns `null` when it cannot value a line;
- **(b)** the totals stay as they are and the footer is **labelled** as a stored figure,
  with the live one shown beside it.

Draw both. (b) is worth drawing seriously rather than as a straw man — a footer that
says *"as saved"* is honest, cheap, and it is what half the finance screens in the world
do. Then recommend one, and say what happens to the **vendor comparison table**, which
ranks on the saved landed figure and is therefore correct today and would be correct
under either answer.

**The fifth state is the hard half.** `convertedPreview` returns `null` for an unvalued
line. A total containing one of those is **not measurable**, and drawing it as a smaller
number is the exact failure the module's own comment names. Draw:

- the footer when every line is valued,
- the footer when one line is not — the total, the count of what it excludes, and what
  the *Save plan* button does,
- and the **card in the lane** for that PO, which today prints
  `+charges → landed` (`:443-444`) from server figures and so is *right* while the
  editor above it is wrong.

**One more thing to show, not solve.** The card prints two currencies with an arrow
between them (`:433-444`): `USD 12 000` on the first line, then
`+ 3 200 000 UZS → 155 200 000 UZS landed` on the second — where the landed figure
**contains** the first, converted. An arrow between two currencies reads as addition.
Draw it, name it, and propose a reading that cannot be misread.

### S2 — two refusals the user meets only after Save, one about a field they cannot see

`save_po_landed_charges` throws on exactly two conditions (`tender.py:485-496`), and
the client prevents neither:

**One — a currency with no rate.**

```python
if c["currency"] and c["fx_rate"] <= 0:
    frappe.throw(_("Enter the exchange rate for the {0} charge: {1}").format(...))
```

The cell already says *"Enter an exchange rate"* in red (`:646-647`). The **Save plan**
button is still enabled (`:757` disables it only on `editorSaving || editorLoading`).
So the user clicks Save, waits for a round trip, and gets a toast repeating what the
cell said.

**Two — a customs line carrying a currency.**

```python
if c["currency"] and c["type"] == "customs":
    frappe.throw(_("A customs line is valued from its customs value, not from a currency quote: {0}"))
```

The rule is sound: the ГТД declares the customs value in company currency at the rate
customs itself applied, so re-deriving it from a Central Bank quote produces a figure
the declaration does not agree with.

**But the currency select is hidden for customs lines** (`:609` —
`v-if="l.type !== 'customs'"`), and changing a line's **type** does not clear its
currency (`onChargeCurrency` runs on the *currency* select's `@change` only, `:255`).
So: set the type to transport, pick USD, then change the type to customs. The select
disappears, the line still carries `currency: "USD"`, and Save is refused **naming a
field the user can no longer see**.

**Draw the validation, and decide where it lives.** Beside the line, in the footer, on
the button, or all three — and say what the *Save plan* button looks like when the plan
is unsaveable. A disabled primary carries its reason beside it (§4); a reason for one
bad line among eleven has to point at the line.

**Then answer the harder half:** should changing a line's type clear the fields the new
type cannot hold, or should the type change be refused while they are set? One silently
discards user input; the other blocks a legitimate correction. Pick one, and draw what
the user sees.

### S3 — five screens behind one route, and a tab strip the layer does not have

`stabler-modernist.css` has **no tab component**. Measured: `ds-tab` **0**, `nav-tabs`
**0**. `TenderWorkspaceTabs.vue` uses raw Bootstrap `nav nav-tabs` with
`<button class="nav-link">` (`:33-42`).

**What is missing, measured:**

- **No `role="tablist"`, no `role="tab"`, no `aria-selected`, no `aria-controls`.** The
  strip has exactly one `aria-` attribute: `aria-label` on the `<nav>` (`:33`).
- **No keyboard model.** Arrow keys do nothing; every tab is a separate tab stop.
- **Two sources of truth for which tab is active.** The parent computes
  `activeWorkspaceTab` from `route.query.tab` (`:122-126`) and passes it as `:active`;
  the strip computes `activeTab` from `route.query.tab` **again** (`:22-25`) and
  renders `:class="{ active: activeTab === tab.key || active === tab.key }"` (`:39`). The two
  agree today because both fall back to `overview` over the same set — but they build
  that set from **different lists in different orders**, and the `||` means any future
  divergence renders **two tabs active at once** rather than failing.
- **The strip's order is not the parent's order.** Strip: Overview · Documents ·
  Vendor & PO · Delivery · Finance. Parent template: Overview · Vendor & PO · Delivery
  · Documents · Finance. Nothing breaks; they are simply two opinions about the
  workflow, shipped together.

**Design the tab component for the layer, not for this screen.** It will be the
module's, so it needs: the roving-tabindex keyboard model, `aria-selected`, a
told-not-computed active state, five states of its own (a tab whose data failed to load
is not the same as a tab that is empty), and an answer at **640 px**, where five
two-word labels do not fit and 3.75× growth makes it worse.

**Then the question underneath.** Is this one screen with five sections, or five screens
sharing a deal picker? The evidence pulls both ways: the tab is a query parameter and
therefore linkable and Back-able, which argues *screens*; but a single `load()` fetches
**both** payloads for **all** tabs on every deal change (`:96-101`), which argues *one
screen*. Say which it is, and make the loading behaviour match the answer — because
today a user opening the Finance tab waits for the PO board they did not ask for.

### S4 — the chain that is not a chain, in a currency that is not the document's

`TenderDocumentChain.vue` is 48 lines and draws the delivery tab: purchase execution and
sales execution side by side, each as three stacked lists — orders, receipts (or
deliveries), invoices.

**It is called a chain and it draws three lists.** The server sends the link: every
receipt and invoice row carries `purchase_order` / `sales_order`
(`tender.py:736-749`). The component **uses that field in its `:key`** (`:36`) and
never renders it. So a tender with four POs and seven receipts shows seven receipts
with nothing to say which order each belongs to — while the data to say it is sitting
in the loop variable.

**And the money is in the wrong currency.** `_document_row` sends four money fields and
the document's own currency:

| field sent | rendered |
|---|---|
| `grand_total` — the document's own-currency figure | **yes** |
| `currency` — the document's own currency | **no** |
| `base_grand_total` — the company-currency figure | no |
| `outstanding_amount` / `base_outstanding_amount` | no |
| `status`, `docstatus` | no |

`:40` renders `formatMoney(row.grand_total, currency, language)` where `currency` is the
**prop** — the tender's currency. **A USD 12 000 purchase invoice renders as
12 000 UZS.** Mandate 6 exists for this, and the correct field is one word away.

**Four things to draw:**

1. the chain **as a chain** — receipts and invoices under the order they belong to, or a
   stated argument for why three flat lists are better;
2. each row in **its own currency**, with the company-currency figure available for
   comparison and clearly marked as derived;
3. `outstanding_amount` — sent, never shown. An invoice with 12 000 outstanding and one
   with 0 look identical today. This is the delivery tab of a post-award screen; whether
   the invoice is paid is arguably the point of it;
4. `docstatus` — a **draft** or **cancelled** document is indistinguishable from a
   submitted one. Decide whether cancelled documents appear at all (the purchase chain
   filters `docstatus < 2`; the linked-row helper's filter is worth reading before you
   assume).

### S5 — after a failed load the screen tells you to pick the deal you just picked

Three regions, one `v-else`, and the wrong one wins (`:364`, `:537-538`):

```
v-if      = "deal && workspace && data"     → the workspace
v-else-if = "deal && loading"               → EmptyState, icon ti-loader, "Loading…"
v-else                                       → EmptyState, "Pick a tender deal to see its purchase orders."
```

`load()`'s `catch` fires a toast and sets `data = null; workspace = null`, then `finally`
sets `loading = false` (`:104-109`). Every condition above is now false except the last.
**So a user whose board failed to load is told to pick a tender deal — while the deal
they picked is still in the picker above the message.**

The toast is gone in four seconds. The instruction stays.

**Three states are collapsed into two empty states here:** never picked · loading ·
failed. Draw all three, plus **forbidden** — a user with read access to the board and no
write permission on the PO exists, is normal, and has no drawing anywhere in this file.

And loading is not a skeleton: it is an `EmptyState` with `icon="ti-loader"`. The board
has a known shape — four KPI cards, four lanes, an eight-column table — so it is one of
the easiest skeletons in the module to draw. Draw it.

### S6 — the two rulings this screen owes the package

**(a) Which vocabulary does `TenderDocumentsPanel` speak?** Prompt 09's S5 measured the
mirror and deferred the ruling to here. Same endpoint, same requirements, two products:

| | screen 09 · `TenderDocuments.vue` | this panel · `TenderDocumentsPanel.vue` |
|---|---|---|
| layout | a 5-column table | a card grid, `col-12 col-md-6 col-xl-4` |
| file control | two text inputs — **cannot take a file** | `FileSlot` — real upload, pick or drop |
| role | not shown at all | an icon per card **and** a role filter |
| the reasons | in `:title` attributes | rendered as text |
| scope badge | `bg-purple-lt` / `bg-secondary-lt` | `bg-purple-lt` / `bg-secondary-lt` |

**The panel is better at three of the four things screen 09 was criticised for**, and
screen 09 has the words the panel hides. Rule: one component, or two with a stated
reason. If it is one, say which layout survives and what happens to the other screen's
table. If it is two, say what makes a tab different from a page such that the same data
earns a different shape — and be prepared for that answer to apply to the whole module.

**(b) `TenderIntake.vue` — connected or removed?** ADR-304: the council said it is
*either connected or removed, but not left orphaned*. Measured: **no route**, exactly
**one** embed, at `PoControlBoard.vue:368`, on the **overview** tab of a **post-award**
screen. It is 365 lines that edit the tender's intake — the thing the drawer is the sole
writer of, per ADR-201.

So the question is sharper than "connect or remove": **should a post-award board be able
to edit intake at all?** Draw the overview tab both ways — with the intake editable, and
with it read-only beside a route to the drawer that owns it — and recommend one.

**(c) `BidPricing.vue`, bounded.** 287 lines, one call site (`:369`), no route. It turns
landed cost plus a margin into the price we bid, with its own tax-rate parameters behind
a toggle. It is not a full screen in this prompt, and one question is asked of it:
**it and the vendor comparison are two answers to "what does this cost", on the same
tab-set, computed differently.** Show them together, and say whether the user is meant
to reconcile them or whether one is derived from the other.

### An architectural problem you must show, not solve

**The hand-rolled modal is now three files.** This screen's landed editor is
`class="modal fade show d-block"` with an inline `style="background: rgba(0,0,0,.45)"`
and `tabindex="-1"` (`:541`) — no `role="dialog"`, no `aria-modal`, no
`aria-labelledby`, no focus trap, no Escape handler, no backdrop element. Screen 09 has
two of these. That is the fifth dialect, measured at **three files** and counting.

It is also `modal-xl` — **wider than any drawer the layer defines** (`ds-drawer` is 542
default, 760 at `[data-size="lg"]`). If this becomes a drawer, say what size; if it stays
a dialog, say what the layer's dialog is, because it does not have one.

**And it reopens 10.6, the unresolved z-index question.** This route can show a
`modal-xl` over a page that also hosts drawers elsewhere in the module; the two stacking
contexts were never reconciled. Note it. Do not settle it here.

## 7 · Data — use these rows, invent nothing

**The demo seed creates POs and the board has real shape.** `seed_tender_demo.py` writes
Supplier Quotations, Purchase Orders and Sales Orders tagged with `custom_crm_deal`
(`:256-275`), so unlike screen 09 this board is not empty on a seeded site.

**Lanes come from the PO's own workflow state** and nothing else (`tender.py:229-237`):

```python
if docstatus == 0:        return "draft"
if per_received >= 100:   return "completed"
if per_received > 0:      return "partial"
return "to_receive"
```

Draw the board for **`UTY-2026-4308`** · *Signal va aloqa boshqarmasi*, company currency
**UZS**:

| lane | vendor | own currency | base | charges | landed | badges |
|---|---|---|---|---|---|---|
| Draft | Alfa Kabel MChJ | 148 000 000 UZS | 148 000 000 | 0 | 148 000 000 | `draft` |
| To receive | Shenzhen Hualing Ltd | **USD 12 000** | 152 000 000 | 3 200 000 | 155 200 000 | — |
| Partially received | Uz-Tex Logistics | 96 400 000 UZS | 96 400 000 | 1 850 000 | 98 250 000 | `partial:60` · `cheapest` |
| Completed | Termiz Metall | 210 000 000 UZS | 210 000 000 | 4 100 000 | 214 100 000 | `received` · `billed` |

KPI strip from that set: **PO count 4** · **Total committed 606 400 000 UZS** ·
**Received 40 %** · **Vendors 4**.

**Four things in this data the design must not smooth over:**

1. **`cheapest` is landed-cheapest and sits on a partially-received PO.** The badge
   means *cheapest delivered cost*, not *best vendor* and not *chosen vendor* — and the
   comparison table adds `Award winner` and `Selected` as two more blue badges beside it
   (`:481-483`). Three badges, three meanings, one colour family, no shared map.
2. **The `Received 40 %` KPI is unconditionally green** (`:404` —
   `class="h3 m-0 text-green"`). At 0 % it is green. It is the only KPI with a colour and the colour
   carries no information.
3. **`partial:60` is a string the client parses** (`:138` — `b.startsWith("partial:")`,
   `b.slice(8)`). A severity encoded in a string prefix, decoded in a template helper.
4. **`min_landed` decides `cheapest` by float equality** (`tender.py:604` —
   `if landed and landed == min_landed`). Two vendors at the same landed total both get
   the badge; a vendor at landed `0` gets none. Draw the tie.

**The landed plan for the Shenzhen PO** — this is the editor's loaded state, and it is
the one that produces S1:

| type | HS code | provider | description | quoted | rate | planned (UZS) | actual |
|---|---|---|---|---|---|---|---|
| transport | — | Uz-Tex Logistics | Tashkent ← Shenzhen | **USD 1 200** | 12 800 | 15 360 000 | — |
| customs | 8544 49 | — | ГТД | — | — | 2 480 000 | PInv-2026-0412 |
| certification | — | Uzstandart | conformity | 720 000 UZS | — | 720 000 | — |
| broker | — | Sharq Broker | declarant fee | **EUR 150** | *(no rate)* | **not measurable** | — |

Four lines, two currencies, one unvalued. The footer today prints a Landed total that
includes the customs and certification lines, includes a **stale or zero** figure for the
transport line, and treats the broker line as **free**.

**Dates:** `dd.mm.yyyy` via `formatDate()`. **Money:** `MoneyInput` only, each figure in
its own currency, `moneyFractionDigits(currency)` for decimals — UZS has none and USD
has two, on the same row.

## 8 · Vocabulary

**Tabs** — **new; the layer has none.** `nav-tabs` 0, `ds-tab` 0. Name it, define its
states, and give it the keyboard model raw Bootstrap does not have.

**Lanes** — this board's four lanes are `col-md-3` cards containing cards. The kanban
vocabulary exists (`stabler-modernist.css:369-384`, settled on screen 02) and these
lanes are **not** using it. Decide whether a read-only lane is the same component as a
draggable one; the module has already ruled that **drag-to-advance is forbidden** on
read-only projections, and these lanes are read-only by design (`:5` — *"Lanes stay
read-only"*).

**Cards in a lane** — `card shadow-none border` inside `card-body p-2` inside a `card`
(`:427`): three nested card frames. Screen 01 settled the adjacent-stack rule for exactly
this shape.

**Summary values** — `ds-kpi`, `-val`, `-cap`, `-note`. The four KPI cards are
hand-built `card > card-body > .text-secondary.small.text-uppercase + .h3`, three of
them uncoloured and one unconditionally green.

**Tables** — `ds-table` inside a mandatory `table-responsive` wrapper; numeric cells
`ds-td-num`. Measured: `ds-table` **0**, `table-responsive` **1** (the comparison table,
correctly), `card-table` **1**. The comparison table is **eight columns**, five of them
numeric.

**Rows as click targets** — the comparison table's `<tr>` carries
`style="cursor: pointer"` and `@click` (`:478`) with **no** `role`, no `tabindex` and no
key handler. Screen 02 settled the accessible-row rule and screen 09 met it again; this
is the same problem without even the `role="button"` that made it visible elsewhere.
Selection is also drawn with `table-primary` — a Bootstrap row-colour class doing the
work of a selection state.

**Badges** — `ds-status` with the shared map. Nine hand-written badge sites across four
files on this route.

**Money** — `MoneyInput` for entry, `formatMoney` for display, and **a converted figure
is not the same thing as an entered one**. The editor already distinguishes them
visually (`= 15 360 000` in secondary, monospace, right-aligned); give that a name in
the layer, because S1 makes it load-bearing.

**Provenance** — this screen has three kinds and no vocabulary for any: `fx_source`
(*"from CBU · 2026-08-24"*), `rate_source` (*"from HS table · 2026-01-01"*), and
`actual_label` (a linked GL voucher). All three answer *where did this number come from*,
all three are rendered as small grey or green text with an icon, and all three are the
difference between a figure a user typed and a figure the system stands behind. Name it.

**Dialogs** — `ds-drawer` with `-backdrop`, `-head`, `-title`, `-close`, `-body`,
`-foot`; 542 default, 760 at `[data-size="lg"]`. This screen hand-rolls a `modal-xl`.

**Loading** — `SkeletonRows` mounts **in place of** a table body, never inside it.
Measured **0** here, against three spinners and one `EmptyState`-as-loader.

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Count them per region
before you draw: the editor's toolbar has *Add cost item*, each line has *fetch rate*,
*look up rates*, *pull actual*, *unlink* and *remove*, and the footer has *Cancel* and
*Save plan*.

**Forbidden here:** `class="badge bg-*"`; `spinner-border`; `EmptyState` used as a
loading state; `form-switch`; `card-table`; a `<tr>` with `@click` and no role or key
handler; `table-primary` as a selection state; a severity encoded in a string prefix;
a money figure labelled with a currency that is not its own; a total that silently
excludes a line it is displaying.

## 9 · Responsive

Draw at **1280**, **992** and **640** px.

- The **tab strip** is five two-word labels against 3.75× growth. There is no overflow
  behaviour today.
- The **KPI strip** is `col-6 col-md-3` — two-up on phones, correct.
- The **lanes** are `col-12 col-md-3`, so at 640 they become four full-width stacked
  cards. That is four headers and four card lists down a phone screen; decide whether
  that is the right answer or whether a read-only lane collapses differently.
- The **comparison table** is eight columns with a `table-responsive` wrapper — it will
  scroll, and it is the one table in this package that already does the right thing.
- The **landed editor** is the hardest surface in the module at 640: seven columns, one
  of which nests up to seven controls, plus a customs sub-row with six more. `modal-xl`
  on a 640 px viewport is a full-screen sheet by any other name. Draw it as one.

## 10 · Deliverables

1. **Both** answers to S1 — totals from `convertedPreview` vs a labelled "as saved"
   footer — each drawn at 1280, and a recommendation.
2. **The not-measurable landed total**: the footer with one unvalued line, what it says
   instead of a number, what it says about how many lines it excludes, and the state of
   *Save plan*.
3. **The lane card's two currencies**: the `USD 12 000 → 155 200 000 UZS landed` problem
   drawn, named, and answered.
4. **S2's validation**: the unsaveable plan drawn twice — the missing rate, and the
   customs line carrying a hidden currency — with the reason beside the line, and a
   stated answer for what a type change does to fields the new type cannot hold.
5. **The tab component** for the layer: anatomy, states, keyboard model, `aria`
   contract, and the 640 px answer. Plus **both tab strips** — four tabs and five —
   showing that finance is absent rather than disabled.
6. **A stated answer to "one screen or five"**, with the loading behaviour that follows
   from it.
7. **S4: the chain as a chain**, with each row in its own currency, `outstanding_amount`
   visible, and a decision about draft and cancelled documents.
8. **All five states for the board**, including the **error** state that currently
   renders as "Pick a tender deal", the **forbidden** state for read-without-write that
   has no drawing anywhere, and a **skeleton** for a board whose shape is known.
9. **The editor at 640** as a full-screen sheet.
10. **The badges redrawn from one vocabulary** — `cheapest`, `draft`, `delayed`,
    `received`, `partial:NN`, `billed`, `Cheapest (landed)`, `Award winner`, `Selected`
    — with the three that share a blue family separated by meaning, and the `partial`
    severity carried by something other than a string prefix.
11. **The `Received` KPI with a colour that means something**, or no colour.
12. **A named vocabulary for provenance** — `fx_source`, `rate_source`, `actual_label` —
    one form, three uses.
13. **S6(a)**: the ruling on `TenderDocumentsPanel` vs screen 09, with both layouts side
    by side and the losing one marked "not chosen".
14. **S6(b)**: the overview tab drawn twice — intake editable, and intake read-only
    beside a route to the drawer that owns it — and a recommendation on ADR-304.
15. **S6(c)**: `BidPricing` and the vendor comparison shown together, with a stated
    answer to whether the user reconciles them.
16. The `modal-xl` resolved into the layer, or a stated argument for keeping a dialog
    the layer does not define — including its width.
17. Every question your design raised, listed — including the **z-index** (10.6) and
    anything S6 could not settle.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `PoControlBoard.vue`, `TenderWorkspaceTabs.vue`,
`TenderDocumentChain.vue`, `TenderDocumentsPanel.vue`, `stabler/api/tender.py` and
`stabler/stabler/tender_landed_math.py` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | **The editor's totals and its lines agree.** No expression sums `l.amount` while the same line renders `convertedPreview(l)`; whichever field wins, one field feeds both | 2 fields | 1 |
| K2 | **A total containing an unvalued line is not a number.** `convertedPreview` returns `null` by design; a `null` inside a total makes the total not-measurable, never smaller | silently 0 | asserted |
| K3 | **Save is refused in the browser for both conditions the server refuses.** Currency with `fx_rate <= 0`, and `type === "customs"` with a currency — `tender.py:485-496` | 0 / 2 | 2 / 2 |
| K4 | **No refusal names a field the user cannot see.** A customs line cannot hold a currency the currency select is hidden for | 1 | 0 |
| K5 | **The tab strip is a tablist.** `role="tablist"`, `role="tab"`, `aria-selected` and a roving tabindex; measured `aria-` on the strip today is **1**, an `aria-label` | 1 | asserted |
| K6 | **One source of truth for the active tab.** The strip is told, not told-and-also-computing; no `\|\|` between two active checks | 2 | 1 |
| K7 | **No money figure is labelled with a currency that is not its own.** `TenderDocumentChain.vue:40` renders `grand_total` with the prop currency while `row.currency` is sent and unused | 1 site | 0 |
| K8 | **The chain renders the link it keys on.** `purchase_order` / `sales_order` appear in the output, not only in `:key` | key only | rendered |
| K9 | **A failed load is a state, not the empty state.** After `catch`, the screen does not render "Pick a tender deal" while a deal is picked | 1 | 0 |
| K10 | **Loading is a skeleton.** Three `spinner-border` and one `EmptyState` with `icon="ti-loader"` | 3 / 1 | 0 / 0 |
| K11 | **No page-local colour map.** `badgeMeta()` has six entries plus a prefix parser; five more badges are hand-written across the route; zero imports of the shared map | 11 / 0 | 0 / 1 |
| K12 | **Severity is not encoded in a string prefix.** `partial:60` is parsed with `startsWith` and `slice(8)` | 1 | 0 |
| K13 | **The `Received` KPI's colour is conditional or absent.** `text-green` is unconditional today (`:404`) | unconditional | asserted |
| K14 | **No `<tr>` is a click target without a role and a key handler**, and selection is not drawn with `table-primary` | 1 / 1 | 0 / 0 |
| K15 | **The dialog is the layer's, or the argument for keeping it is written down.** A hand-rolled `modal-xl` with no `role="dialog"`, no `aria-modal`, no focus trap — the third such file in the package | 3 files | decided |
| K16 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once — including the three that collapse into two empty states today | 0 | = region count |
| K17 | **The forbidden state exists.** Read-on-board without `Purchase Order` write permission is drawn | 0 | 1 |
| K18 | **Regression guards — these are already right and must stay so.** Policy numbers interpolated from `tenderPolicy` and never literal (`:377-378`); `openPo` routing inside the SPA rather than to Desk (`:143`); the lane card's own-currency figure (`:433`); the comparison table's `table-responsive` wrapper (`:463`); the finance tab absent rather than disabled when the server omits the key; `MoneyInput` at 7 sites and `DateInput` at 3; and the editor's per-line `null` on an unusable rate (`:227-233`) — **do not "fix" that into a zero** | asserted | unchanged |

**K18 is the one a redesign is most likely to lose**, and its last item is the
load-bearing one: `convertedPreview` returning `null` is not a bug to tidy away. It is
the module's written rule, it is the only place in this file that obeys it, and S1 is
the story of what happened to the total that ignored it.

**K1–K4 are money criteria.** State plainly whether your design satisfies them. A
landed-cost editor that looks better and still adds an unvalued line as zero has made
the screen worse, because it will be believed.

State plainly which of these your design satisfies, and name anything it cannot.
