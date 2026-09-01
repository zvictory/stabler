# 06 · New RFQ

**Source:** `stabler/public/js/pages/tender/rfq/RfqForm.vue` — 384 lines,
**0 `ds-*`, 0 `tgm-*`, 1 badge, 1 spinner, 8 bare `btn-*`, 0 `ListToolbar`**.

**Read the measurement wrong and you will redesign the wrong file.** Its zero `ds-*`
does not mean it is outside the layer — it renders inside `<TenderPage>`
(`TenderPage.vue:12`, `.stbl-ds`), and the layer's 344 compatibility rules already
restyle every `.btn`, `.card`, `.form-control` and `.table` on the page. **This is the
best-composed form in the tender module** and it looks unmigrated only in a grep.

It already uses `MoneyInput`, `DateInput`, `Typeahead` ×3 with `⌘K`, `SkeletonRows`,
`EmptyState`, a **shared reach calculation** with its own spec, server policy numbers
with no literals anywhere, and correct `{count}` interpolation. Screen 04 was the
reference for drawers; **this is the reference for forms**.

So the job is the same as 04's: name what makes it the reference, then fix the four
things it gets wrong — **one of which throws away the only human-readable name the
user ever sees.**

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

A **sourcing** screen, and the only one in the family that **writes**. Note what that
means for the forbidden state: the four `Typeahead` searches hit four different
endpoints (`crm.list_deals`, `purchasing.list_suppliers`, `inventory.list_items`,
`sourcing.get_deal_rfq_defaults`), each with its own permission. A user can be allowed
to open this form and refused by any one of them, mid-typing.

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
   button; the search placeholder ends with `⌘K`. *(Not a list screen — but the three
   `Typeahead` placeholders end with `⌘K` and should stay that way.)*
9. Loading is a skeleton, never a bare spinner.

**Mandate 9 is the only one this form breaks**, once: `spinner-border` inside the
Create button (`:375`). Its table loading is already a skeleton (`:317`). Mandate 3 it
keeps — and then applies `MoneyInput` to a **quantity**; see §6.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** This form has
  two warnings drawn as `text-warning` + an icon (`:275`, `:284`). **Colour and shape,
  no word.**
- **A disabled control carries its reason beside it.** `canCreate` is four conditions
  ANDed on one line (`:156-158`) and the disabled primary says nothing about which one
  failed. Screen 04 solved this three files away with a named `problems` list rendered
  as `<ul role="alert">`. **The module contains both patterns.**
- **The procurement policy numbers are server values** and never literal digits. This
  form is **exemplary** here: `policy` is zeroed until the server answers, with a
  source comment explaining that the badge must stay quiet rather than announce a
  policy it has not been told (`:39-42`).
- **No fixed-width label, badge or nav item.** Worst-case growth **3.75×**.
- **String interpolation exists; plurals do not.** This form is where that costs the
  most — see S2.
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
**No CSS may bind to that attribute. Measured here: 0.**

**The `catch` in `loadDefaults` (`:126-129`) is deliberately non-blocking and it is
right.** It toasts, drops in one blank line, and lets the officer keep working — the
lot's items are a convenience, not the record. Do not "fix" it into a blocking error.
**The `catch` in `create` (`:186`) is a different animal**: it toasts and leaves the
form exactly as it was, with no record and no trace. Draw the distinction.

## 6 · The screen

**New request for quotation.** A full page, not the old workspace modal. Three
sections stacked as separate cards: the lot and response date · the suppliers to ask ·
the requested items, with the create action in the last card's footer.

Its item lines arrive **pre-filled from the tender intake** — a lot that reached
sourcing was already specified line by line, and this form's job is to ask suppliers
for exactly that list.

### What it already gets right — name each one, because the others must copy it

1. **`MoneyInput` and `DateInput`**, never a raw `<input type="number">` for money or
   a raw date field.
2. **`Typeahead` for all three lookups**, each with a `⌘K` placeholder, each searching
   the server rather than filtering a preloaded list.
