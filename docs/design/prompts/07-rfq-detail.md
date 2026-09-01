# 07 · RFQ detail

**Source:** `stabler/public/js/pages/tender/rfq/RfqDetail.vue` — 245 lines,
**0 `ds-*`, 0 `tgm-*`, 4 badges, 0 spinners, 6 bare `btn-*`**.

As with 05 and 06, the zero `ds-*` does not put this screen outside the layer — it
renders inside `<TenderPage>` (`.stbl-ds`) and the layer's 344 compatibility rules
already paint it. What it lacks is vocabulary, not styling.

**This screen has the sharpest defect in the family, and it is not a visual one.** It
carries a button that writes a durable record to the database and **no path anywhere
in the SPA can read that record back**. Screen 04's silent fork lost an error; this
one loses a success. Both leave a toast as the only evidence, and a toast is not a
record.

**Correction, 2026-09-01 — carried from prompt 11.** `RfqDetail.vue` calls
`useAutoRefresh(load)`, `load()` sets `loading = true`, and the template answers with
`v-if="loading"` — **so this page replaces itself with a skeleton every sixty seconds**.
`load()` also catches its own error and toasts, defeating the composable's documented
promise never to surface an auto-refresh failure as a toast. Six screens do both; the
module's answer is drawn on **prompt 11's canvas** and this screen adopts it rather than
inventing a second one. A detail page is the harder case: there is no lane board to
redraw, only a form the user may be reading mid-sentence.

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
| `logist` | System Manager · Stabler Admin · Sales Manager · Stabler Tender Logistics |

A **sourcing** screen. `mark_rfq_sent` needs **two** permissions — `write` on the RFQ
*and* `create` on `Communication` (`sourcing.py:938-939`) — so a user can read this
whole page and be refused by the one control on it. Draw that.

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
   button; the search placeholder ends with `⌘K`. *(Not a list screen.)*
9. Loading is a skeleton, never a bare spinner.

**Mandates 1, 3, 6 and 7 all bear on this screen at once, and it breaks three of
them.** Mandate 1 is the one it cannot break by adding a link — see S1, where the only
place the missing record is visible is Frappe Desk.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.**
- **A disabled control carries its reason beside it.** `Mark as sent` is disabled while
  `marking` is true (`:118`) with no reason and no busy affordance — the label does not
  change, nothing spins, nothing is announced.
- **The procurement policy numbers are server values** and never literal digits. **This
  screen reads no policy at all** — see S2.
- **No fixed-width label, badge or nav item.** Worst-case growth **3.75×**.
- **String interpolation exists; plurals do not.**
- **The currency is the company's home currency, read from the server, never a
  literal.** Settled 2026-09-01 as the third documented exception in
  `.claude/rules/10-frontend.md`. **This screen passes an empty string as the
  currency** — see S3.
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
  S1 will tempt you. Read its last paragraph before you answer it.
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

**This screen has a real error state and it is a dead end.** `:134` renders
`<div class="alert alert-danger">{{ error }}</div>` — no `role="alert"`, no retry, and
because the header's action slot is `v-if="rfq"`, the failure also removes every
control that could have recovered from it. The user's only move is the browser's back
button.

**The loading state draws one table where two will appear.** `SkeletonRows :cols="4"`
inside a single card (`:129-133`), while the loaded screen has a 4-column suppliers
table *and* a 5-column items table, in two cards, under a summary bar. The skeleton is
not a placeholder for this screen; it is a placeholder for a different one.

## 6 · The screen

**RFQ detail.** Whom we asked, who answered, what we asked for. Three regions under a
page header:

1. a **summary bar** — status badge, raised date, response-by date, responded count;
2. **Suppliers asked** — supplier · contact · quotations · answered, with a footer
   that routes to the sourcing workspace;
3. **Requested items** — item · qty · UOM · target rate · needed by.

The header carries a channel `Select` and two buttons: `Mark as sent` and `Print`.

