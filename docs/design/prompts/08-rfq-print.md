# 08 · RFQ print letter

**Source:** `stabler/public/js/pages/tender/rfq/RfqPrint.vue` — 282 lines,
**0 `ds-*`, 0 `tgm-*`, 0 badges, 1 spinner, 4 bare `btn-*`, 0 `table-responsive`**.

**This is the only screen in the family whose zero `ds-*` means what it says.** The
other three render inside `<TenderPage>` and inherit `.stbl-ds`; this one's root is
`<div class="print-wrapper">` with no shell, no nav, no layer (`:50`). The Design
Council already required it: **`RfqPrint.vue` and `BidPricing.vue` must gain a
`.stbl-ds` ancestor. Both measure 0 today.**

**And it is the only screen in the package that is not a screen.** It is a letter — an
A4 page handed to a supplier. That difference is the whole prompt, because:

> **The design layer has never been asked to print. `stabler-modernist.css` contains
> zero `@media print` rules.**

So this file invented a **fourth dialect** — `rfq-*`, 20 classes, its own type ramp in
points and its own greys — because there was nothing to inherit. Deciding what a
Stabler document looks like on paper is new work, and it is the work of this screen.

---

<!-- ═══════════ PASTE BELOW THIS LINE ═══════════ -->

You are designing **one printed document** of an existing product. Do not invent a
design system. Do not write code. The deliverable is design: artboards, states, and a
written rationale for each decision you make.

## 1 · The product

**Mikas Tender** is the tender module of **Stabler**, a Vue 3 SPA used by an Uzbek
trading company. It follows a public tender from the moment a state buyer publishes
it, through pricing, bidding, award, purchase orders, customs clearance and delivery.

The SPA is built on **Tabler**, with a house layer called **`stbl-ds`** on top. That
layer already exists and is not up for redesign — you extend it, you do not replace
it. There is **no dark mode**; do not invent one. **On paper there is no mode at all**
— see §6.

## 2 · The four roles

Gated server-side. The gate sits **at the endpoint, not in the navigation**.

| view | roles |
|---|---|
| `director` | System Manager · Stabler Admin · Sales Manager · Stabler Tender Director |
| `sourcing` | System Manager · Stabler Admin · Sales Manager · Sales User · Stabler Tender Sourcing |
| `declarant` | System Manager · Stabler Admin · Sales Manager · Stabler Declarant · Stabler Tender Declarant |
| `logist` | System Manager · Stabler Admin · Sales Manager · Stabler Logist · Stabler Tender Logistics |

A **sourcing** screen. But this is the only artefact in the module that **leaves the
company**: the reader of the printed page is a supplier with no role, no login and no
way to ask what a symbol means. Every convention the other seventeen screens rely on —
hover, tooltip, badge colour, a shared status vocabulary learned over time — is
unavailable to them. Say what that removes.

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
8. List screens use the shared `ListToolbar`. *(Not a list screen.)*
9. Loading is a skeleton, never a bare spinner.

**Three of these mean something different on paper, and you must say which and why:**

- **Mandate 2** — the file hand-stripes with `rfq-row--alt` (`:106`, `:249-251`). On
  screen that is forbidden; on a page that will be photocopied and faxed, a 4 % grey
  may be the only thing holding the row alignment together. Decide, and argue it.
- **Mandate 3** — **this document renders no money at all**, deliberately. See §6.
- **Mandate 9** — the loading spinner (`:61`) is on a surface that is never printed.

Mandate 1 applies unchanged and absolutely: a letter to a supplier can carry no
internal URL of any kind.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** On a
  monochrome laser printer, **colour is gone**. Whatever survives must survive without
  it.
- **No fixed-width label.** Worst-case growth **3.75×**. On a fixed A4 page this is the
  hardest constraint in the package: `Supplier signature / stamp` sits under a 60 mm
  rule (`:277-281`) and the page cannot grow sideways.
