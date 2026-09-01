# 09 · Document center

**Source:** `stabler/public/js/pages/tender/TenderDocuments.vue` — 520 lines,
**0 `ds-*`, 0 `tgm-*`, 11 badges, 3 spinners, 1 `form-switch`, 25 bare `btn-*`, 0
`table-responsive`, 0 `ListToolbar`, 0 `aria-*`**.

**It is the worst-measuring screen in the package**, and none of the four things that
make it worth drawing carefully are in that list.

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
(**ADR-210**); the other half has never been written down. That is **S1**.

**Fourth, and the largest question in the package:** the screen is named a *centre* and
it is not one. A document here is not a record — it is a filename and a URL appended to
a JSON blob inside one deal. The write endpoint is already a **bind**, not an upload
(it refuses to run unless the file exists), and the download gate already checks each
binding independently, so **the same file may be reused across lots today and the
server will handle it correctly**. What is missing is everything above the plumbing:
no way to pick a document you already own, no way to see where one is used, no shelf
to arrange them on. That is **S2**, and it is the reason this screen is worth
redrawing rather than restyling.

**Scope.** `TenderDocumentsPanel.vue` and `TenderDocumentChain.vue` are **not** this
screen: both are rendered by `PoControlBoard.vue` (`:504`, `:508`) and belong to prompt
10. The panel appears here only as the mirror that produces S5 — it reads the same
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

**This is the only screen all four open, and §6's S3 is about exactly that.** Read the
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
  **not disabled at all** — see S3. Two more reasons live in `:title` attributes
  (`:133`, `:85`).
- **The procurement policy numbers are server values** and never literal digits. *(No
  policy numbers on this screen; the readiness percentage is derived — see S5.)*
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

### S2 — a document is not a record, and everything else depends on making it one

This is the largest question in the prompt. Read S1 first: it establishes that three
scopes are needed. This one establishes that **there is no thing to put in them.**

**What a document is today.** Open the write endpoint and read what it actually does
(`tender_documents.py:215-256`):

```python
def upload_tender_document(deal, requirement_key, file_name, file_url, company=None):
    ...
    file_url = _assert_local_file_url(file_url)
    if not frappe.db.exists("File", {"file_url": file_url}):
        frappe.throw(_("No uploaded file found for {0}.").format(file_url), ...)
    ...
    r["files"].append({
        "file_name":   file_name,
        "file_url":    file_url,
        "uploaded_by": frappe.session.user,
        "uploaded_at": now(),
    })
    r["done"] = True
```

**It does not upload.** It refuses to run unless the `File` already exists, and then it
appends four strings to a list. The name of the endpoint is the last thing in this
module you should trust: `upload_tender_document` is a **bind** operation, and has been
one all along.

Three consequences, each measured:

**One — reuse already works on the write path.** Nothing in that function ties the
`file_url` to this deal, this requirement, or this company. `_assert_local_file_url`
(`:121-143`) checks the *shape* of the URL — starts with `/files/` or `/private/files/`,
contains no `://`, no `..`, no CR/LF. That is an open-redirect guard, not an ownership
check. The same licence PDF can be bound to thirteen lots today and the endpoint will
accept all thirteen.

**Two — the read path was written for reuse too.** `download_tender_document`
(`:419-445`) does not ask "does this user own the file". It asks "is this `file_url`
listed on *this* requirement of *this* deal", and refuses otherwise with a
`PermissionError`. Thirteen bindings are thirteen independent gates. The permission
model for a shared library is **already correct** — nobody has to design it.

**Three — and yet there is no library.** Bindings live in two JSON blobs:
`Tender Master.custom_tender_documents` is a `Long Text` field
(`patches/v76_tender_master_documents.py:30`) and `CRM Deal.custom_tender_intake` is the
same shape (`patches/v37_deal_tender_intake.py:28`). Not a child table. Not a doctype.
No index. `tender_documents.py` looks up `"File"` exactly once, by `file_url` existence
(`:227`), and **never sets `attached_to_doctype` / `attached_to_name`** — the one place
in the API layer that does is `service.py:216`, for Issues. A tender document is
therefore a *string pair inside a JSON blob inside one deal*. The same PDF bound to
thirteen lots is thirteen unrelated string pairs that happen to spell the same thing.

**The asymmetry to design against:** the binding is one picker away from doing
everything asked of it. The *library* does not exist at all. Do not solve this by
inventing a doctype — draw the surface that makes the gap obvious and name what it needs.

#### The two directions, which are one operation

Reuse has two entry points and they must be drawn as **the same act seen from two
sides**, not as two features:

| From | The user is holding | And wants |
|---|---|---|
| **Library → tender** | a document | to satisfy a requirement with it |
| **Tender → library** | a requirement | to satisfy it with a document |

