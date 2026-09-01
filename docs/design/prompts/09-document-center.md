# 09 · Document center

**Source:** `stabler/public/js/pages/tender/TenderDocuments.vue` — 520 lines,
**0 `ds-*`, 0 `tgm-*`, 11 badges, 3 spinners, 1 `form-switch`, 25 bare `btn-*`, 0
`table-responsive`, 0 `ListToolbar`, 0 `aria-*`**.

**It is the worst-measuring screen in the package**, and the two things that make it
worth drawing carefully are not in that list.

**First:** this is the screen the roadmap calls *"the one surface all four roles
share"* — and the server gates **every write on this screen** by a field the screen
never shows. Four roles share it, and it tells none of them which rows are theirs.

**Second:** it is called the Document Center and it is **the one document surface in
the module that cannot handle a file**. Its `Upload file` button opens a modal with two
text inputs: a file name, and a path you type by hand. The component that performs a
real upload — `components/files/FileSlot.vue`, `FormData` → `/api/method/upload_file`,
pick or drop — exists, works, and is used by a **different** screen.

**Third:** the screen holds **two** scopes and the product needs **three**. Today a
requirement is either `lot` or `tender`; the company's own documents — its licence, its
registration certificate, its tax clearance — have nowhere to live, so they would be
re-uploaded per lot. The council fixed the direction for half of this and deferred it
(**ADR-210**); the other half has never been written down. **That is now S1, and it is
the largest question in the package.**

**Scope.** `TenderDocumentsPanel.vue` and `TenderDocumentChain.vue` are **not** this
screen: both are rendered by `PoControlBoard.vue` (`:504`, `:508`) and belong to prompt
10. The panel appears here only as the mirror that produces S4 — it reads the same
endpoint and renders the same requirements, differently.

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

**This is the only screen all four open, and §6's S2 is about exactly that.** Read the
gate now, because it shapes every region below:

```
_require_any_tender_view(("director", "sourcing", "declarant", "logist"))   # to open
```

then, **per requirement row**, on upload · waive · remove
(`tender_documents.py:176-191`):

| the row's `role` | who may write it |
|---|---|
| `customs` | declarant + director |
| `logistics` | logist + director |
| `general` | sourcing + director |
| `finance` | sourcing + director |

**There is no row for the company scope**, because the company scope does not exist
yet. Who may replace an expired company licence is undefined — see S1.

## 3 · Nine mandates — not negotiable

1. **No links into Frappe Desk** — no `/app/...`, no `window.open`.
2. Tables are striped by default; never hand-add `table-striped`.
3. Money renders **only** through `MoneyInput`; decimal count **only** from
   `moneyFractionDigits(currency)`. *(No money on this screen.)*
4. Dates render **only** through `DateInput` + `formatDate()`; visible format
   `dd.mm.yyyy`.
5. **One** primary button per visual region. A second colour is not a second primary.
6. Amounts stay in **their own transaction currency**.
7. Status badges come **only** from the shared status map. No page-local colour map.
8. List screens use the shared `ListToolbar` with auto-apply — no Apply/Refresh
   button; the search placeholder ends with `⌘K`.
9. Loading is a skeleton, never a bare spinner.

**Measured: this screen breaks 4, 7, 8 and 9.** Eleven badges across **six** hand-written
colour scales (`bg-warning-lt`, `bg-green`, `bg-green-lt`, `bg-red-lt`,
`bg-secondary-lt`, `bg-purple-lt`, `bg-blue-lt`) and **zero** imports of the shared
status map. Two dates rendered by string slicing (`:144`, `:152`) instead of
`formatDate()`. A lot picker with no toolbar. Three `spinner-border`.

It keeps mandate 5, and it keeps mandate 1 in a way worth naming: the file download is
a **gated API URL** (`getGatedDownloadUrl`, `:497`), not a Desk link.

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.**
- **A disabled control carries its reason beside it.** On this screen the controls are
  **not disabled at all** — see S2. Two more reasons live in `:title` attributes
  (`:133`, `:85`).