- **String interpolation exists; plurals do not.**
- **The procurement policy numbers are server values** and never literal digits. **This
  document must show none of them** — the policy is a buyer's internal rule.
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

**States on this screen split in two, and the split is the interesting part.** The
loading, error and forbidden states belong to the **screen** — they are chrome, and
`@media print` hides everything but `.a4-print` anyway, so a user who prints during a
failure gets a **blank sheet**. The empty and not-measurable states belong to the
**document**: an RFQ with no lines still prints, and what it says on paper when the
table is empty is a real design question with a supplier on the other end.

Draw both sets, and say which is which.

**There is no empty state at all today.** `doc.items` renders through `v-for` with no
fallback (`:106`); an RFQ with no lines prints a table with a header row and nothing
under it, above a signature block asking the supplier to quote for it.

## 6 · The screen

**The letter a supplier is handed.** Company block · rule · title · lead paragraph ·
response-by date · item table · closing instruction · two signature lines. A4 portrait,
186 mm wide, 250 mm minimum height, 15 mm margins, rendered WYSIWYG on screen at the
same size it prints.

The file's own comment states the rule that governs it, and the template honours it:

> *"Buyer-internal facts (target rates) never appear here: the letter asks for a
> price, it does not hint at one."*

That is why **no money appears on this document**. Mandate 3 is satisfied by absence,
and the absence is the design.

### S1 — the question this screen exists to answer

**What does a Stabler document look like on paper, and where do those rules live?**

Right now the answer is: in this file, privately, in a fourth dialect.

| | screen | this letter |
|---|---|---|
| layer | `.stbl-ds` | **none** |
| vocabulary | `ds-*` | **`rfq-*`**, 20 private classes |
| type | px, layer tokens | **pt**, hard-coded: 16 / 14 / 11 / 10 / 9.5 / 9 / 8 |
| colour | layer tokens | **hard-coded**: `#111 #333 #555 #666 #999 #ddd #eee #fafafa` |
| font | layer | `Inter, system-ui, -apple-system, sans-serif` (`:188`) |
| radius | layer (0) | none used |
| stripes | layer, automatic | `rfq-row--alt`, hand-applied |

None of those eight greys is a layer token. The letter and the screen that produced it
are two different products, and a supplier who receives letters from both this module
and the sales module receives two different-looking documents from one company.

Draw **both** answers:

- **(a) The letter joins the layer** — it gains the `.stbl-ds` ancestor the council
  requires, and the layer gains its first `@media print` block: print tokens, a print
  type ramp, a print table. Every future printed document inherits it.
- **(b) The letter stays its own thing** — a document vocabulary deliberately separate
  from a screen vocabulary, because a page has no hover, no scroll, no viewport and no
  dark mode, and forcing one system across both makes both worse.

Both are defensible. **(a) is what the council asked for and (b) is what four
different files independently chose** — see the architectural problem below.
Trade-offs, and a recommendation, and if you recommend (a), say what the layer's print
block must contain.

### S2 — the page is designed for one language and printed in four

The letter is offered in **en, ru, uz and tr** (a fifth catalogue, `uzc` — Uzbek
Cyrillic — is still shipped and translated). Worst-case growth is **3.75×**. On A4 the
page cannot widen, and these strings are all fixed in place:

- `Request for quotation` — the title, 14 pt bold (`:81`)
- `We kindly ask you to quote your prices and delivery terms for the following items.`
  — the lead (`:85`)
- `Please respond by` (`:91`)
- Five table headers, one of which sits in a **30 mm fixed column**: `Needed by`
  (`:102`)
- `Please state: unit price, currency, validity period, and delivery time.` (`:124`)
- `Requested by` and `Supplier signature / stamp`, both above **60 mm** rules
  (`:129`, `:133`, `:277-281`)

Draw the loaded page in **English and Uzbek**, same A4 frame, and show what gives.
`Needed by` in a 30 mm column is the concrete failure; find the others.