The second is the missing button. Today a requirement row offers `Upload file` and
nothing else (S3) — so the only way to satisfy a requirement with a document the firm
already has is **to upload a second copy of it**, which creates a second `File`, a
second `uploaded_at`, and no relationship between them. Every duplicate in this system
was created by the absence of one button.

Draw both. Then answer the harder question: **is the picker the same component in both
directions, or two?** Coming from the library the user has already chosen the document
and is choosing a target; coming from the requirement the target is fixed and the
document is being chosen. One is a target picker, one is a document picker, and they
may share nothing but a modal frame. Say which you built and why.

**Multi-bind is the real case, not an edge case.** A tender with four lots asks for the
same company licence four times. Coming from the library, the target chooser must let
the user tick four requirements at once, or the feature has replaced one upload with
four picks and saved nobody anything. Draw the multi-select target list, and draw what
it says afterwards — *"Bound to 4 requirements in 2 lots"* — because the confirmation is
the only place the user learns that reuse happened rather than copying.

#### The facets — three groups, and only one of them is honest

Zafar asked for the library to be organised "her türlü" — chronologically, by tender,
and so on. The data answers this unevenly, and the design has to show which shelf is
real. Sort them yourself before drawing:

**Real today** — derivable from the bindings that exist:

| Facet | Field | Note |
|---|---|---|
| By tender / lot | `deal`, `tender_master` | the natural spine; matches how the data is stored |
| By role | `role` | four values: `customs`, `logistics`, `finance`, `general` (`_tender_documents.py:19`) |
| By requirement | `key` / `label` | free text — see the warning below |
| By status | derived `done` / `unverified` / waived | already a vocabulary on this screen |
| By person | `uploaded_by` | never rendered anywhere today |
| By name | `file_name` | the only text a user can search; client-side only |

**Real but not what it says** — draw it, and draw the trap:

*Chronological.* `uploaded_at` is stamped by `now()` **at bind time**, not at file time.
Bind the same 2019 licence to a new lot this morning and it sorts to the top of "most
recent". A chronological shelf built on this field is a shelf of *bindings*, not
documents — and for a library that is the wrong axis. Show the timeline and label its
axis honestly: **"last used"**, never "uploaded". If you want a true document date, say
so as a requirement; do not quietly relabel a field that means something else.

**Not present at all** — these are the ones that make it a library rather than a list:

- **Document type.** There is no such field. A passport is only "the thing that
  satisfied the requirement named *passport*", per deal, as free text. Two lots spelling
  the same requirement differently produce two shelves. Grouping by type is therefore
  grouping by a string somebody typed.
- **Validity / expiry.** Established as missing in S1, and it is the facet with
  operational teeth: *"what expires in 30 days"* is the one query that prevents a lost
  bid, and it is the one query this data cannot answer.
- **Owner scope.** S1 again — the company shelf has nowhere to live.
- **Version.** Nothing links last year's licence to this year's. A renewed document is
  an unrelated file with a similar name.

Draw the facet rail with **all four groups visible and visibly different**: real facets
live, the chronological one labelled for what it is, and the missing ones present as
what they are — a stated requirement, not a greyed-out control pretending to be a
feature. A disabled filter is a lie about what exists.

#### What "smart" is allowed to mean

Smart here means **derived, not guessed.** Every shelf in this library must be
computable from a field: counted, grouped, sorted, filtered. Nothing in this design may
depend on inferring a document's type from its contents or its filename — that is a
different product, it fails silently, and it fails on a document that decides whether a
bid is legal. Where a shelf needs a fact the data does not carry, the answer is to name
the missing field, not to infer it.

The one genuinely derived thing you *should* draw, because it needs no new field and it
is the reason a library beats a folder: **usage**. From the bindings alone you can
compute, for any document, *where else it is used* — the back-reference that does not
exist today in either direction. A document row that reads
*"used in 4 requirements across 2 tenders"*, expandable to the list, is the single
strongest argument on the canvas for making the document the primary record. Draw it.

#### The cost, stated once so the design is honest about it

Computing any of this today means loading every deal's JSON and parsing it — there is no
query. `tender_document_targets` (`:449`) lists **deals**, not documents; there is no
endpoint anywhere that lists documents. At the thirteen-deal scale in §7 that is
harmless. At five hundred it is not, and the library is exactly the screen where the
count grows without bound while everything else in the module stays lot-sized.

You are not asked to solve this. You are asked to **draw a library whose shape does not
collapse when the list is long**: a facet rail that narrows before it renders, a default
view that is not "everything ever", and a paging or windowing story stated rather than
assumed. Screen 05 shipped a silent truncation at 200 reported as the total — the same
mistake here would hide a document the firm owns, which is worse than hiding a bid.