- **The procurement policy numbers are server values** and never literal digits. *(No
  policy numbers on this screen; the readiness percentage is derived — see S4.)*
- **No fixed-width label, badge or nav item.** Worst-case growth **3.75×**. This screen
  has **six** fixed column widths in its editor (`:58-63`) and a `max-width: 200px`
  truncation on file names (`:149`).
- **String interpolation exists; plurals do not.** Three live workarounds:
  `file(s)` (`:81`), `lots` (`:241`), `files` (panel).
- **No new backend field, doctype or migration.** Raise it as a **question** instead.
  **S1 will tempt you and the answer is already in the repo** — read it before you
  reach for a new endpoint.
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

**This screen contains the package's clearest violation of the fifth state, and it is
one line of Python.** `_tender_documents.py:181`:

```python
readiness_pct = round(done_required / required * 100) if required > 0 else 100
```

**A lot with no checklist at all reports 100 %.** Not `0`, not `null` — a hundred
percent ready. Follow it through:

| situation | `missing_required` | `readiness_pct` | what the picker draws |
|---|---|---|---|
| every required document verified | 0 | 100 | green ✓ · full green bar |
| **no checklist has ever been written** | 0 | **100** | **exactly the same** |
| **that lot's requirements failed to load** | 0 | **0** | green ✓ · **0 % orange bar** |

The third row is a second bug in the same place: `tender_document_targets` wraps its
per-deal call in a bare `except Exception: summary = {}` (`tender_documents.py:470`),
so a failure yields `missing_required: 0` — a **green tick** — beside a 0 % bar that
contradicts it.

And the picker **sorts by those two numbers**
(`targets.sort(key=lambda r: (r["missing_required"], r["readiness_pct"]))`), so lots
with no checklist sort to the **top**, ahead of every lot with real work outstanding.

The four KPI cards do the same thing three more times: `summary?.total || 0`,
`summary?.required || 0`, `summary?.done_required || 0` (`:9`, `:16`, `:23`) all render
**`0`** when `summary` is `null` — which is its value while loading and after a failed
load. Three counters that say "zero" when they mean "not yet known".

**There is no error state anywhere in this file.** Three `catch` blocks (`:437`,
`:417`, and the two modal submits) each fire a toast and leave the screen as it was.

## 6 · The screen

**Document center.** Two screens behind one route today, chosen by whether `?deal=` is
in the query — and S1 asks for a third thing this route cannot express:

- **no `deal`** — a **lot picker**: 6 columns, every tender lot in the company, sorted
  by missing-required then readiness.
- **with `deal`** — the **checklist for that lot**: four KPI cards, then a requirements
  table in one of two modes (read / edit), then two hand-rolled modals.

The checklist merges two levels: **tender-master** requirements shared by every lot
under the master, and **lot-specific** ones. Only the lot rows are editable here
(`:355-358`); the server refuses a master row in this payload. **S1 adds a third level
above both**, with a different nature from either.

This screen is also the **sole writer of the checklist**, and that is recent and
deliberate. Its own comment (`:324-330`):

> *Until 2026-08-28 the only screen that could create a requirement row was
> `TenderIntake.vue` on the PO control board — a post-win screen editing the checklist
> through the intake JSON blob. That is why ADR-201 could not retire its edit rights.
> The writer lives here now: one surface owns the checklist.*

### S1 — two scopes exist and the product needs three

A requirement row's `scope` is parsed like this (`_tender_documents.py:69-71`):

```python
scope = str(item.get("scope") or "lot").strip().lower()
if scope not in ("lot", "tender"):
    scope = "lot"
```

**A `company` scope is not missing — it is silently rewritten to `lot`.** And
`list_tender_documents` merges exactly two lists, `master_reqs + lot_reqs`
(`tender_documents.py:82-87`). There is no third level and nothing that fails loudly
when one is attempted.

**The council fixed the direction for half of this and deferred the work.** ADR-210
(`docs/plans/2026-08-17-mikas-tender-workflow-formlari-tasarim-kurulu-karari.md:345`):

