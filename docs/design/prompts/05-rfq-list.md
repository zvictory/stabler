# 05 · RFQ list

**Source:** `stabler/public/js/pages/tender/rfq/RfqList.vue` — 146 lines,
**1 `ds-*`, 0 `tgm-*`, 2 badges, 0 spinners, 2 `ListToolbar` sites**.

**Why this one first of the four, and what its measurement does not mean.** Screens
05–08 are one doctype seen four ways, and this is the front door. Its `ds-*` count is
1, which on screens 01–03 meant "outside the layer". **Here it does not.** This screen
renders inside `<TenderPage>`, whose root is `<div class="tender-page stbl-ds">`
(`TenderPage.vue:12`), and the layer carries **344 `.stbl-ds`-prefixed rules** that
restyle bare Bootstrap — `.stbl-ds .btn`, `.card`, `.table`, `.badge`, `.form-control`.

So this screen is **already wearing the layer's clothes without speaking its
vocabulary**. That is why nobody migrated it: the cost was never visual. What it loses
is the semantics — `ds-sev`, `ds-meter`, `ds-empty`, `ds-row`, `ds-table` — every
construct that carries meaning rather than paint.

**It is also the best-behaved list in the module.** It keeps mandates 7, 8 and 9
already. Name what it does right; the other three screens must copy it.

**Correction, 2026-09-01 — this prompt missed a defect, and prompt 11 found it.**
`RfqList.vue` calls `useAutoRefresh(load)`, and `load()` sets `loading = true`, which
this file's template answers with `v-if="loading"`. **So the list replaces itself with a
skeleton every sixty seconds.** And `load()` catches its own error and calls
`toast.error(...)`, so it never throws — which defeats the composable's documented
promise that *"an auto-refresh must never surface as an error toast"*. Both hold for six
screens (`DeclarantQueue`, `LogistBoard`, `DirectorBoard`, `MyTenders`, `RfqList`,
`RfqDetail`). **The module's answer is drawn on prompt 11's canvas, not here** — this
note exists so a designer reading 05 alone does not redraw the same gap. Anything drawn
for this screen must adopt 11's liveness vocabulary: a first-paint flag that a
background tick does not set, a staleness line in the page head, and a failed tick that
is not a toast.

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

This is a **sourcing** screen. Its endpoint throws `PermissionError` twice: once for
the tender module, once for `Request for Quotation` read permission. **Two different
refusals reach the same catch and become the same red toast.** Say what the forbidden
state should distinguish.

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

**Mandates 7, 8 and 9 this screen already keeps** — `getStatusBadgeClass` +
`getDocstatusLabel` (`:131-132`), `ListToolbar` with `⌘K` (`:79-87`), `SkeletonRows`
(`:102`). It is the only list in the module that keeps all three. **Mandate 7 it also
breaks, in the next column over.** See §6.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.**
- **A disabled control carries its reason beside it.**
- **The procurement policy numbers are server values** and never literal digits. This
  screen reads `tenderPolicy.minQuotations` from the session store and is **right**
  about it (`:122`).
- **No fixed-width label, badge or nav item.** Worst-case interface-language growth is
  **3.75×** — `RFQs` becomes `Narx so'rovlari`, and that string is **in this screen's
  search placeholder**.
- **String interpolation exists; plurals do not.** `RFQs` in the placeholder is a bare
  English plural with no interpolation and no plural form behind it.
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

**This screen is the module's cleanest case of the fifth state being drawn as the
second.** `list_all_rfqs` returns `{"rows": [], "count": 0}` when
`_rfq_link_ready()` is false (`sourcing.py:795`) — an unmigrated site, where the link
field between RFQ and tender lot does not exist yet. That is **not measurable**. The
screen renders it as `No requests for quotation yet.` — which is a claim about the
business, made from a fact about the schema. Draw both, differently.