### S1 — the question this screen exists to answer

**`Mark as sent` writes a record that nothing can read back.**

The server side is real and careful. `mark_rfq_sent` (`sourcing.py:927-961`) inserts a
**Communication** — `communication_medium` from the channel, `sent_or_received:
"Sent"`, `sender: frappe.session.user`, `reference_doctype: "Request for Quotation"`,
`reference_name: doc.name` — the same record type the CRM email trail uses. It is
durable, attributed, timestamped and queryable.

The client side then does this (`:84-99`):

```
await call("stabler.api.sourcing.mark_rfq_sent", …)
toast.success(t("Sending recorded on the RFQ timeline."))
```

and **stops**. No reload. `rfq.value` is untouched. And it could not help if it did:
**`get_rfq` returns no sending information at all** — its payload is `name`, `deal`,
`deal_label`, `company`, `status`, `docstatus`, `transaction_date`, `schedule_date`,
`suppliers`, `items` (`sourcing.py:861-885`). No `sent_at`, no `channel`, no
communications.

So, all true at once:

- The toast says *"recorded on the RFQ timeline"* and **this page has no timeline**.
- Press the button five times and you get five toasts, five Communications, and a
  screen that never changes.
- The channel `Select` defaults to `whatsapp` on every mount (`:39`). An RFQ sent by
  email last week shows `WhatsApp` today.
- **The only surface in the whole system where that Communication is visible is
  Frappe Desk** — which mandate 1 forbids you to link to.

**Before you answer:** the obvious fix is "return the communications from `get_rfq`",
and that is a backend change this prompt forbids. But look again — you are not being
asked to add a **field**, a **doctype** or a **migration**. The record already exists,
already carries everything needed, and is already linked to this document. Say
precisely what the screen needs to show and what shape the read would take, as a
**question for the backend**, and design the region that would hold it — including
what it must say **today**, when the answer is not available.

That "today" rendering is the **fifth state**: sending is not empty, not zero, and not
unsent. It is **not measurable from here**.

### S2 — the same number, measured against nothing

The suppliers table shows each supplier's quotation count as a green badge when it is
non-zero and an em-dash when it is zero (`:176-179`). Two problems:

1. **Colour is the only code.** Green pill or dash. No shape, no word, and the dash is
   doing the work of "none" in a column where three other dashes on the same screen
   mean different things.
2. **It is measured against nothing.** The *list* screen takes the same underlying
   number and compares it to `tenderPolicy.minQuotations` from the session store. This
   screen — which shows the suppliers one by one, where the policy actually bites —
   compares it to zero. One number, two screens, two rules, and the stricter rule is
   on the screen with less information.

`Received` / `Waiting` (`:182-185`) is a **second status vocabulary** beside the
shared docstatus map used correctly ten lines above (`:139`). Hand-written
`bg-green-lt` / `bg-secondary-lt`, no shared map, no `data-tone`.

**And `Waiting` is wrong for the row that matters.** The screen holds
`rfq.schedule_date` — the response deadline. A supplier who has not answered *after*
that date is not waiting, they are **overdue**, and the screen has both facts and
draws neither together.

### S3 — money rendered by no rule at all

```
function fmtRate(v) {
  return formatMoney(v, "", user.value.language);   // :64-66
}
```

That empty string is the currency. Follow it into `composables/money.js:155-180`:
there is no override for `""`, so it reaches
`new Intl.NumberFormat(locale, {style: "currency", currency: ""})`, which **throws** —
a currency style requires a valid ISO code — and the `catch` returns **`n.toFixed(2)`**.

So every target rate on this screen renders as a bare number with a dot decimal and
**no grouping, on every locale**: `920000000.00`. The same value on screen 06, which
passes the real currency, renders `920 000 000,00 сўм`.

`money.js`'s own header documents at length why locale money formatting is not
optional here — the rule it replaced posted **150000050** to the ledger for a user who
typed **1500000.50** on the Russian UI. This screen bypasses all of it.