> *…belge gereksinim katalogu tender seviyesinde orada yaşıyor (`custom_tender_documents`)
> — yani tek-seviye mimarisiyle çelişen tek kalıntı burası. **Yön: katalog şirket
> seviyesine (ayarlar) taşınır**, Tender Master salt-okuma arşive döner. **Bu dilimde
> yapılmaz.***

That is about the **catalogue** — *which documents are required* — moving to company
settings. **It is not about the company's own document files**, and nothing in the
council record, the UZEX integration plan or `docs/decisions/` mentions those at all.

#### The three scopes, and why the third is not one more row

| scope | belongs to | how many | expires | who may write | consumed by |
|---|---|---|---|---|---|
| **company** | the firm | **one set** | **yes** | not defined anywhere | every lot, **and things outside tender** |
| **tender** | one tender master | one per tender | rarely | sourcing · director | every lot under it |
| **lot** | one deal | one per lot | no | the row's `role` | that lot only |

**The direction of reuse is the opposite of the direction of ownership.** A company
document is owned once and consumed everywhere; a lot document is owned per lot and
consumed once. So the company level is not another row in the same table — **it is a
library**, and the question is how a lot's checklist relates to it.

Draw **both** answers:

- **(a) reference rows** — every lot's checklist carries the company requirements as
  rows satisfied by the library: *"Company licence · ✓ from the company file · valid
  until 14.03.2027"*. The bid packet is assembled per lot and the person assembling it
  sees the whole list in one place. Costs: 13 lots × 5 company documents = **65 rows
  carrying 5 facts**, against a checklist capped at **40 rows**
  (`_REQUIREMENT_LIMIT`, `tender_documents.py:104`).
- **(b) a gate line** — the lot checklist stays lot-scoped, and company compliance is
  **one line** above it: *"5 company documents required · 4 valid · 1 expired"*, linking
  to the library. Costs: the bid packet's full list is no longer on one screen.

Trade-offs and a recommendation.

#### Expiry is a new severity, and it propagates

**No document in this module has a validity date today** — the requirement row carries
`label`, `required`, `role`, `date` (a *due* date), `done`, `waiver_reason`, `files`.
There is no `expires_at` anywhere in `tender_documents.py` or `_tender_documents.py`.

Company documents are precisely the kind that expire. That gives the design a state no
existing requirement has — **valid · expiring soon · expired** — and one consequence
the other two scopes never produce:

> **An expired licence makes every lot non-compliant at once.**

So a lot can be at 100 % on its own documents and still be un-biddable. Draw that: the
readiness figure and the company gate are two different facts, and the screen currently
has one number.

Say what "expiring soon" is measured against. **Do not invent a threshold** — the
procurement policy's numbers live in one file for exactly this reason
(`_procurement_policy.py`); a validity horizon belongs in the same place, as a question.

#### The identity question — say it, do not settle it

The third scope also holds documents with **no lot and no tender at all**: contracts,
insurance policies, records that are simply the company's. That breaks three premises
of this screen at once:

1. **The route.** `/tender/documents` is the wrong address for a company-wide surface.
2. **The gate.** Opening this screen requires one of four **tender** views
   (`tender_documents.py:461`). A company contract has no tender view that governs it,
   and the per-row role table (§2) has **no row for the company scope** — who may
   replace an expired licence is undefined.
3. **The entry point.** The lot picker assumes you arrive to work on a lot. A user
   coming to update the firm's insurance policy is not picking a lot.

**Draw the surface as it must look, and raise the route, the gate and the writer-role
as three questions.** They are architecture, not layout, and this prompt does not
settle architecture.

#### One measured fact that shapes every answer

**The file plumbing is deal-shaped.** `FileSlot`'s `attachedTo` prop is generic
(`FileSlot.vue:33`, default `"CRM Deal"`), but **all three call sites in the app pass
`'CRM Deal'`** — `TenderDocumentsPanel.vue:154`, `TenderMasterDrawer.vue:470`, and the
default. Nothing in Stabler attaches a file to a **Company**.

