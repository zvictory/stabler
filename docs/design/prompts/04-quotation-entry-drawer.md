# 04 · Quotation entry drawer

**Source:** `stabler/public/js/components/QuotationEntryDrawer.vue` — 416 lines,
**31 `ds-*`, 0 `tgm-*`, 0 bare Bootstrap buttons, 0 badges, 0 spinners, 0
`form-switch`**.

**Why fourth, and why it reads differently from 01–03.** The first three screens were
drawn to find what was wrong. **This one is mostly right**, and the job is the other
way round: name precisely what makes it the reference so the remaining fourteen
screens can copy it — and then fix the four things it still gets wrong, **two of which
fail silently**.

Its own scoped-style comment is the sentence the whole migration is trying to say:

> *"Yalnız yerleşim. Renk, kenar, tipografi katmandan (`.ds-*`)."*
> — layout only; colour, border and typography come from the layer.

**It also settles an open question by existing.** Screen 02 decided the intake drawer
should take `ds-drawer[data-size="lg"]` (760 px) because of its line table. This drawer
carries a line table and **already declares exactly that** (`:225`). The decision was
not a new value; it was catching up with this file.

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

This drawer opens from the **sourcing** workspace (screen 03) and writes a supplier
quotation. It is a component, not a route — it has **no gate of its own** and inherits
whatever the screen that mounted it allows. Say what that means for the forbidden
state.

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

**Mandates 3 and 9 are the two this drawer breaks.** Everything else it already keeps.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.**
- **A disabled control carries its reason beside it.** This drawer **already does
  this**, for its primary, better than any other file in the module — and then does
  **not** do it for its second button. See §6.
- **The procurement policy numbers are server values** and never literal digits.
- **No fixed-width label, badge or nav item.** Worst-case interface-language growth is
  **3.75×**.
- **String interpolation exists; plurals do not.**
- **The currency is the company's home currency, read from the server, never a
  literal.** Mikas's is UZS; another tenant's is its own. Settled 2026-09-01 as the
  third documented exception in `.claude/rules/10-frontend.md` — and **this drawer is
  where a non-home currency enters the product at all**. See S3(b).
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

**Measured: `v-if="loading"` = 0.** This drawer has no loading state at all. It opens
empty and fills in when the call returns.

## 6 · The screen

**Quotation entry drawer.** Its one job: record what one supplier quoted against one
lot, as a draft, and then submit it.

`ds-drawer[data-size="lg"]` (760 px), `role="dialog"`, `aria-modal="true"`,
`aria-labelledby` — with a `ds-drawer-backdrop`. Three fields and a line table:

| field | control | note |
|---|---|---|
| Supplier | `Typeahead`, placeholder ends `⌘K` | |
| Currency | `Select` | populated from `stabler.api.sales.list_currencies` |
| Valid till | `DateInput` with `:min` | the minimum is the **transaction date** |
| lines | `ds-table`: item · qty · rate · total · remove | |

Footer: **`Save draft` (the one primary)** · `Submit quotation` · `Close` · and a
monospace source stamp reading `supplier_quotation · {name or "new"}`.

### What it already gets right — name each one, because the others must copy it

1. **The blocked primary explains itself.** A `problems` computed list
   (`:159-171`) holds up to **six** named reasons — no supplier, no currency, valid-till
   before transaction date, no lines, quantity not above zero, negative rate — and the
   template renders them as a `<ul role="alert">` (`:315`). The primary is disabled
   *from that list*. Screen 03's primary has four reasons and shows none; this one is
   the pattern screen 03 should have had.
2. **Waiting is a label swap.** `saving ? "Saving…" : "Save draft"` and
   `submitting ? "Submitting…" : "Submit quotation"`. **No spinner anywhere.**
3. **Money goes through `MoneyInput`** — `hide-currency` on quantity,
   `:currency="form.currency"` and `:max-fraction-digits="4"` on rate.
4. **The icon-only control has a name**: `:aria-label="t('Remove line')"`.
5. **Layout is local; everything else is the layer.** The scoped stylesheet declares
   padding, flex and gaps — and says so in its first comment.

### S3 — the question this screen exists to answer

**What does a drawer show when the record it was opened for did not load?**