The currency is available: `get_rfq` is called with the company, and the home currency
resolves server-side exactly as `_accounts.py:94` does it — Mikas's is UZS, another
tenant's is its own. **Never a literal.** Draw the target-rate column with a currency,
and say which one it is and where it came from.

### An architectural problem you must show, not solve

**Three `<a href="#">` with `@click.prevent`** (`:107`, `:194`) — the lot link in the
header meta and the "Open comparison" link in the suppliers footer. Fake links: no
target, no middle-click, no copy-link, no keyboard focus order that means anything.
One of them sits in a `#meta` slot whose whole content is *"Lot: <fake link>"*.

Draw them as real destinations. Do not redesign the router.

## 7 · Data — use these rows, invent nothing

**The demo data produces no RFQ at all.** `seed_tender_demo.py` creates 13 lots and
their Supplier Quotations and **never the string "Request for Quotation"**. The only
way to reach this screen on a seeded site is to create one through screen 06.

Draw `PUR-RFQ-2026-00001` on lot **`UTY-2026-4308`** · *Signal va aloqa boshqarmasi*
(`seed_tender_demo.py:64-84` — sourcing stage, 19 days in step against a 14-day
threshold, value 920 000 000):

**Summary bar:** status `Draft` · raised **12 days ago** · response by **—** ·
responded **1 / 3**

**Suppliers asked:**

| supplier | contact | quotations | answered |
|---|---|---|---|
| Hebei Rail Parts | `sales@hebeirail.cn` | **1** | Received |
| Shandong Heavy | **—** | **—** | Waiting |
| Temiryo'l ta'minot | Aziz Karimov | **—** | Waiting |

**Requested items:**

| item | qty | UOM | target rate | needed by |
|---|---|---|---|---|
| `UTY-2026-4308 (demo)` | 1 | **—** | **920000000.00** | today |

**Four things in this data the design must not smooth over:**

1. **Five em-dashes, four meanings.** No response-by date · no contact on file · no
   quotation received · no UOM captured. The screen renders all four identically, and
   the fifth-state rule says at least one of them is a different thing.
2. **The target rate is drawn exactly as the code renders it** — `920000000.00`,
   ungrouped, no currency. Do not tidy it in the "before" artboard; that string is the
   finding.
3. **Responded is `1 / 3` and the policy minimum is 5.** The RFQ asked three suppliers
   against a policy that wants five quotations from two countries. Nothing on this
   screen says so; the *list* screen would have.
4. **`Response by` is blank and the lot's deadline is today.** The RFQ carries no
   response date while the tender it serves closes in hours.

**Policy:** `MIN_QUOTATIONS = 5`, `MIN_COUNTRIES = 2` — server values, **never a
literal digit**.

**Currency:** the company's home currency, from the server. Mikas's is UZS. Decimals
from `moneyFractionDigits(currency)` — for UZS that is **2**, because that is what the
ledger holds (`money.js:16-25`), not zero.

## 8 · Vocabulary

**Sections** — `ds-form-section`, **adjacent stack**: flush inside one bordered card,
divided by their own heads, no nested card frames. Settled on screen 01. **Measured
here: three separate `.card`s with `mb-3`.**

**Summary values** — `ds-kpi`, `-val`, `-cap`, `-note`, or `ds-deflist` for
label/value pairs. The current bar is four `<span class="small text-secondary">` with
`<strong>` inside, in a flex row.

**Tables** — `ds-table` inside a mandatory `table-responsive` wrapper; numeric cells
`ds-td-num`. **Measured: `ds-table` 0, `table-responsive` 2, `card-table` 3.**

**Status** — `ds-chip[data-tone]` through the shared status map. **Correct once
(`:139`), then abandoned for three hand-written badges.**