So a company document is not merely un-scoped in the checklist; there is no path in the
product that puts a file on the firm. Note it, design around it, and do not invent the
doctype.

**Where the catalogue would live, if asked:** `Stabler Settings` is a Single doctype
that already holds company-scoped tender configuration — `company_modules` and
`tender_stage_sla`, both `Table` fields. ADR-210 names "şirket seviyesine (ayarlar)" and
this is that place, with the shape already in use. **Mentioning it is in scope;
designing it is not.**

### S2 — the Document Center cannot upload a document

`Upload file` (`:157`) opens a modal (`:173`) with exactly two controls:

| label | control | placeholder |
|---|---|---|
| File name * | `<input type="text">` | `e.g. GTD_Customs_Declaration.pdf` |
| File URL / Path * | `<input type="text">` | `/private/files/GTD_Customs_Declaration.pdf` |

There is **no `<input type="file">` in this file.** The user types the name of a file
and the server path where it must already be sitting. Get the path wrong and
`_assert_local_file_url` (`tender_documents.py:121`) rejects it — after the modal was
filled in and submitted.

**The component that does this properly already exists and is used elsewhere in the
same module.** `components/files/FileSlot.vue`: pick or drop a file, `FormData` →
`/api/method/upload_file` with the CSRF token, then emit the saved
`{file_name, file_url}` — the exact pair this modal asks a human to type. It is wired
into `TenderDocumentsPanel.vue:157-166` with the same requirement key, the same deal,
and the same gated download endpoint.

So the fix needs no new endpoint and no new field. **The design question is what the
row looks like when the file control lives in it** — because that is a different
layout from a button that opens a modal:

- **(a) the file control in the row**, as the panel does it: every requirement is a
  slot, upload is drop-or-pick in place, no modal at all;
- **(b) the modal stays** and gains a real file control, keeping the row compact for a
  checklist that can run to dozens of rows.

Draw both. Note that (a) removes one of this screen's two modals and (b) keeps a
dialog this file hand-rolled — see §8.

### S3 — four roles share this screen and it shows no role

The write gate in §2 is enforced on **every** upload, waive and remove. The standard
set assigns the roles (`:344-352`):

| requirement | role | who may attach a file |
|---|---|---|
| Customs Declaration (GTD) | `customs` | declarant · director |
| Certificate of Origin | `customs` | declarant · director |
| CMR / Waybill | `logistics` | logist · director |
| Packing List | `logistics` | logist · director |
| Commercial Invoice | `finance` | sourcing · director |
| Technical Specification | `general` | sourcing · director |
| Price Offer | `general` | sourcing · director |

**The read view has five columns and `role` is not one of them** (Requirement · Scope ·
Status · Attached files / Waiver · Actions). The field appears only inside the
checklist **editor** (`:66-72`), which most of these users never open.

So a **logist** opens this lot, sees seven requirements, sees `Upload file` and `Waive`
on **all seven**, and is refused on five — after filling in a modal. The buttons are
never disabled, carry no reason, and the refusal arrives as a red toast.

**Forbidden is a per-row state on this screen, and no row can express it.** Design
that: which rows are mine, which are someone else's, and — since this surface is shared
precisely so the four roles can see each other's work — whose.

Do not solve it by hiding the rows. A declarant needs to see that the CMR is missing
even though attaching it is the logist's job; that is what "the one surface all four
roles share" means.

### S4 — the same data, two screens, two vocabularies

`TenderDocumentsPanel.vue` reads the **same endpoint** (`list_tender_documents`) and
renders the **same requirement set** on the PO control board. Measured differences:

| | this screen | the panel |
|---|---|---|
| upload | two text inputs in a modal | **`FileSlot`** — real, drop-or-pick |
| remove a file | **not possible** | `remove_tender_document` |
| waive | a modal | an inline box on the card |
| role | **not shown** | a badge **and** a filter |
| status | four **text** badges: Verified · Unverified tick · Missing file · Pending | **icon-only** badges; the word is in a `:title` |
| readiness | a big number, `text-success` at 100 % else `text-warning` | a grey monospace `%` badge |
| edit the checklist | **yes — sole writer** | no |
| layout | a table | a card grid |