3. **`SkeletonRows`** for the line table while defaults load (`:317`).
4. **Server policy, zeroed until it arrives**, with the reasoning in a comment.
5. **A shared reach calculation** — `reachOf` (`composables/sourcingReach.js`), the
   deliberate client twin of `_sourcing_reach.py`, pinned by its own spec, with the
   drift risk written down in its header.
6. **Correct `{count}` interpolation**, not string concatenation.
7. **The direct-URL path treated as primary**, not as a corner case (`:194-196`).
8. **A footer sentence that tells the truth about what the product does**:
   *"Stabler creates the draft; sharing it with suppliers stays your act."*

### S1 — the question this screen exists to answer

**The supplier chips show the database id, not the supplier's name.**

`searchSuppliers` returns `{name, label, country}` where `label` is
`supplier_name || name` (`:66-70`). `pickSupplier` keeps the **country** beside the
list — with a comment explaining exactly why it is kept apart — and pushes only
`o.name` into `suppliers` (`:88-89`). The chip then renders `{{ sup }}` (`:243-244`).

So after picking **Hebei Rail Parts** from a list that showed you *Hebei Rail Parts*,
the chip reads **`SUP-00042`**. The country was worth keeping; the name was not.

This is not a styling problem and you cannot draw your way around it: the officer is
choosing **who to ask**, and after choosing, the screen stops naming them. Draw the
chip set as it must be, and say what the chip carries — name, country, and what
happens when the country is blank, which is the fact the next two warnings depend on.

**The chip itself is a fourth chip vocabulary in the module** (`badge bg-primary-lt`
with a nested `btn-close` at `font-size: 10px`, `:243-250`). Screen 01 settled the
file-chip question as **D14**; the layer has `ds-chip`. The remove control has **no
accessible name at all** — it is a bare `<button class="btn-close">` with no text and
no label, so a screen reader announces "button". Give it one.

### S2 — plurals do not exist, and this screen has four of them

```
"Asking {count} vendor(s) from {countries} country(ies)."
"The policy wants {min} quotations from {countries} countries."
"This invitation reaches {countries} country(ies). …"
"{count} of the vendors has no country on file, …"
```

`vendor(s)` and `country(ies)` are the workaround for a plural system that does not
exist. Four things follow, and all four are visible:

1. **English reads as a form, not a sentence.** `Asking 1 vendor(s) from 1
   country(ies).`
2. **Russian has three plural forms.** `(s)` maps to none of them; the parenthesis is
   not a Russian construction at all.
3. **Uzbek does not mark the plural after a numeral** — `5 ta yetkazib beruvchi`, not
   a pluralised noun. So the `(s)` is wrong in the opposite direction.
4. `"{count} of the vendors **has** no country"` — the verb is singular in a sentence
   whose subject is a count that is usually plural.

You cannot add a plural system; that is a backend and i18n change, and this prompt
forbids inventing one. **Design the sentences so they do not need one** — a count and
a noun as separate elements, a label-and-value pair, a meter with its own caption.
This is a real constraint that shapes layout, not a translation footnote.

### S3 — the policy guidance is invisible on a real path

Everything from `:260` to `:294` — the reach line and both warnings — is inside
`v-if="policy.min_suppliers"`. `policy` starts `{min_suppliers: 0, min_countries: 0}`
and is only filled by `loadDefaults()`, which only runs when a **lot is picked**.

The form's own empty state invites the other path:

> *"Pick a tender lot to load its items, **or add lines by hand**."* (`:359`)

On that path `policy.min_suppliers` is `0`, so:

- the reach line does not render,
- neither warning renders,
- **you can create an RFQ asking one supplier in one country and never be told the
  policy exists.**

The zeroing is deliberate and defensible — the comment argues the badge should stay
quiet rather than announce a policy it has not been told. **The consequence was not
intended.** Draw both readings:

- **(a)** the guidance stays lot-dependent, and the by-hand path says plainly that the
  policy cannot be checked yet — the **fifth state**, not silence;