**Ratios and thresholds** — `ds-meter` / `-seg` / `-txt`
(`stabler-modernist.css:337-342`). `1 / 3` responded against a policy of 5 is exactly
this construct.

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it.
It must match the tables it stands in for; see §5.

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Waiting is a **label
swap** plus `aria-busy="true"` plus `disabled`. The header currently has a
`btn-outline-secondary` and a `btn-primary` side by side; decide which one is the
region's primary and why — `Print` is currently primary and `Mark as sent`, the only
control that writes anything, is not.

**Forbidden here:** `class="badge bg-*"` (3 of the 4 sites); `card-table`;
`<a href="#">`; `formatMoney(v, "")`; an alert without `role="alert"`.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. Two tables, 4 and 5 columns, plus a
four-value summary bar in a `d-flex flex-wrap gap-4` that wraps without any rule about
what wraps first. The header holds a 140 px-wide `Select` (`:114`, inline
`style="width: 140px"`) beside two buttons — **a fixed width on a control whose
options are translated**, against 3.75× growth. `In person` becomes a longer string in
every other language.

Nothing may scroll the page horizontally.

## 10 · Deliverables

1. The detail screen at 1280 / 992 / 640, loaded, with the data above.
2. All five states — including the **forbidden** state that can arrive from the
   `Communication` permission alone, and the **not measurable** state for sending.
3. The error state with `role="alert"`, a retry, and header actions that survive it.
4. The loading skeleton matching the two tables it replaces.
5. Your answer to S1: the sending region drawn **twice** — as it must look once the
   record can be read, and as it must look **today** when it cannot. Plus the backend
   question, stated precisely.
6. The channel `Select` redrawn so it does not assert a default it does not know.
7. The per-supplier quotation count per S2 — colour + shape + word, measured against
   the server policy — and `Received`/`Waiting`/**overdue** from one shared vocabulary.
8. The target rate with a real currency and real grouping, and the "before" artboard
   keeping `920000000.00` exactly as it renders today.
9. The five em-dashes disambiguated.
10. Every question your design raised, listed.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `RfqDetail.vue`, `composables/money.js` and
`stabler/api/sourcing.py` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | **No money formatted without a currency.** `formatMoney(v, "")` at `:65` is the only site; it reaches `Intl.NumberFormat`'s throw and returns `toFixed(2)` | 1 | 0 |
| K2 | **`Mark as sent` changes the screen.** After a success the page shows the sending, or states that it cannot be read back — it does not rely on a toast | toast only | asserted |
| K3 | **No page-local colour map.** Three hand-written badges (`:176`, `:182`, `:185`) beside one correct shared-map badge (`:139`) | 3 local | 0 |
| K4 | **The error alert carries `role="alert"` and a retry**, and the header's actions are not gated on the record having loaded | 0 / 0 | 1 / 1 |
| K5 | **The loading skeleton matches the loaded layout** — two tables, 4 and 5 columns, not one table of 4 | 1×4 | 2 |
| K6 | **No `<a href="#">`** | 3 | 0 |
| K7 | **Busy controls carry `aria-busy="true"` and swap their label.** `marking` currently only disables | 0 | asserted |
| K8 | **The response-by deadline participates in the answered column.** A supplier unanswered past `schedule_date` does not render identically to one still in time | same | different |
| K9 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K10 | **No fixed pixel width on a control carrying translated text.** The channel `Select`'s inline `width: 140px` (`:114`) | 1 | 0 |
| K11 | **Regression guards — these are already right and must stay so.** `getStatusBadgeClass` + `getDocstatusLabel` imported and used for docstatus, `formatDate` on every date, `SkeletonRows` present, `EmptyState` present, `useAutoRefresh` present, and zero links into Frappe Desk — including in whatever S1 produces | 2/3/1/1/1/0 | unchanged |

**K11's last clause is the one to read twice.** The record S1 is missing is visible
today in exactly one place, and that place is the one mandate 1 forbids. A design that
solves S1 with a link to Desk has not solved it.

State plainly which of these your design satisfies, and name anything it cannot.