Neither is wrong on its own. **Together they are two products.** A declarant who works
on the PO board and a sourcing officer who works here are looking at one dataset
through two vocabularies, and the one called the Document Center is the one that can do
less with the files.

State which vocabulary wins and why. Your answer constrains prompt 10, so make it
explicit rather than implicit in the drawing.

### An architectural problem you must show, not solve

**The lot picker is an N+1 with no bound.** `tender_document_targets` loops over every
tender deal in the company and calls `list_tender_documents` for each one — merging
master and lot requirements per deal, in Python (`tender_documents.py:463-483`). No
limit, no pagination, no toolbar, and the count in the header
(`{{ targets.length }} {{ t("lots") }}`, `:241`) is whatever the loop produced.

Draw the picker honestly — it is a list screen and mandate 8 applies — but do not
design the query.

## 7 · Data — use these rows, invent nothing

**The demo data creates no document requirements.** `seed_tender_demo.py` does not
contain the word `requirement`. So on a seeded site **every one of the 13 lots reports
`readiness_pct: 100` and `missing_required: 0`** — thirteen green ticks over thirteen
empty checklists, sorted to the top of the picker.

**Draw that as the loaded state of the picker.** It is not an edge case; it is what the
screen shows today on the only data anyone has.

Then draw the checklist for **`UTY-2026-4308`** · *Signal va aloqa boshqarmasi* with
the standard set applied, which is what `Add standard set` (`:87`) produces:

| requirement | scope | role | required | status | files |
|---|---|---|---|---|---|
| Customs Declaration (GTD) | Lot | customs | yes | **Missing file** | — |
| Certificate of Origin | Lot | customs | no | Pending | — |
| CMR / Waybill | Lot | logistics | yes | **Verified** | `CMR_4308.pdf` · 2026-08-24 |
| Packing List | Lot | logistics | no | Verified | `packing_4308.pdf` · 2026-08-24 |
| Commercial Invoice | **Tender Master** | finance | yes | **Unverified tick** | — |
| Technical Specification | Lot | general | yes | **Waived** | *"Protocol 14-B: the buyer supplied the specification"* |
| Price Offer | Lot | general | yes | Verified | `offer_4308.pdf` · 2026-08-19 |

Summary from that set: total **7**, required **5**, done_required **3**,
unverified **1**, readiness **60 %**.

### Four things in this data the design must not smooth over