**And say which language the letter should be in at all.** It is currently rendered in
the *buyer's* interface language — the officer's UI setting — and handed to a
*supplier* who may read none of it. Hebei Rail Parts and Temiryo'l ta'minot do not
read the same language, and the seeded supplier pool spans Uzbekistan, China and the
Russian Federation. This is a question, not a task: state it precisely.

### S3 — the document has no identity a supplier can act on

The header carries the company block and the RFQ id. It does **not** carry:

- **who to reply to** — no officer name, no direct contact, no reply address; the
  company block has a generic `email` and `phone_no` from the Company doctype, both
  optional and both blank on a fresh tenant (`sourcing.py:919-923`, `getattr(…, "") or
  ""`);
- **which supplier this copy is for** — one letter is generated per RFQ, not per
  supplier, so every recipient gets an identical unaddressed page;
- **any reference the supplier should quote back**, other than the RFQ id in the
  corner.

`Requested by` sits above an **empty rule** for a handwritten signature (`:129-130`) —
the one place a name would appear, left blank by design so it can be signed by hand.

Draw what the header must carry for the letter to be answerable, and separate what is
available today from what would need a question to the backend.

### An architectural problem you must show, not solve

**The app ships four global `@page` rules that fight each other, and this file is
one of them.**

Measured in the shipped bundle `stabler/public/dist/js/stabler.bundle.BUSE7QDS.js`:
`@page` appears **4 times**, `visibility: hidden` **4 times**.

| file | page size | margin |
|---|---|---|
| `pages/sales/InvoicePrint.vue:299` | A5 portrait | 5 5 10 5 mm |
| `pages/purchasing/InvoicePrint.vue:261` | A5 portrait | 5 5 10 5 mm |
| `pages/sales/Waybill.vue:187` | A4 portrait | 10 mm |
| **`pages/tender/rfq/RfqPrint.vue:142`** | **A4 portrait** | **15 mm** |

All four live in **unscoped** `<style>` blocks, and `router.js` imports every page
component **statically** — 208 static imports, **zero** `() => import(`. So all four
are in the document from first paint, on every screen.

`@page` is a document-level rule, not a selector-scoped one. **One page size wins per
print job, decided by bundle order rather than by which screen you are on.** The
`body * { visibility: hidden }` blocks compose harmlessly by accident — hiding is
idempotent and each file reveals only its own root — but the page geometry does not
compose at all.

Two smaller facts in the same area:

- **`.print-wrapper` is styled nowhere.** Used at three sites
  (`RfqPrint.vue:50`, `sales/InvoicePrint.vue:158`, `purchasing/InvoicePrint.vue:136`),
  defined in no stylesheet and no component. A dead class carried by three files.
- The file's own comment says *"the InvoicePrint approach, unchanged"* (`:148`) —
  correctly describing an approach copied four times and owned by no one.

**Do not fix this.** It is a bug, it is being recorded separately, and it is outside a
design package's scope. **But do not design as if it were absent:** whatever you
recommend in S1(a) — a print block in the layer — has to say what happens to four
`@page` declarations that already exist.

## 7 · Data — use these rows, invent nothing

**The demo data produces no RFQ at all.** `seed_tender_demo.py` creates 13 lots and
their Supplier Quotations and **never the string "Request for Quotation"**. This
screen is reachable only from a record created by hand through screen 06.

Print `PUR-RFQ-2026-00001` on lot **`UTY-2026-4308`** · *Signal va aloqa boshqarmasi*:

| field | value | source |
|---|---|---|
| company name | **Mikas** | `Company.company_name` |
| TIN | *(blank on a fresh tenant)* | `Company.tax_id`, optional |
| phone | *(blank)* | `Company.phone_no`, optional |
| email | *(blank)* | `Company.email`, optional |
| RFQ id | `PUR-RFQ-2026-00001` | |
| transaction date | **12 days ago** | |
| respond by | **—** | `schedule_date` is empty; the block is `v-if`, so **the whole line vanishes** |