**There is no error state at all.** The `catch` (`:41-44`) toasts and sets
`rows.value = []`, so a failed load and an empty company are **the same screen**. That
is now three meanings on one empty state.

## 6 · The screen

**RFQ list.** Every request for quotation raised across the company's tender lots,
with the two numbers the sourcing policy is audited against: how many suppliers were
asked, and how many quotations came back.

Seven columns: RFQ · Tender lot · Raised · Response by · Suppliers asked · Quotations
· Status.

### What it already gets right — name each one, because the others must copy it

1. **`ListToolbar` with auto-apply and `⌘K`** — the only list in the module that has
   it. No Apply button, no Refresh button.
2. **The shared status map** for the docstatus badge (`:131`) — `getStatusBadgeClass`
   and `getDocstatusLabel`, imported, not re-derived.
3. **`SkeletonRows` mounted as the `<tbody>`**, not inside one (`:102`).
4. **`EmptyState`** rather than a hand-written empty row.
5. **`formatDate()`** on both dates.
6. **The policy minimum read from the server** (`:122`), never a literal `5`.
7. **`table-responsive`** present (`:88`).

### S1 — the question this screen exists to answer

**Two numbers sit side by side and are counted over different denominators.**

- `supplier_count` is **per RFQ** — how many suppliers this document asked
  (`sourcing.py:812`).
- `quotation_count` is **per DEAL** — every quotation on the lot, whoever sent it
  (`sourcing.py:813`, `_deal_quotation_counts(deals)` keyed by `deal_name`).

Consequences, all live:

- Two RFQs raised on the same lot show the **same** quotation count.
- The count includes answers from suppliers this RFQ never asked.
- A row can read `Suppliers asked 3 · Quotations 5` and nothing is wrong with it.

The sibling screen states the principle exactly, in its own source comment:

> *"'asked' and 'answered' are separate facts and one standing in for the other is
> what hid the gap in the first place."* — `RfqForm.vue:144-147`

**This list performs that substitution.** Answer it. Both readings are defensible —
the lot's total response is a real thing a sourcing officer wants — but the current
design gives one number two meanings and labels it once. Draw:

- **(a)** the two numbers kept, relabelled so the denominators are visible;
- **(b)** a single per-RFQ ratio, with the lot-level total moved somewhere it belongs.

Trade-offs and a recommendation.

### S2 — the quotation badge is a second, private severity vocabulary

Line 119-128, next to the shared map on line 131:

```
green  when quotation_count >= tenderPolicy.minQuotations
grey   otherwise
```

Three problems, in order of severity:

1. **It is a page-local colour map** — exactly what mandate 7 forbids, sitting in the
   next `<td>` from the mandate being kept.
2. **Grey is the wrong code for "the policy is not met".** That is the one number the
   sourcing policy is audited against. Under-minimum is a *finding*, not a neutral.
3. **Colour is the only code.** No shape, no word. A red-green colour-blind buyer sees
   two grey pills; a printed list shows nothing at all.

The layer already has the construct for a value measured against a threshold:
`ds-meter` / `ds-meter-seg` / `ds-meter-txt` (`stabler-modernist.css:337-342`). Use
it, or argue why a threshold badge is different from a meter.

### S3 — the row is a click target with no keyboard path

Line 103-108: `<tr style="cursor: pointer" @click="openRfq(r.name)">`. No `role`, no
`tabindex`, no key handler. **The whole row opens the record and nothing announces
it.** Screen 02 met the same pattern as `<tr role="button" tabindex="0">` — worse
markup, better honesty, since at least it claimed to be a control.

Screen 02's decision applies here unchanged, and you should state it in the same words:

> **A container that groups a record's fields never carries `role="button"` or
> `tabindex`. The control is a real `<button>` on the field that identifies the
> record.**

Here that field is the RFQ id in column one.

**And there is a second target inside the first.** Line 111 is an `<a href="#">` on
the lot label, defused with `event.stopPropagation()` — a fake link nested inside a
click surface, where the outer target is invisible to a keyboard and the inner one
goes nowhere. Draw the row with **both** destinations reachable and distinguishable.