Measured, `:65-90`. The drawer is opened to edit `SQ-2026-0342`. The call throws.
What happens:

- a **toast** fires and disappears;
- `form.name` is **never assigned**, so it stays `""`;
- every field stays at its blank default and the line table shows one empty row;
- the drawer now looks **exactly like a new quotation**, with no indication that
  anything failed;
- `Save draft` therefore **creates a second quotation** rather than updating the one
  the user opened;
- and the **only** trace on screen is the word `new` inside a monospace string in the
  footer's bottom corner.

Worse, there is a quieter path: the code guards `if (res)`. If the call **succeeds and
returns nothing**, there is no toast at all — the same blank form, with no signal
whatsoever.

`Submit quotation` happens to stay disabled (it is gated on `!form.name`), which
limits the damage by accident and explains none of it — its only reason is a
`:title` attribute, which a touch user never sees.

**Draw at least two ways to resolve this, with trade-offs, and recommend one.** The
obvious pair: (i) the drawer refuses to be a form — it shows the error state in place
of the fields, with the raw message and a "Try again"; (ii) the drawer stays a form
but is visibly and unmistakably a **new** one, and the failed record is named. There
may be a better third. **"Show a better toast" is not an answer** — a toast has already
gone by the time the user reaches Save.

### S3(b) — the currency list has a silent single-currency fallback

`:119-129`. The list comes from `list_currencies`. If that call fails, the `catch`
sets the list to **the company currency alone** and the user gets a dropdown with one
option and no indication that anything went wrong.

That matters more than it looks. **This drawer is the only place a non-home currency
enters the product.** The third documented currency exception — adopted 2026-09-01,
the whole reason screen 03's comparison table may convert at all — is dead letter if
every quotation can only ever be entered in the home currency. Draw what a degraded
currency list looks like when the user can see it.

### An architectural problem you must show, not solve

The drawer has **no gate of its own**. It is mounted by the sourcing workspace, which
is itself behind a bare `v-if="canSourcingView"`. So the drawer's forbidden state is
whatever its host decides, and if the host ever mounts it without checking, nothing in
this component says no. The server does — `api/sourcing.py` applies the same rules and
the component's own comment says so — but the UI has no answer. Draw the question.

## 7 · Data — use these rows, invent nothing

The drawer edits one quotation at a time. Use **`SQ-2026-0342`** against lot
`UTY-2026-4308`, generated by `stabler/maintenance/seed_tender_demo.py`:

| field | value |
|---|---|
| supplier | **Hebei Rail Parts** |
| country | China |
| lot | `UTY-2026-4308` · Signal va aloqa boshqarmasi |
| transaction date | **7 days ago** (`min(deadline − 7, today)`, and this lot's deadline is today) |
| valid till | **deadline + 30 days** |
| status | **Draft** — the seed inserts quotations and never submits them |
| lines | **one** |
| line | item `UTY-2026-4308 (demo)` · qty **1** · rate **874 000 000** |

### Three things in this data the design must not smooth over

1. **The whole bid is one line, at quantity 1.** The seed writes the lot's entire value
   into a single line's *rate* (`round(value × (0.92 + i × 0.03))`, `:376`). So the
   **per-unit price column holds a nine-digit number**, the quantity column always
   reads `1`, and the line total repeats the rate. A rate field carrying
   `:max-fraction-digits="4"` on 874 000 000 is four decimal places on a number that
   has none. Draw it as it is, and say what the column is for.
2. **`transaction_date` is loaded, governs a validation message, and has no field.**
   It is read from the server (`:78`), used to compute the `Valid till` minimum
   (`:113-114`), and is **not in the template and not in the save payload**. So the
   error *"Valid till date cannot be before transaction date"* points at a value that
   is **nowhere on screen**. Fix that without inventing a backend field — the value is
   already there.
3. **Every demo quotation is in the same currency.** The seed sets none per quotation,
   so the site default applies to all of them. The currency `Select` is therefore
   always showing the one value that makes the third exception do nothing.

**Currency:** never hard-code a symbol. Decimals come from
`moneyFractionDigits(currency)`.

## 8 · Vocabulary

**Drawer** — `ds-drawer[data-size="lg"]` (760 px) with `-backdrop`, `-head`, `-title`,
`-kicker`, `-close`, `-body`, `-foot`. 542 px is the default for drawers **without** a
line table. Settled on screen 02.

**Sections** — `ds-form-section`, **adjacent stack**: flush inside one bordered card,
divided by their own heads, no nested card frames. Settled on screen 01.

**Files** — `ds-file-list[data-mode="edit"|"read"]` with `-row`, `-name`, `-meta`.
Settled on screen 01 as D14.

**Tables** — `ds-table`, and a `table-responsive` wrapper is **mandatory**. Numeric
cells are `ds-td-num`. **Measured here: `ds-table` 1, `table-responsive` 0.**

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it;
its own root is a `<tbody>`.

**Status** — `ds-chip[data-tone]` through the shared status map. This drawer writes a
`Draft` and can submit it; drawing that status is new work here.

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Waiting is a **label
swap** plus `aria-busy="true"` plus `disabled` — **this drawer already does the label
swap and does not set `aria-busy`.** A disabled control carries its reason **beside
it**, not in a `title`.

**Forbidden here:** `class="badge bg-*"`; `spinner-border`; `form-switch`; `btn-xs`;
`card-table`; `ds-table-wrap`; **`toLocaleString()` on money** — see K3.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. Measured: below **640 px** the layer
collapses `ds-drawer`, `[data-size="lg"]` and `[data-size="sm"]` all to `100vw` with
no left border (`stabler-modernist.css:699-701`), and `ds-form-grid[data-cols="2"|"3"]`
to a single column. **A five-column line table inside a full-width phone drawer is the
problem on this screen** — solve it explicitly. Nothing may scroll the page
horizontally.

## 10 · Deliverables

1. The drawer at 1280 / 992 / 640, loaded, editing `SQ-2026-0342`.
2. All five states — including the **loading** state the drawer does not have and the
   **forbidden** state it cannot express.
3. **Both** answers to S3, each drawn, with trade-offs and a recommendation.
4. S3(b): a degraded currency list the user can see.
5. The `problems` list drawn as the reference pattern, with **all six** reasons, and
   `Submit quotation`'s reason moved out of its `title` into the same pattern.
6. The `transaction_date` value made visible without inventing a field.
7. The line table with the real data — one line, quantity 1, a nine-digit rate — and a
   stated answer for what the quantity column is for.
8. The five-column line table at 640 px.
9. Every question your design raised, listed.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `QuotationEntryDrawer.vue` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | The `ds-table` sits inside a `table-responsive` wrapper | 1 / 0 | 1 / 1 |
| K2 | **A failed load is a state, not a toast.** The template has an error branch for `quotationName`, and no path renders editable fields for a record that did not load | 0 branches | asserted |
| K3 | **No money rendered by `toLocaleString()`.** Two live sites — the line total (`:301`) and the grand total (`:312`) — both bypass `MoneyInput` and `moneyFractionDigits`, and both use the browser's default locale rather than `user.language` | 2 | 0 |
| K4 | `transaction_date` is rendered somewhere the user can see it, since a validation message already names it | 0 | 1 |
| K5 | Every disabled control's reason is in the `problems` list, not in a `title`. `Submit quotation` is the live case (`:334`) | 1 title | 0 |
| K6 | Busy controls carry `aria-busy="true"`. The label swap is already right; the attribute is missing | 0 | 2 |
| K7 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K8 | The currency list's failure is visible: the `catch` at `:123` does not silently produce a one-option select | silent | asserted |
| K9 | **Regression guards — these are already right and must stay so.** Zero `spinner-border`, zero `badge`, zero `form-switch`, zero bare `btn-*`, and the `problems` list keeps its `role="alert"` | 0/0/0/0/1 | unchanged |
| K10 | The drawer keeps `data-size="lg"`. This file is the reference that settled the width; a regression here silently re-opens screen 02's S1(a) | 1 | 1 |

**K9 and K10 exist because this file is the reference.** A reference that regresses
takes the copies with it — and unlike the other screens, everything it is asked to
keep is something it already does.

State plainly which of these your design satisfies, and name anything it cannot.