**One state you must draw and could not guess at:** the download gate re-validates the
URL on every request, with a comment saying why — rows written before the upload-side
check existed may carry an **external** URL, and those are refused rather than
redirected to (`:441-443`). So a document can be listed in the library and be
**un-openable**. That is a fifth status, it is invisible today, and it is precisely the
kind of thing a library surfaces and a per-lot checklist never will.

### S3 — the Document Center cannot upload a document

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

### S4 — four roles share this screen and it shows no role

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

### S5 — the same data, two screens, two vocabularies

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

### The reuse this data already implies — draw these numbers

S2 needs a library with something in it. Build it from the two tables above rather than
inventing a third: the thirteen lots plus the standard set produce the duplication on
their own, and the numbers are the argument.

| document | what it is | bound to | the point it makes |
|---|---|---|---|
| `licence_2025.pdf` | activity licence *(company, proposed)* | **13 lots** — every one | one expiry, thirteen consequences |
| `guvohnoma.pdf` | registration certificate *(company, proposed)* | **13 lots** | the clearest case for binding over copying |
| `CMR_4308.pdf` | waybill for one shipment | **1 requirement** | genuinely per-lot; not everything is shared |
| `offer_4308.pdf` | price offer | **1 requirement** | per-lot, and per-round — it will be superseded |
| `invoice_4308.pdf` | commercial invoice | **1 tender-master requirement** | the scope that is neither company nor lot |

Two things to draw from this and nothing else:

- **The usage column is the library's spine.** *"Used in 13 requirements across 13
  lots"* against the licence, and *"Used in 1"* against the waybill, in the same column
  — the contrast is what tells a user which documents are the firm's and which belong to
  a shipment, **without a scope field existing**. It is derived, it is honest, and it is
  the strongest thing on the canvas.
- **Reuse is not always right.** `offer_4308.pdf` is per-lot *and* per-round; a library
  that invites the user to bind last month's price offer to this month's lot has
  automated a mistake. Draw what the picker shows to warn about that, or state that it
  does not and why.

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

**Facets and filtering (S2)** — the module already has a filter vocabulary and this
screen has none of it. `ListToolbar` is the settled answer for search plus filters plus
`⌘K` (mandate 8), and it is **`0` on this file**. Use it before inventing a rail; if the
library genuinely needs a persistent vertical facet rail that a toolbar cannot express,
say why, and say what happens to it at 640 where a rail has no room. **Every facet must
show its count**, because a facet with no count is a filter you cannot judge before
clicking — and the counts are the only way a user sees that thirteen bindings are one
document.

**Usage / back-reference (S2)** — new, and there is no component for it. It is a
**count with a disclosure**, not a badge: badges on this screen carry status severity
(`ds-status`), and a usage count is not a severity — a document used thirteen times is
not thirteen times as urgent. Pick a form that cannot be mistaken for one, and make the
expanded list say *where*, in the module's own words: tender code, lot, requirement.

**Bind vs upload** — two verbs, one result, and the user must be able to tell them
apart before clicking. `Upload` creates a file; `Use existing` creates a reference.
Mandate 6 allows one primary per region, so they cannot both be primary: decide which
one the product prefers and let the layout say so. **Naming matters more than usual
here** — the server calls binding "upload" (`upload_tender_document`) and that name is
the reason the duplication exists. Do not inherit it into the UI.

**Forbidden here:** `class="badge bg-*"`; `spinner-border`; `form-switch`; `card-table`;
`alert` as a table cell; a raw `progress` bar; `substring(0, 10)` on a date;
`<tr role="button">`; a **disabled facet** standing in for a field that does not exist;
the word *upload* on a control that binds an existing document.

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
- The **library** (S2) is new and therefore has no measured width to inherit. It carries
  more columns than anything else on this screen — document, usage, last used, role,
  status — beside a facet rail. It is the hardest thing in the package to fit at 640,
  and it is also the view a buyer's deadline will be checked on from a phone.

The editor at 640 px is the problem on this screen: six columns of live controls,
820 px of them fixed. Nothing may scroll the page horizontally.

## 10 · Deliverables

1. **Both** answers to S1 — reference rows and a gate line — each drawn at 1280, with
   the company set above, and a recommendation.
2. The **three scopes together** on one lot: company · tender · lot, with the expired
   licence visible and its effect on the lot's biddability stated.
3. The **company library** as its own surface: five documents, their validity states,
   and what it says when a document is not required for this buyer.
4. **The library** (S2) at 1280 / 992 / 640: the five documents of §7's reuse table,
   the usage count against each, and the facet rail — with the real facets live, the
   chronological one **labelled "last used"**, and the missing ones present as stated
   requirements rather than disabled controls.