### An architectural problem you must show, not solve

**The list silently truncates and reports the truncation as the total.**
`list_all_rfqs` caps at `limit` — default **200**, clamped to `[1, 500]`
(`sourcing.py:806`) — and returns `{"count": len(rows)}`, the *capped* length. The
toolbar renders that as `:count="rows.length"`.

So on a company with 340 RFQs the screen says **200** and nothing anywhere says
"more". There is no pagination, no "showing 200 of …", no way to reach row 201 except
narrowing the search.

**And the search cannot narrow it usefully:** `filters["name"] = ["like", …]`
(`sourcing.py:801`) matches the **document id only**. The screen shows a `Tender lot`
column and a supplier count, and you can search by neither. The placeholder promises
`Search RFQs…`; what it searches is `PUR-RFQ-2026-00001`.

Do not design the pagination — that is decision 10.1, still open. **Design the
honesty:** the count must not claim to be a total it is not, and the search field must
not imply a reach it does not have.

## 7 · Data — use these rows, invent nothing

**Read this before drawing the loaded state: the demo data produces zero rows here.**

`stabler/maintenance/seed_tender_demo.py` creates 13 tender lots, their suppliers and
their **Supplier Quotations** — and **not one Request for Quotation**. The string does
not appear in the file. Every quotation the sourcing workspace compares is an answer
to a question that was never recorded.

That is a finding about the product, not about the seed: **the module models answers
without questions, and these four screens exist to close that gap.** Say so.

So the loaded state is drawn from what the API *would* return. Use these three rows,
built from the real lots and the real supplier pool:

| RFQ | Tender lot | Raised | Response by | Suppliers asked | Quotations | Status |
|---|---|---|---|---|---|---|
| `PUR-RFQ-2026-00001` | `UTY-2026-4308` · Signal va aloqa boshqarmasi | 12 days ago | **—** | 3 | **5** | Draft |
| `PUR-RFQ-2026-00002` | `UTY-2026-4308` · Signal va aloqa boshqarmasi | 4 days ago | in 3 days | 2 | **5** | Draft |
| `PUR-RFQ-2026-00003` | `UTY-2026-4309` · Qurilish materiallari kombinati | 26 days ago | 5 days ago | 6 | 3 | Submitted |

**Every one of these rows is doing work:**

- Rows 1 and 2 are **the same lot**, so they carry **the same `5`** — S1, visible.
- Row 1 has **no `Response by`**, rendered `—` (`:116`). Is that "no deadline was set"
  or "not measurable"? Fifth-state rule; the screen currently cannot tell them apart.
- Row 3's response date is **in the past** and its quotation count is **below the
  policy minimum**. The screen has both facts and draws neither as a problem: the date
  is plain text, the count is a grey pill.
- Row 3 is the only `Submitted`; 1 and 2 are `Draft`. `docstatus < 2` is the filter,
  so cancelled RFQs never appear at all — a fourth thing the empty state can mean.

**Policy:** `MIN_QUOTATIONS = 5`, `MIN_COUNTRIES = 2`, read from the session store as
`tenderPolicy.minQuotations`. **Never render the digit 5 as a literal.**

**Dates:** `dd.mm.yyyy` via `formatDate()`. **No money on this screen at all** — do
not add any.

## 8 · Vocabulary

**Tables** — `ds-table`, and a `table-responsive` wrapper is **mandatory**. Numeric
cells are `ds-td-num`. **Measured here: `ds-table` 0, `table-responsive` 1, and
`card-table` 1.** The wrapper is right and the table class is Bootstrap's.

**Toolbar** — the shared `ListToolbar`, auto-apply, placeholder ending `⌘K`. **Already
correct — keep it exactly.**

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it;
its own root is a `<tbody>`. **Already correct.**