| # | item | qty | UOM | needed by |
|---|---|---|---|---|
| 1 | `UTY-2026-4308 (demo)` | 1 | **—** | today |

**Four things in this data the design must not smooth over:**

1. **Three of the four company header fields are blank on a fresh tenant**, and each is
   its own `v-if` (`:69-71`). The header collapses to a bare company name over a rule
   — on the one document that leaves the building.
2. **`Please respond by` disappears entirely when there is no date** (`:90-92`). A
   letter with no deadline does not say it has no deadline; the line is simply not
   there. That is the fifth state rendered as absence.
3. **The one line is quantity 1 with a blank UOM.** The letter asks a supplier to
   quote a unit price for a unit it does not name, and the closing instruction says
   *"Please state: unit price, currency, validity period, and delivery time."*
4. **The description row is conditional on being different from the name**
   (`:110-112`) — so a line whose description equals its item name prints one line,
   and one whose description differs prints two. The table's row height varies with a
   comparison the reader cannot see.

**No money on this document** — see §6. **Dates** `dd.mm.yyyy` via `formatDate()`.

### One fact about the payload, stated once

`rfq_print` returns `{**get_rfq(name, company), company_name, company_abbr,
company_tax_id, company_email, company_phone}` (`sourcing.py:909-924`). `get_rfq`'s
payload includes **`target_rate` on every line** (`sourcing.py:880`).

The template is correct — it renders no rate, exactly as its comment promises. But the
buyer's internal target prices are delivered to the browser and sit in the network
response of the page whose purpose is to be handed to a supplier. This is not a visual
defect and you cannot draw it away. **Note it as a question for the backend**, in one
line, and move on.

## 8 · Vocabulary

**This is the section where your S1 answer becomes concrete.** The layer's vocabulary
is a screen vocabulary; here is what exists and what does not.

**Exists in the layer, unusable as-is on paper:** `ds-table` (13.5 px, hover row
backgrounds, screen greys), `ds-chip[data-tone]` (colour-carried status),
`ds-btn`/`ds-btn--primary` (never printed), `ds-empty`, `ds-skel`, `ds-panel`.

**Does not exist anywhere:** a print type ramp, print colour tokens, a print table,
page-break rules beyond this file's two (`page-break-inside: auto` on `table`, `avoid`
on `tr`, `:168-173`), a running header or footer, page numbering, a print empty state.

**This file's private set, for you to keep or replace:** `a4-print` · `rfq-head` ·
`rfq-brand` · `rfq-sub` · `rfq-rule` · `rfq-id` · `rfq-title` · `rfq-lead` ·
`rfq-meta` · `rfq-table` · `rfq-th` · `rfq-row--alt` · `rfq-num` · `rfq-center` ·
`rfq-item-name` · `rfq-muted` · `rfq-faint` · `rfq-sign` · `rfq-sign-line` ·
`print-wrapper` *(dead)*.

**Screen chrome** (`.no-print`, hidden when printing): two buttons, `Back` and
`Print`. `Print` is `btn-primary` and `Back` is `btn-outline-secondary` — one primary
per region, satisfied. `Back` calls `router.back()` (`:52`), which on a directly
opened URL goes wherever the browser was before, possibly outside the app.

**Forbidden here:** `spinner-border` (1 site, `:61`); an alert without `role="alert"`
(1 site, `:63`); any internal URL on the printed page; any money; any policy number;
any status badge — a supplier has no use for `Draft`.

## 9 · Responsive — and the medium

Draw at **1280**, **992** and **640** px **on screen**, and at **A4** as printed. Four
frames, and the fourth is the real one.