5. **Both directions of binding**, drawn as two flows:
   **(a)** from the library — one document, a multi-select target list, and the
   confirmation that says *"Bound to 4 requirements in 2 lots"*;
   **(b)** from a requirement row — `Use existing` beside `Upload`, the document picker,
   and the row after it is satisfied. Then a **stated answer** to whether these are one
   component or two.
6. **The usage back-reference expanded**: `licence_2025.pdf` showing its thirteen
   bindings, in the module's own words (tender code · lot · requirement), at 1280 and
   640.
7. **The library when it is long.** The same view at a scale the module will reach —
   with the paging, windowing or narrow-by-default behaviour visible. Screen 05's silent
   truncation at 200, reported as the total, is the failure to design against.
8. The **picker** at 1280 / 992 / 640, loaded with the thirteen-green-ticks state that
   the real data produces.
9. The **checklist** at 1280 / 992 / 640, read mode, with the seven rows above.
10. The **editor** at 1280 and 640, with the tender-master row's disappearance made
    visible before it happens.
11. All five states — including the **error** state the file does not have anywhere, and
    the **not measurable** state for `readiness_pct` when there is no checklist — **plus
    the un-openable file**: a binding whose URL the download gate refuses (`:441-443`).
12. **Both** answers to S3, each drawn, with trade-offs and a recommendation.
13. S4: the role made visible, and every row that this user cannot write shown as such —
    for **two different users** (a logist and a sourcing officer), same lot, same data.
14. S5: a stated answer for which vocabulary wins, with the panel's card grid and this
    screen's table side by side.
15. The four status badges redrawn from one vocabulary, `Unverified tick` included, with
    its explanation out of the `:title`.
16. The waiver row: reason, person and date, out of the `alert` component.
17. The two hand-rolled modals resolved into the layer, or a stated argument for
    keeping them.
18. Every question your design raised, listed — **including the route, the gate and the
    writer-role for the company scope**, and **every field S2 needs that does not
    exist** (document type, validity, version, owner scope), each written as a
    requirement with the shelf it unlocks. This prompt raises them and settles none.

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
| K0d | **A document is a thing, and the design says what identifies it.** Today identity is `file_url` — two bindings of the same file are related only because the strings match. Whatever the design treats as the document's identity is named, and it is not the filename | none | named |
| K0e | **A requirement can be satisfied from what the firm already owns.** A control beside `Upload` that binds an existing document. The endpoint already accepts this: `upload_tender_document` requires the `File` to exist and appends a reference (`:227`, `:239-245`) | 0 paths | 2 |
| K0f | **Binding is not called uploading.** No control that attaches an existing document uses the word *upload*, whatever the server's method is named | 1 verb | 2 |
| K0g | **Every document shows where it is used.** A count derived from the bindings, expandable to tender · lot · requirement, and rendered as a count rather than a status badge | 0 | asserted |
| K0h | **The chronological shelf is labelled for what it sorts.** `uploaded_at` is stamped by `now()` at bind time (`:243`), so it orders bindings, not documents; the axis says *last used* or the design states the new field it needs | mislabelled | asserted |
| K0i | **A facet that has no field behind it is not a disabled control.** Document type, validity, version and owner scope are absent from the data; each appears as a stated requirement or not at all | — | asserted |
| K0j | **The library's length is designed for.** The count grows without bound while every other list on this screen is lot-sized, and there is no document endpoint to page — the narrowing, windowing or paging behaviour is drawn, not assumed | 0 | asserted |
| K0k | **An un-openable binding is visible.** The download gate re-validates the URL and refuses legacy external ones (`:441-443`); a document listed but not retrievable does not present as available | invisible | asserted |
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

**K0a–K0k are not testable against today's file, and that is deliberate.** K0a–K0c are
the three things a three-scope design must be able to claim; a design that draws a
company library without them has drawn a fourth place to lose a document. If your answer
to S1 is (b) — a gate line rather than reference rows — say which of the three it
satisfies where, because the gate line is the only thing carrying them.

**K0d–K0k are the library.** They divide cleanly and the division is the point: **K0e
and K0f cost nothing** — the server already binds by reference and gates each binding
independently, so both are UI decisions available today. **K0g and K0h cost a query and
a rename**, both derivable from data that exists. **K0i, K0j and K0k are admissions** —
a missing field, an unbounded list and a refused URL — and the criterion for each is
that the design shows them rather than papering over them. A library that quietly
disables four filters, renders every document it can find, and lists a file nobody can
open has met none of the three, while looking finished.

State plainly which of these your design satisfies, and name anything it cannot.