**Status** — `ds-chip[data-tone]` through the shared status map. **Already correct for
docstatus; wrong for the quotation count.** See S2.

**Threshold values** — `ds-meter` / `ds-meter-seg` / `ds-meter-txt`.

**Empty** — `ds-empty`. Currently `EmptyState`, which is right in kind and carries one
message for four different situations.

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. The screen's single
`ds-btn` is the `Clear lot filter` action (`:73`) — the module's only correct one
outside the migrated files, and it appears **only when a lot filter is active**.

**Forbidden here:** `class="badge bg-*"` (2 sites, one of them justified by mandate 7
and one forbidden by it); `card-table`; `style="cursor: pointer"` as an affordance;
`<a href="#">`.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. Seven columns is the most of any list in the
module. Below 640 the layer does not collapse tables for you — `table-responsive`
gives you a horizontal scroller inside the card, and **the page itself must never
scroll horizontally**. A seven-column table on a 640 px phone is the problem on this
screen; solve it explicitly, and say which columns a sourcing officer cannot lose.

The `Clear lot filter` button lives in the page header's `#actions` slot next to a
`#meta` line — both appear only in the filtered state. Draw the filtered header too.

## 10 · Deliverables

1. The list at 1280 / 992 / 640, loaded, with the three rows above.
2. All five states — including the **error** state the screen does not have, and the
   **not measurable** state that the unmigrated-site branch currently renders as empty.
3. The empty state **disambiguated**: no rows · no permission · unmigrated · load
   failed. Four situations, one component today.
4. **Both** answers to S1, each drawn, with trade-offs and a recommendation.
5. The quotation count redrawn per S2, with colour + shape + word, and the
   policy minimum never printed as a digit.
6. The row's click target replaced per S3, with the lot link still reachable.
7. The truncation made honest — 200 rows out of an unknown total — without designing
   pagination.
8. The filtered header (`Filtered to one lot` + `Clear lot filter`).
9. The search placeholder at 3.75× growth: `Narx so'rovlari… ⌘K`.
10. Every question your design raised, listed.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `RfqList.vue` and `stabler/api/sourcing.py` on
2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | The table is `ds-table` inside `table-responsive`; `card-table` is gone | 0 / 1 / 1 | 1 / 1 / 0 |
| K2 | **No page-local colour map.** The quotation-count badge's ternary (`:121-125`) is the only one in the file; the docstatus badge already comes from the shared map | 1 local | 0 |
| K3 | **The count badge carries a word and a shape, not only a colour** | colour only | asserted |
| K4 | **No row is a click target.** Zero `@click` on `<tr>`, zero `cursor: pointer` as an affordance; the RFQ id cell holds a real `<button>` | 1 / 1 | 0 / 0 |
| K5 | **No `<a href="#">`.** The lot link is a router link with a real target and needs no `stopPropagation` | 1 | 0 |
| K6 | **A failed load is a state, not a toast.** The template has an error branch; the `catch` at `:41` does not reduce a failure to an empty list | 0 branches | asserted |
| K7 | **Empty and not-measurable are different renderings.** `_rfq_link_ready() == false` does not produce the same screen as "no RFQs" | same | different |
| K8 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K9 | **The count shown is not asserted to be a total.** `:count` is either the true total or labelled as capped | claims total | asserted |
| K10 | **Regression guards — these are already right and must stay so.** `ListToolbar` present with a `⌘K` placeholder, `getStatusBadgeClass` + `getDocstatusLabel` imported and used, `SkeletonRows` as the `<tbody>`, `EmptyState` present, `formatDate` on both dates, and `tenderPolicy.minQuotations` never replaced by a digit | 2/2/1/1/2/1 | unchanged |

**K10 is the longest regression guard in the package so far, and that is the point.**
This screen keeps three mandates the rest of the module breaks. A migration that
modernises the markup and loses the toolbar, the status map or the skeleton has made
the module worse while making this file look better.

State plainly which of these your design satisfies, and name anything it cannot.