1. **`Unverified tick` is a real state with a real history, and its explanation is in a
   `:title`** (`:133` — *"Legacy tick without verified file attachment"*). It means a
   row that a human ticked before the rule that completion is derived from files. The
   server keeps it deliberately (`_tender_documents.py:37`, *"preserved as `unverified`
   so legacy data stays visible"*). It is neither done nor missing, and it is the
   fifth state with a name.
2. **`Waived` renders as an `alert alert-warning` inside a table cell** (`:142`) —
   an alert box as a data cell, carrying the reason, the person and the timestamp. It
   is the only row that explains itself, and it does it in a component built for page
   notices.
3. **The waiver's `waived_at` and every file's `uploaded_at` bypass `formatDate()`.**
   `:144` prints the raw server string; `:152` does `uploaded_at.substring(0, 10)`.
   Mandate 4 wants `dd.mm.yyyy`; the screen shows `2026-08-24`. Two live sites.
4. **The tender-master row cannot be edited here and nothing says so.** `Commercial
   Invoice` is `scope: tender`; `startEditing` filters it out of the draft (`:356`), so
   opening the editor makes a required row **silently disappear** from a list the user
   is about to save. The footer note says *"Tender-level requirements are edited on the
   tender, not here"* (`:92`) — in the editor, after the row has already gone.

### The company set — invented as a proposal, and labelled as one

**No company documents exist in the product, in the seed, or in any council record.**
So unlike every other table in this package, the rows below are **not measured** — they
are a proposal, drawn so S1 has something concrete to argue about. Label them that way
on the artboard; do not present them as data.

They are the documents an Uzbek public-tender bid packet routinely asks the bidder for:

| company document | required by | validity | state to draw |
|---|---|---|---|
| Guvohnoma — state registration certificate | every bid | none | **valid** |
| Tax clearance (*qarzdorlik yo'qligi*) | every bid | **90 days** | **expires in 11 days** |
| Licence for the activity | activity-dependent | **1 year** | **expired 6 days ago** |
| Nizomnoma — charter | every bid | none | valid |
| Bank reference | some buyers | 30 days | not on file |

**Three things this set must make visible, and none of them exists today:**

1. **The expired licence blocks every lot at once.** Thirteen lots, one file. A lot
   sitting at 100 % on its own documents is still un-biddable. Two facts, and the screen
   has one number.
2. **"Expires in 11 days" is a state no requirement in this module can hold.** There is
   no validity field on a requirement row; the only date it carries is a *due* date.
3. **"Not on file" and "not required for this buyer" are different**, and the second is
   the fifth state again — a bank reference some buyers want is not measurable against a
   lot whose buyer has not asked.

**Do not pick the validity horizon for "expiring soon".** The procurement policy's
thresholds live in one file for exactly this reason (`_procurement_policy.py`); a
validity horizon belongs beside them, as a question.

**Dates:** `dd.mm.yyyy` via `formatDate()`. **No money on this screen.**

## 8 · Vocabulary

**Sections** — `ds-form-section`, **adjacent stack**: flush inside one bordered card,
divided by their own heads, no nested card frames. Settled on screen 01.

**Summary values** — `ds-kpi`, `-val`, `-cap`, `-note`. The four cards are
`card card-sm p-3 text-center` with an `h2` inside; the readiness card colours itself
**binary** (`=== 100 ? 'text-success' : 'text-warning'`, `:28`), so 99 % and 3 % look
the same.

**Progress against a threshold** — `ds-meter` / `-seg` / `-txt`
(`stabler-modernist.css:337-342`), or `ds-progress` for a continuous bar. The picker
uses a raw Bootstrap `progress` with an inline `height: 5px; min-width: 60px` and the
same binary colour (`:270-272`).

**Tables** — `ds-table` inside a mandatory `table-responsive` wrapper; numeric cells
`ds-td-num`. **Measured: `ds-table` 0, `table-responsive` 0, `card-table` 2** — and the
picker's table is 6 columns wide with no wrapper at all.

**Status** — `ds-chip[data-tone]` through the shared status map. **Measured: 11
hand-written badges, 6 colour scales, 0 imports of the map.** Two of them are pure
colour (`bg-green-lt` with a `✓`, `bg-red-lt` with a count) with no word.

**Scope** — today two values rendered as two coloured badges (`bg-purple-lt` for
tender, `bg-blue-lt` for lot, `:120-122`). S1 makes it **three**, and the third is not a
peer of the other two: company documents are a library the other levels draw on. Decide
whether three scopes are three tones of one construct or whether the library needs its
own, and say why.

**Validity** — **nothing in the layer expresses it and nothing in the module has it.**
A company document is *valid* · *expiring* · *expired*, and the third propagates to
every lot. `ds-sev` carries severity and `ds-chip[data-tone]` carries status; whether
expiry is one of those or a fourth thing is a decision this screen has to make, because
it is the first screen in the package where **one row's state invalidates another
screen's total**.

**Files** — `ds-file-list[data-mode="edit"|"read"]` with `-row`, `-name`, `-meta`.
Settled on screen 01 as **D14**, and this screen is the reason the decision has two
modes: its files are server facts with a **gated download** and an **upload date**,
where the intake drawer's are being composed before a save. `read` mode is this
screen's mode.

**Dialogs** — the layer has `ds-drawer` with `-backdrop`, `-head`, `-title`, `-close`,
`-body`, `-foot`, and sizes settled on screen 02 (542 default, 760 `[data-size="lg"]`).
**This file hand-rolls two modals instead** (`:173`, `:205`):
`class="modal modal-blur fade show d-block"` with an inline
`style="background: rgba(0,0,0,0.5)"` and `tabindex="-1"`. No `role="dialog"`, no
`aria-modal`, no `aria-labelledby`, no focus trap, no Escape handler, no separate
backdrop element — a `<div>` that looks like a Bootstrap modal without being one.
**That is a fifth dialect**, after `ds-*`, `tgm-*`, bare Bootstrap and `rfq-*`. Decide
what these two dialogs are; if they become drawers, say what happens to the module's
z-index question (10.6, still open).

**Loading** — `SkeletonRows` mounts **in place of** the table body, never inside it.
The read table does this correctly (`:113`). The **three** `spinner-border` sites
(`:50`, `:197`, `:229`) are all inside buttons and must become label swaps plus
`aria-busy="true"`.

**Toggles** — the checklist editor's `Required` column is a `form-check form-switch`
(`:70`), the module's only one. Screen 03 met the same control on a policy-exception
toggle. One answer for both.

**Actions** — `ds-btn`, at most one `ds-btn--primary` per region. Two reasons currently
live in `:title` attributes (`:85`, `:133`) and must move beside their controls.

**Forbidden here:** `class="badge bg-*"`; `spinner-border`; `form-switch`; `card-table`;
`alert` as a table cell; a raw `progress` bar; `substring(0, 10)` on a date;
`<tr role="button">`.

## 9 · Responsive

Draw at **1280**, **992** and **640** px.

- The **picker** is 6 columns with no `table-responsive`.
- The **read checklist** is 5 columns, one of which holds a stack of file rows with a
  `max-width: 200px` truncation (`:149`).
- The **editor** is 6 columns with **five fixed pixel widths** (`:58-63`: 220 · 110 ·
  160 · 150 · 120 · 60 px = 820 px of fixed track) carrying translated headers against
  3.75× growth, plus a `<select>`, a `DateInput` and a text input inside them.
- The four KPI cards are `col-md-3`, so they collapse at **768** — a different
  breakpoint from the layer's **640**.

The editor at 640 px is the problem on this screen: six columns of live controls,
820 px of them fixed. Nothing may scroll the page horizontally.

## 10 · Deliverables

1. **Both** answers to S1 — reference rows and a gate line — each drawn at 1280, with
   the company set above, and a recommendation.
2. The **three scopes together** on one lot: company · tender · lot, with the expired
   licence visible and its effect on the lot's biddability stated.
3. The **company library** as its own surface: five documents, their validity states,
   and what it says when a document is not required for this buyer.
4. The **picker** at 1280 / 992 / 640, loaded with the thirteen-green-ticks state that
   the real data produces.
5. The **checklist** at 1280 / 992 / 640, read mode, with the seven rows above.
6. The **editor** at 1280 and 640, with the tender-master row's disappearance made
   visible before it happens.
7. All five states — including the **error** state the file does not have anywhere, and
   the **not measurable** state for `readiness_pct` when there is no checklist.
8. **Both** answers to S2, each drawn, with trade-offs and a recommendation.
9. S3: the role made visible, and every row that this user cannot write shown as such —
   for **two different users** (a logist and a sourcing officer), same lot, same data.
10. S4: a stated answer for which vocabulary wins, with the panel's card grid and this
    screen's table side by side.
11. The four status badges redrawn from one vocabulary, `Unverified tick` included, with
    its explanation out of the `:title`.
12. The waiver row: reason, person and date, out of the `alert` component.
13. The two hand-rolled modals resolved into the layer, or a stated argument for
    keeping them.
14. Every question your design raised, listed — **including the route, the gate and the
    writer-role for the company scope**, which this prompt raises and does not settle.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` as text, pulls the decision expressions out and
runs them — `stabler/public/js/tests/sourcingAwardPanel.spec.js`.

Every number below was measured from `TenderDocuments.vue`,
`stabler/api/tender_documents.py` and `stabler/api/_tender_documents.py` on 2026-09-01:

| # | Criterion | Before | After |
|---|---|---|---|
| K0a | **A third scope exists and is not silently swallowed.** `_tender_documents.py:69-71` rewrites anything outside `("lot", "tender")` to `"lot"`; a design that adds `company` without that parser changing produces rows that lie about what they are | 2 scopes | 3, or a stated reason for keeping 2 |
| K0b | **A company document's validity is a rendered state, not a date to read.** No requirement row carries an expiry today; *valid* · *expiring* · *expired* are drawn, and the horizon is a server value, never a literal | 0 | asserted |
| K0c | **An expired company document invalidates every lot, visibly.** A lot at 100 % on its own requirements does not present as ready when the licence behind it has lapsed | 1 number | 2 facts |
| K1 | **The screen can attach a real file.** `<input type="file">` or `FileSlot` is present; the two text inputs at `:186-192` are gone | 0 | 1 |
| K2 | **Every row shows its `role`, and a row this user cannot write is not offered a write control.** `role` appears in the read view, not only in the editor | 0 | asserted |
| K3 | **No page-local colour map.** Eleven hand-written badges across six scales; zero imports of `getStatusBadgeClass` | 11 / 0 | 0 / 1 |
| K4 | **No `<tr role="button">`.** `:257` also contains its own `<button>` at `:278` — nested interactive content | 1 | 0 |
| K5 | **No spinner.** Three sites (`:50`, `:197`, `:229`) become label swaps plus `aria-busy="true"` | 3 / 0 | 0 / 3 |
| K6 | **Every date goes through `formatDate()`.** `:144` prints a raw server string; `:152` slices one with `substring(0, 10)` | 2 raw | 0 |
| K7 | **`readiness_pct` of an empty checklist is not drawn as 100 %.** The design distinguishes *complete* · *no checklist* · *could not load* | 1 rendering | 3 |
| K8 | **The KPI cards never print `0` for an unknown value.** `summary?.x \|\| 0` at `:9`, `:16`, `:23` | 3 | 0 |
| K9 | **A failed load is a state, not a toast.** No error branch exists in the template today | 0 | asserted |
| K10 | **Every reason is beside its control, not in a `:title`.** `:85` and `:133` are the live sites | 2 | 0 |
| K11 | **The dialogs are the layer's, or the argument for keeping them is written down.** Two hand-rolled `modal modal-blur` divs with no `role="dialog"`, no `aria-modal` and no focus trap | 2 / 0 | decided |
| K12 | **The editor drops no required row silently.** `startEditing` filters `scope === 'tender'` out of the draft (`:356`); the user is told before the list changes under them | silent | asserted |
| K13 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | = region count |
| K14 | **The picker is a list screen.** `ListToolbar` with auto-apply and a `⌘K` placeholder; the count is not asserted to be a total | 0 | 1 |
| K15 | **Regression guards — these are already right and must stay so.** `SkeletonRows` in both tables, `EmptyState` in both, `DateInput` in the editor, the **gated download URL** rather than a Desk link, both modals reloading the list on success (`await load()`), and the tender-master row staying **read-only** on this screen | asserted | unchanged |

**K15's last two items are the ones a redesign is most likely to lose.** This screen is
the checklist's sole writer (ADR-201/205) and it reloads after every write — two things
screens 03 and 07 do not do. A rebuild that makes uploading pleasant and stops
reloading has traded a real defect for a worse one.

**K0a–K0c are not testable against today's file, and that is deliberate.** They are the
three things a three-scope design must be able to claim; a design that draws a company
library without them has drawn a fourth place to lose a document. If your answer to S1
is (b) — a gate line rather than reference rows — say which of the three it satisfies
where, because the gate line is the only thing carrying them.

State plainly which of these your design satisfies, and name anything it cannot.