Measured: the on-screen page is a fixed **186 mm** wide (`:180`) — about **703 px** —
inside a `print-wrapper` that is styled nowhere. Below roughly 750 px of viewport it
**overflows horizontally with no scroller**, because there is no `table-responsive`
and no max-width rule anywhere on the path. On a 640 px phone the letter is cut off,
and the rule says nothing may scroll the page horizontally.

A fixed-millimetre page inside a fluid viewport is the problem on this screen. Solve
it explicitly, and note that it cannot be solved by the layer's mobile collapse rules —
those apply to `ds-drawer` and `ds-form-grid`, neither of which is here.

**Print-specific, and the reason the fourth frame is the real one:** decide what
happens at a page break with a long item table — 40 lines is normal for a construction
lot. Today the table breaks anywhere, rows stay whole, and **the header does not
repeat**: page 2 of the item list has no column titles. The signature block is
`margin-top: auto` inside a flex column (`:274`), so on a multi-page document it
lands under the last row rather than at the foot of the last page.

## 10 · Deliverables

1. The letter as **A4**, loaded, with the data above — the primary artboard.
2. The same letter at **A4 in Uzbek**, same frame, per S2.
3. The on-screen view at 1280 / 992 / 640, including the 640 px overflow as it is
   today.
4. All five states, split into **screen chrome** states and **document** states per §5
   — including the blank sheet a user gets by printing during a failure.
5. The **empty document**: an RFQ with no lines, printed.
6. **Both** answers to S1, each drawn, with trade-offs and a recommendation. If (a):
   what the layer's `@media print` block contains, and what happens to the four
   existing `@page` rules.
7. The header per S3, separating what is available today from what needs a question.
8. A **multi-page** letter: 40 lines, showing the page break, the repeated header you
   recommend, and where the signature block lands.
9. The header with three of four company fields blank.
10. Every question your design raised, listed — including the language question from
    S2 and the payload question from §7.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `RfqPrint.vue`, `stabler-modernist.css`,
`router.js`, `stabler/api/sourcing.py` and the shipped bundle on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | **The component has a `.stbl-ds` ancestor.** The council's requirement; this file and `BidPricing.vue` are the two that measure 0 | 0 | 1 |
| K2 | **No spinner.** The one `spinner-border` (`:61`) becomes a skeleton of the page it is loading | 1 | 0 |
| K3 | **The error alert carries `role="alert"` and a retry** | 0 / 0 | 1 / 1 |
| K4 | **The document has an empty state.** `doc.items` renders through `v-for` with no fallback (`:106`) | 0 | 1 |
| K5 | **`Please respond by` never disappears silently.** The `v-if` at `:90` is the only thing standing between "no deadline" and no line at all | vanishes | asserted |
| K6 | **No fixed-width column carrying translated text.** `style="width: 30mm"` on `Needed by` (`:102`) is the live case | 1 | 0 |
| K7 | **The printed page carries no internal URL, no money, no policy number and no status badge** | 0/0/0/0 | unchanged |
| K8 | **A multi-page item table repeats its header row** | no | yes |
| K9 | **The on-screen page does not overflow its viewport.** 186 mm fixed (`:180`) with no wrapper rule and no `table-responsive` | overflows | asserted |
| K10 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K11 | **Whatever replaces `rfq-*` is used by more than one file, or `rfq-*` is kept deliberately.** A fifth private dialect invented for one screen is the outcome this prompt exists to avoid | 20 private | decided |
| K12 | **Regression guards — these are already right and must stay so.** Zero money rendered, `formatDate` on both dates, the buyer's `target_rate` absent from the template, `.no-print` on the chrome, `page-break-inside: avoid` on rows, and one primary button in the chrome region | asserted | unchanged |

**K12's third item is the one that must not be lost in a redesign.** The rate is in the
payload; only the template's restraint keeps it off the page. A migration that rebuilds
this letter from `doc` without reading the comment above it will put the buyer's target
price in front of the supplier being asked to beat it.

State plainly which of these your design satisfies, and name anything it cannot.