- **(b)** the policy is session-level (the list screen already reads
  `tenderPolicy.minQuotations` from the store without any lot), so the guidance can
  render from the first supplier.

Trade-offs and a recommendation.

### An architectural problem you must show, not solve

**`reachOf` computes `meets_suppliers` and nothing renders it.** Line 39 of
`sourcingReach.js` returns it; the template uses `reach.suppliers`,
`reach.countries`, `reach.unknown_country` and `reach.meets_countries` — never
`meets_suppliers`. So the country rule gets a warning and the **supplier-count rule
does not**, though both are policy and both are computed.

Draw what the missing warning would say. Do not change the composable.

## 7 · Data — use these rows, invent nothing

Build the RFQ for lot **`UTY-2026-4308`** · *Signal va aloqa boshqarmasi* — a
`sourcing`-stage lot, 19 days in step against a 14-day threshold, value
**920 000 000**, from `seed_tender_demo.py:64-84`.

**Suppliers picked** (from `DEMO_SUPPLIERS`, `:193-198`):

| supplier | country | chip shows today |
|---|---|---|
| Hebei Rail Parts | China | `SUP-00042` |
| Shandong Heavy | China | `SUP-00043` |
| Temiryo'l ta'minot | **blank** | `SUP-00031` |

That third row is the one the design has to earn: `reachOf` counts a blank country as
**no country** (`sourcingReach.js:25`, "a blank country is not a country"), so this
selection reaches **2 suppliers in 1 country with 1 unknown** — which trips
`!reach.meets_countries` **and** `unknown_country`, both warnings at once, stacked as
two `text-warning` lines with two different icons.

**Policy:** `min_suppliers = 5`, `min_countries = 2`, arriving from
`get_deal_rfq_defaults`. **Never render either as a literal digit.**

**Lines**, pre-filled from the lot's intake — one line, the lot's whole value in the
rate, quantity 1 (the seed's shape, `:376`):

| item | qty | UOM | target rate |
|---|---|---|---|
| `UTY-2026-4308 (demo)` | 1 | *(blank)* | 920 000 000 |

**Three things in this data the design must not smooth over:**

1. **`Qty` is a `MoneyInput`** (`:337`, with `hide-currency` and `:min="1"`). A money
   control rendering a count: grouped thousands, a decimal separator chosen by
   currency rules, and `moneyFractionDigits` deciding how many decimals a *quantity*
   has. It is the right component for the wrong quantity — say what the column needs.
2. **`UOM` is a bare `<input type="text">`** (`:340`) — free text, no list, no
   validation, in a field the print letter hands to a supplier as the unit they must
   quote against. The seeded row leaves it **blank**.
3. **`Target rate` is a read-only cell inside an editable table** (`:342-344`) — same
   column rhythm, same right-alignment, and it cannot be typed in. It is also the
   buyer's internal number, deliberately never sent to suppliers. Two facts about one
   column, neither of them visible in it.

**Currency:** `currency.value` arrives from the server and is passed to `formatMoney`
correctly here (`:164`). Never hard-code a symbol; decimals come from
`moneyFractionDigits(currency)`.

## 8 · Vocabulary

**Sections** — `ds-form-section`, **adjacent stack**: flush inside one bordered card,
divided by their own heads, no nested card frames. Settled on screen 01. **Measured
here: three separate `.card`s stacked with `mb-3`** — the pattern screen 01 replaced.

**Fields** — `ds-field`, `-label`, `-hint`, `-err`, `-req`. The required marker is
currently `<span class="text-danger">*</span>` at three sites (`:211`, `:240`,
`:299`) — a colour-only required indicator with no accessible text.

**Chips** — `ds-chip[data-tone]`. See S1: the supplier chips are a fourth vocabulary.

**Tables** — `ds-table` inside a mandatory `table-responsive` wrapper; numeric cells
`ds-td-num`. **Measured: `ds-table` 0, `table-responsive` 1, `card-table` 1.**

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it.
**Already correct.**

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Waiting is a **label
swap** plus `aria-busy="true"` plus `disabled` — **never a spinner inside the button**
(`:375` is the one live spinner in this file). A disabled control carries its reason
**beside it**: `canCreate`'s four conditions must become four named reasons, following
`QuotationEntryDrawer.vue`'s `problems` list.

**Severity** — `ds-sev`. The two warnings are `text-warning` + icon: colour and shape,
no word.

**Forbidden here:** `spinner-border`; `class="badge bg-*"`; `btn-close` as an unlabelled
control; `card-table`; a colour-only required marker.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. Measured: the layer collapses
`ds-form-grid[data-cols="2"|"3"]` to a single column below 640
(`stabler-modernist.css:699-704`). The current grid is Bootstrap's
`col-md-6 / col-md-3 / col-md-3`, which collapses at **768**, not 640 — two different
breakpoints on one page.

The five-column line table (item · qty · UOM · target rate · remove) on a 640 px phone
is the problem on this screen. The `Typeahead` dropdown inside a horizontally
scrolling table is the second one. Nothing may scroll the page horizontally.

## 10 · Deliverables

1. The form at 1280 / 992 / 640, loaded, building the RFQ above.
2. All five states — including the **forbidden** state that can arrive from any of
   four endpoints mid-typing, and the **not measurable** state for policy on the
   by-hand path.
3. The supplier chips per S1 — showing names, carrying country, with a labelled remove
   control — and a stated answer for the blank-country chip.
4. The four plural strings redesigned per S2 so they need no plural system, drawn in
   **English and Uzbek** side by side.
5. **Both** answers to S3, each drawn, with trade-offs and a recommendation.
6. The missing `meets_suppliers` warning drawn.
7. `canCreate`'s four conditions as a named `problems` list, following screen 04.
8. The line table with the real row — quantity 1, a nine-digit target rate, a blank
   UOM — and a stated answer for what the Qty control should be.
9. The line table at 640 px with a `Typeahead` open in it.
10. Every question your design raised, listed.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `RfqForm.vue` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | **The supplier chip renders a name, not an id.** `pickSupplier` keeps `o.label` the way it already keeps `o.country` | id | name |
| K2 | **The chip's remove control has an accessible name.** `btn-close` at `:247` has no text and no label | 0 | 1 |
| K3 | **No spinner.** The one `spinner-border` (`:375`) becomes a label swap plus `aria-busy="true"` | 1 / 0 | 0 / 1 |
| K4 | **Every disabled reason is named.** `canCreate`'s four ANDed conditions (`:156-158`) render as a `problems` list with `role="alert"`, as in `QuotationEntryDrawer.vue` | 0 | 4 |
| K5 | **No `(s)` or `(ies)` plural workaround** in any user-facing string | 4 | 0 |
| K6 | **Policy guidance is never silent.** With `policy.min_suppliers == 0` the screen says the policy cannot be checked yet; it does not render nothing | silent | asserted |
| K7 | `reach.meets_suppliers` is rendered somewhere, since it is already computed | 0 | 1 |
| K8 | Every warning carries colour **and** shape **and** a word; `text-warning` alone is gone | 2 colour-only | 0 |
| K9 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K10 | **Regression guards — these are already right and must stay so.** `MoneyInput` and `DateInput` imported and used, three `Typeahead` placeholders ending `⌘K`, `SkeletonRows` present, `reachOf` imported from the shared composable rather than re-derived, `policy` zeroed until the server answers, zero literal `5` or `2` in the template, and the footer sentence kept verbatim | asserted | unchanged |

**K10's last item is not decoration.** *"Stabler creates the draft; sharing it with
suppliers stays your act"* is the sentence that keeps the next screen honest: nothing
in this product emails a supplier, and screen 07's `Mark as sent` records a human act
rather than performing one.

State plainly which of these your design satisfies, and name anything it cannot.
