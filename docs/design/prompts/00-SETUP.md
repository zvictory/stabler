# 00 · Setup — how to use this folder

**Do not paste this file into Claude Design.** It is the operator's note. The files
`01-*.md` … `18-*.md` are the ones that get pasted, one per session.

---

## What already exists on the web side

A Claude Design project called **Stabler DS** (`caf64c8f-1325-422e-9262-524639167628`)
holds **Phase A — the component language**: `styles.css`, six `woff2` faces,
`delta.css`, `foundations/{color,type,severity}.html`,
`components/{forms,actions,states,table}.html`, `readme.md`, `thumbnail.html`.

That is buttons, fields and states. **There are no screens in it.** This folder is
Phase B: the 16 routes and 2 drawers, drawn as screens.

Keep the Stabler DS project open in another tab while you work — every prompt here
refers to its vocabulary, and none of them re-explain it in full.

### Stabler DS is not the Modernist project

An older Claude Design project (`stabler_modernist_design_guide.md`) used a red mono
palette. **Stabler DS does not.** The palette is Tabler's blue
(`stabler-modernist.css:7-11`), and the design system is built *on top of* Tabler,
not instead of it. If a generated screen comes back red-and-mono, the wrong project
is selected.

---

## Why the prompts repeat themselves

Zafar's choice, 2026-09-01: **one independent prompt per screen.** Each file restates
the product, the four roles, the nine mandates, the i18n limits and the five states,
so any prompt can be run on its own, in any order, in a fresh session. The repetition
is the feature — Claude Design has **no access to this repository**, so every
constraint, every class name and every data row has to travel inside the prompt.

Nothing in these prompts is invented. Lot numbers, buyers, suppliers, amounts and
dates all come from `stabler/maintenance/seed_tender_demo.py`; class names come from
`docs/design/2026-09-01-asama-a-tender-bilesen-dili.md` §1.2–1.3; the rules come from
`.claude/rules/10-frontend.md` and `docs/design/PROMPT_design_tender_modulu.md` §5, §9.

---

## Order, and the gate

The order follows ADR-209 as corrected by ADR-301 — migration starts at the drawer,
because that is where the third dialect lives.

| # | screen | why here |
|---|---|---|
| 01 | Tender intake drawer | the entire third dialect: 0 `ds-*`, 46 `tgm-*` sites / 15 classes; sole writer of intake per ADR-201 |
| 02 | Tender CRM kanban | the drawer's home; the module's `ds-*` reference screen (107 sites) |
| — | **↑ Verification gate — PASSED 2026-09-01** | The language was approved on 01 and 02 before the rest were drawn. The gate is spent; it does not re-arm |
| 03 | Sourcing workspace | comparison table + award panel; 1039 lines, 0 `ds-*` |
| 04 | Quotation entry drawer | drawer grammar, second pass |
| 05–08 | RFQ list · new · detail · print | three inside the layer with no vocabulary; **only the print letter is outside it** |
| 09 | Document center | the one surface all four roles share — **three scopes: company · tender · lot**, a **library with two-way binding** — and the only screen whose **forbidden state is per row** |
| 10 | PO control board | post-award; **one route, six components, 1,696 lines, 0 `ds-*` in any of them** — the module's money is decided here, and the layer has no tab component |
| 11–12 | Customs queue · Logistics board | read-only projections; drag-to-advance is forbidden — and **~77 % the same file**, so 11 draws the projection and 12 draws only the difference |
| 13–18 | Operations desk · Director board · Overview · Process flow · My tenders · Contract board | the boards |

**The gate after 02 was not optional** — getting the language wrong and then drawing
eighteen screens in it is the expensive failure this ordering exists to prevent. It was
put to Zafar with both canvases drawn, and passed on 2026-09-01.

---

## Running one prompt

1. Open the Stabler DS project in Claude Design.
2. Copy one file from the `PASTE BELOW THIS LINE` marker to the end.
3. Paste. Let it draw.
4. Compare the result against the file's own **Deliverables** list — that list is the
   acceptance criterion, not a suggestion.
5. Anything the design had to guess at should come back as a **question**, not as a
   silent decision. A prompt that produces no questions on an ambiguous screen has
   probably been answered by invention.

---

## What has been drawn — the verification gate

Eight canvases exist. The first two **were** the gate the table above stops at: the
language was approved on them before the rest were drawn in it.

| # | canvas | artboards | what it settles |
|---|---|---|---|
| 01 | [Tender intake drawer](https://claude.ai/code/artifact/3d45f238-495f-4832-a25f-eac7c301820e) | 10 | single form (not stepped) · adjacent stack · `ds-file-list[data-mode]` (D14) |
| 02 | [Tender CRM kanban](https://claude.ai/code/artifact/564c73b0-6e7a-49ab-b6c9-87c7db56fb2c) | 10 | S1(a) drawer width → **760** via the existing `[data-size="lg"]` · S1(b) six orphans → **one** new component · one accessibility rule for the card and the row |
| 03 | [Sourcing workspace](https://claude.ai/code/artifact/477c7af9-3734-4986-a842-dc215c56e76e) | 8 | S2 currency → a **third documented exception**, narrowed from 9 sites to one column · nine comparison columns → **seven** · a table row is **not** a region |
| 04 | [Quotation entry drawer](https://claude.ai/code/artifact/16250885-0340-4e6b-a6ca-9421ae5f00d1) | 6 | S3 a failed load is a **state, not a toast** · the module's **reference patterns**, named so the other fourteen can copy them |
| 05–08 | [RFQ family](https://claude.ai/code/artifact/623be708-1d87-4213-a274-b5670a75d4f3) | 8 | `ds-* = 0` does **not** mean outside the layer · the layer has **zero** `@media print` rules · the demo seed creates **no RFQ at all** · 07's `Mark as sent` writes a record nothing can read back |
| 09 | [Document center](https://claude.ai/code/artifact/0ac0448d-6295-4657-9d0e-c3d321b19af6) | 9 | **two scopes exist and the product needs three** (S1, added 2026-09-01) · a document center that **cannot take a document** · the write gate is **per row, by role**, and no row shows one · an empty checklist reports **100 % ready** · a **fifth dialect**: two hand-rolled modals |
| 10 | [PO control board](https://claude.ai/code/artifact/97034dcd-ea7f-481e-a02d-31f1feabdce9) | 8 | the editor's **landed total omits charges it is displaying** (right in the database, wrong on screen) · the layer has **no tab component** · the chain **keys on a link it never renders** and prints a currency that is not the document's · **S6 settles both deferred rulings**: the documents panel becomes one table, `TenderIntake` becomes read-only |
| 11 | [Customs queue](https://claude.ai/code/artifact/5497548e-a529-41a9-9c14-1a703cc78774) | 6 | **six screens blank themselves every sixty seconds** and six toast on a failed background tick — the module's liveness vocabulary, drawn here · the same PO is orange on one board and plain on its twin · `DeclarantQueue` and `LogistBoard` are **~77 % the same file** · the card says *"3 docs missing"* and the three names are in the payload |

Each canvas carries its own **not chosen** artboards rather than deleting the rejected
option — the stepped intake on 01, the 542 px drawer on 02, the per-bid conversion on 03,
both readings of the two denominators on 05, the card grid and the editable intake on 10. A decision whose alternative has been erased
cannot be re-examined.

**05–08 are one canvas, not four.** Zafar's standing choice is an independent prompt per
screen and that is unchanged — there are four prompt files. But the four screens are one
doctype seen four ways, and the family-level questions (one status vocabulary, one
toolbar, one print stylesheet, one denominator for "answered") have to be decided once and
seen together.

The working files (`*.dc.html`, `canvas.json`) live in the session scratchpad, not in the
repo: they are re-seeded from source on every edit and a 2.6 MB payload per canvas has no
business in git. **The canvas URL is the artefact**; the prompt file is how it was produced.

### What the canvases raised that the prompts did not

- **The card title slot is empty in the data** — `c.label || c.name`, and nothing sets a
  deal label, so a card renders the same string twice. Screen 01 hit the same gap from the
  other side ("no tender title on record"). Two screens now depend on one missing field.
- **`Seen` and `Priced` have no Uzbek string.** Five lanes translate, two do not.
- **There is no keyboard path to move a card between lanes** — today or after the redesign.
- **Migrating the intake drawer to `ds-drawer` moves it from z-index 1050 to 41** — from
  above the Bootstrap modal band to below it. That is 10.6, shown and left open.

**From 05–08, and each one changes something outside its own screen:**

- **`ds-* = 0` does not mean "outside the layer".** `stabler-modernist.css` carries **344**
  `.stbl-ds`-prefixed rules that restyle bare Bootstrap. A screen inside `<TenderPage>` is
  already wearing the layer's clothes without speaking its vocabulary — which is why nobody
  migrated these files: **the cost was never visual.** In the whole tender module only
  `RfqPrint.vue` and `BidPricing.vue` are genuinely outside it, exactly the two the council
  named. This corrects how 03's and 05–08's zero counts should be read; it does not change
  any decision already taken on them.
- **The layer contains zero `@media print` rules.** It has never been asked to print, so
  the RFQ letter invented a fourth dialect (`rfq-*`, 20 classes, its own type ramp in
  points). Deciding what a Stabler document looks like on paper is new work — prompt 08.
- **`seed_tender_demo.py` never writes the string "Request for Quotation".** Every
  quotation the sourcing workspace compares is an answer to a question that was never
  recorded. 05 opens empty, 07 and 08 have no reachable record at all. That is a finding
  about the product, not the seed — it is the gap these four screens exist to close.
- **10.1 is sharper than "no server-side pagination".** `list_all_rfqs` **caps** at 200
  (clamped to 500, `sourcing.py:806`) and returns `len(rows)` as the count, which the
  toolbar renders as the total. And `search` matches the **document id only**, so the lot
  and the supplier columns cannot be searched. Silent truncation reported as a total.
- **A write with no read.** `mark_rfq_sent` inserts a `Communication` keyed to the RFQ;
  `get_rfq` returns nothing about it, so no screen in the SPA can show it. **The only
  surface where that record is visible is Frappe Desk — the one place mandate 1 forbids
  linking to.** The backend question is stated in prompt 07 and left open.
- **Four global `@page` rules ship at once** — A5 twice, A4 twice, in unscoped `<style>`
  blocks, all live because `router.js` has 208 static imports and 0 lazy ones. One page
  size wins per print job by bundle order. Recorded as a bug, not designed.

**From 09:**

- **A fifth dialect.** After `ds-*`, `tgm-*`, bare Bootstrap and `rfq-*`, the document
  center hand-rolls two Bootstrap-shaped modals (`:173`, `:205`):
  `class="modal modal-blur fade show d-block"` with an inline backdrop colour, no
  `role="dialog"`, no `aria-modal`, no focus trap, no Escape handler.
- **The fourth state is not always a page state.** Every screen before this one could
  draw *forbidden* as one alert. Here the server gates **each requirement row** by its
  `role` field (`tender_documents.py:176-191`), the read view does not show that field,
  and a logist is offered fourteen write controls of which four work. Refusal arrives as
  a red toast **after** a modal has been filled in.
- **`readiness_pct` returns 100 for a lot with no checklist** —
  `_tender_documents.py:181`, `if required > 0 else 100`. Combined with the picker's
  sort, a lot nobody has set up sorts **above** every lot with real work outstanding.
  A per-deal `except Exception` (`tender_documents.py:470`) produces a third rendering:
  a green tick beside a 0 % bar.
- **The seed gap is not confined to the RFQ family.** `seed_tender_demo.py` creates no
  requests for quotation. **Half of this was overtaken by `ef649cf` / `58f3cbc`** — the
  seed now writes **six** document requirements per deal, with roles (`:571-597`), each
  as a `status: "ready"` tick with **no file**, which the parser records as
  `unverified`. So the checklist is populated and every row on it is an unverified
  claim. Measured while writing prompt 12.
- **The same endpoint feeds two screens with two vocabularies.**
  `TenderDocumentsPanel.vue` (inside screen 10) reads `list_tender_documents` too, and
  has the real file control, the role badge and a role filter that screen 09 lacks —
  while screen 09 has the words that the panel puts in `:title` attributes. Prompt 09
  asks for a ruling, because prompt 10 inherits it.

### The scope Zafar reopened — 2026-09-01

Screen 09 was drawn once with two scopes and **redrawn with three**, on Zafar's
objection that the document center must carry the company's own documents and not only
a tender's. Checked against the record before acting; the answer is that **the council
discussed half of it**:

- **ADR-210** (`docs/plans/2026-08-17-mikas-tender-workflow-formlari-tasarim-kurulu-karari.md:345`)
  fixed the direction — *"katalog şirket seviyesine (ayarlar) taşınır"* — and deferred
  the work behind Tender Master's retirement (16 consumers, "ayrı program"). That is the
  **catalogue**: which documents are required.
- **The company's own document files** — licence, `guvohnoma`, tax clearance,
  `nizomnoma` — appear in **no** council record, no plan and no decision. Nor do
  contracts and insurance policies with no tender at all.

Measured while answering, and all of it new to this package:

- **`scope` accepts two values and silently rewrites the rest**
  (`_tender_documents.py:69-71`): `if scope not in ("lot", "tender"): scope = "lot"`.
  A third level is not missing from the parser — it is quietly renamed by it.
- **`list_tender_documents` merges exactly two lists** — `master_reqs + lot_reqs`
  (`tender_documents.py:82-87`).
- **No document anywhere in the module has a validity date.** A requirement row carries
  a *due* date and nothing else, so *valid · expiring · expired* is a state the layer
  has never had to express — and an expired company licence invalidates **every lot at
  once**, which makes this the first screen where one row's state breaks another
  screen's total.
- **The file plumbing is deal-shaped.** `FileSlot`'s `attachedTo` prop is generic
  (`FileSlot.vue:33`) but all three call sites pass `'CRM Deal'`
  (`TenderDocumentsPanel.vue:154`, `TenderMasterDrawer.vue:470`, and the default).
  **Nothing in Stabler attaches a file to a Company.**
- **`Stabler Settings` is the home ADR-210 names** — a Single doctype already holding
  company-scoped tender configuration as `Table` fields (`company_modules`,
  `tender_stage_sla`).

Three questions the prompt raises and deliberately does not settle: the **route**
(`/tender/documents` is wrong for a company-wide surface), the **gate** (opening the
screen needs a tender view; a company contract has none, and the per-row role table has
no company row), and the **writer role** for an expired licence.

### The library Zafar asked for next — 2026-09-01

Immediately after the three scopes landed, Zafar asked for the document center to be
*organised every way — chronological, by tender — a smart library, with integration in
both directions: from the library into a tender, or from a tender entry back to the
document.* That is now **S2**, and the measurement changed what the prompt could ask
for:

- **`upload_tender_document` does not upload.** It refuses to run unless the `File`
  already exists (`tender_documents.py:227`) and then appends four strings —
  `file_name`, `file_url`, `uploaded_by`, `uploaded_at` — to the requirement's list
  (`:239-245`). It is a **bind**, and its name is the reason nobody knew.
- **Reuse already works on the server, in both directions.** Nothing ties a `file_url`
  to a deal; `_assert_local_file_url` (`:121-143`) guards the URL's *shape*, not its
  ownership. And `download_tender_document` (`:419-445`) gates on "is this file listed
  on *this* requirement of *this* deal" — so N bindings are N independent checks. The
  permission model for a shared library is already correct and nobody has to design it.
- **What is missing is the record.** Both stores are JSON blobs — `Long Text`
  (`patches/v76_tender_master_documents.py:30`, `patches/v37_deal_tender_intake.py:28`).
  No child table, no doctype, no index. `tender_documents.py` touches `"File"` exactly
  once, by URL existence, and **never sets `attached_to_doctype`** (the only API-layer
  site that does is `service.py:216`, for Issues). A document is a string pair inside
  one deal's blob; the same PDF on thirteen lots is thirteen unrelated string pairs.
- **`uploaded_at` is bind time, not file time** (`now()` at `:243`). A chronological
  shelf built on it sorts *bindings*. The prompt makes the design label that axis
  **"last used"** rather than quietly relabelling the field.
- **Four facets have no field at all**: document type, validity, version, owner scope.
  The prompt forbids drawing them as disabled controls — each is a stated requirement
  or it is absent.
- **`tender_document_targets` (`:449`) lists deals, not documents.** There is no
  endpoint that lists documents, so any shelf is an N+1 scan over every deal's JSON.
  Harmless at thirteen; the library is the one view in the module whose count grows
  without bound.
- **A binding can be un-openable.** The download gate re-validates the URL on every
  request because legacy rows may carry an external one (`:441-443`). Listed, and
  refused. A fifth status, invisible today.

The asymmetry is the finding, and it is what makes this a design task rather than a
backend one: **the binding is one button away from doing everything asked of it; the
library does not exist at all.** The prompt therefore forbids inventing a doctype and
asks instead for the surface that makes the gap legible — K0d–K0k in 09's acceptance
table, split into what costs nothing (K0e, K0f), what costs a query (K0g, K0h) and
what is an admission the design must show rather than hide (K0i, K0j, K0k).

### From 10 — 2026-09-01

**The route is not the screen.** `/tender/po-control` renders **six components and
1,696 lines**, and none of them uses a single `ds-*` class. The roadmap row said
"765 lines"; that is the shell.

- **`upload`-shaped naming struck twice in this package.** Screen 09's write endpoint
  is a bind called `upload_tender_document`. Screen 10's totals sum `l.amount`, a field
  named as if the client owned it while the **server** is its only writer
  (`tender.py:319-321`, *"the one chokepoint both reads and writes pass through"*). Both
  defects are a name promising a thing the code does not do.
- **The landed total is right in the database and wrong on screen.** `editorCharges`
  sums `l.amount`; for a foreign-currency line that is `null` when newly added and
  **stale** when edited, while `convertedPreview(l)` prints the correct figure in the
  same cell. `saveEditor` was already fixed for exactly this asymmetry — the save filter
  carries the comment *"Filtering on `amount` alone silently dropped every such line on
  save"* — and the totals were not. The stored plan is correct; the number the vendor is
  chosen by is not.
- **The module's own rule, obeyed at the line and broken at the total.**
  `tender_landed_math.converted_amount` returns `None` rather than a number when a rate
  is unusable, because both fallbacks *"read as CHEAP and hand the tender to the wrong
  vendor"*. The client mirrors it per line. The footer adds the line in as zero.
- **The layer has no tab component.** `ds-tab` **0**, `nav-tabs` **0** in
  `stabler-modernist.css`. `TenderWorkspaceTabs` is raw Bootstrap with **one** `aria-`
  attribute, no keyboard model, and the active tab computed **twice** — once by the
  parent, once by itself — joined with `||`, so a future divergence renders two active
  tabs rather than failing.
- **The finance tab is the module's only role-conditional region done right**: the
  server omits the `finance` key, the client derives the tab list from its absence, and
  nothing is hidden by CSS or by a client-side role check. Every other screen in this
  package hides things worse. Copy it.
- **`TenderDocumentChain` keys on a link it never renders.** Every receipt and invoice
  row carries `purchase_order` / `sales_order`; the component uses it in its `:key` and
  draws three flat lists. It also prints `grand_total` — the document's **own-currency**
  figure — with the **tender's** currency, while `row.currency` and `base_grand_total`
  are both sent and unused. Mandate 6, one word away.
- **After a failed load the screen says "Pick a tender deal"** while the deal is in the
  picker above it. Three states — never picked · loading · failed — collapse into two
  empty states, and loading is an `EmptyState` with `icon="ti-loader"`, a fourth
  spinner-substitute nobody else invented.
- **Two server refusals the client never prevents**, and one names a hidden field: a
  customs line cannot carry a currency, and the currency select is `v-if`-ed away for
  customs while a **type** change does not clear it.
- **The hand-rolled modal is now three files** (09 has two, 10 has one) — and 10's is
  `modal-xl`, wider than any drawer the layer defines. 10.6, the z-index question, is
  reopened and still not settled.
- **The roadmap has eighteen slots and this route alone holds five surfaces.**
  `BidPricing.vue` is drawn in prompt 10 because nothing else would ever draw it, and
  `TenderIntake.vue` only appears because ADR-304 asked. **Whether prompts 11–18 have
  the same problem is worth checking before they are written.**

**What 10 settles for other prompts:** `TenderDocumentsPanel` and screen 09 become
**one table** — the panel wins on `FileSlot`, the role and the filter, and loses on
layout, because a card grid destroys the row-to-row comparison a readiness checklist
exists for. And **ADR-304** is answered as *read-only intake beside a route to the
drawer that owns it*, which satisfies "connected or removed" without creating a second
writer against ADR-201.

### Coverage audit — 2026-09-01

Prompt 10 raised the question and this answers it: **the eighteen slots map exactly onto
the module.** Sixteen `/tender/*` routes (eighteen `path:` entries less two redirects)
plus the two drawers, which are not routes:

| slots | surfaces |
|---|---|
| 01, 04 | the two drawers — `components/TenderMasterDrawer.vue`, and the quotation drawer **inside** `SourcingWorkspace.vue` |
| 02, 03, 05–10 | one route each |
| 11–18 | one route each: `/tender/customs` · `/logistics` · `/desk` · `/portfolio` · `/overview` · `/flow` · `/my-tenders` · `/board` |

**Screen 10 was the exception, not the pattern.** Measured across 11–18: every one of
them imports **only** `TenderPage` plus `EmptyState` / `SkeletonRows` — shared
infrastructure, not screen-sized components. Nothing there resembles 10's four hosted
surfaces (`TenderIntake` 365, `BidPricing` 287, `TenderDocumentsPanel` 186,
`TenderDocumentChain` 48).

**Three gaps, in descending size:**

1. **`TenderFunnel.vue` — 745 lines, no slot, two hosts.** Bigger than
   `PoControlBoard`'s shell. Rendered by `DirectorBoard.vue:192` (slot 14) and
   `TenderOverview.vue:119-125` (slot 15). Without a decision it gets drawn twice, by
   two prompts, differently.
   **Two measurements settle where it goes.** It is the module's most layer-native
   component — **64 `ds-*`, 0 `badge bg-`** — so it needs extension, not migration. And
   its `mode` prop **has exactly one value in the whole app**: `DirectorBoard` omits it
   (default `"full"`), `TenderOverview` passes `mode="full"` explicitly, and both pass
   `pipeline-strip`. The `v-if="props.mode === 'full'"` at `:425` guards a branch that
   is always taken. **A mode switch with one mode.**
   **Decision: draw it once, in prompt 15**, where it is the whole screen. Prompt 14
   then carries only the difference — `DirectorBoard` passes `:selected` and controls
   the phase, `TenderOverview` does not. The dead `mode` prop belongs to whichever
   prompt draws it, as a finding.
2. **The shell is in no prompt.** `TenderPage.vue` (29) and `TenderNav.vue` (87) render
   on **all sixteen routes**, and `TenderPage.vue:12` is where `.stbl-ds` is applied —
   the single line that puts every tender screen inside the layer. Neither is named in
   any prompt. Small, and load-bearing enough that it should be said out loud
   somewhere rather than assumed sixteen times.
3. **`/tender/board` renders a file in the sales folder.** `pages/sales/SalesOrderBoard.vue`
   (192), reached from a tender route, using `TenderPage` and the shared
   `tenderBoardFilters` composable. Slot 18 covers it; the prompt has to say whose
   screen it is before it redesigns it.

**Also confirmed: no dead files remain** — see the corrected bullet above.

### From 11 — 2026-09-01

**The largest finding in the package so far is not a screen finding, and it was found on
the package's best-behaved screen.** `DeclarantQueue.vue` is the only file measured to
date that obeys mandate 9 outright — **0 `spinner-border`, 3 real `SkeletonRows`** — with
real empty states, SPA-internal routing and a header comment stating its own read-only
contract. The defect surfaced there precisely because nothing else was in the way.

- **Six screens replace themselves with a skeleton every sixty seconds.**
  `useAutoRefresh(fn)` re-runs the page's own `load()`, which sets `loading = true`,
  which every one of these templates answers with `v-if="loading"`. Measured, all six:
  `DeclarantQueue`, `LogistBoard`, `DirectorBoard`, `MyTenders`, **`RfqList`** and
  **`RfqDetail`**. Nothing distinguishes a first paint from a background tick.
- **And six toast on a failed background tick.** The composable documents *"Swallows
  errors — an auto-refresh must never surface as an error toast"*, and its `catch {}`
  only catches what `refreshFn` throws. Every consumer's `load()` catches its own error
  and calls `toast.error(...)`, so it never throws and the swallow never runs. **The
  composable is careful and every consumer defeats the care.**
- **The composable is otherwise right and must not be redesigned away.** It pauses
  entirely while the tab is hidden — a backgrounded board issues zero requests — and
  fires once on reveal. A countdown ring or a polling indicator that keeps ticking in a
  hidden tab trades a correct behaviour for a decoration.
- **Six screens are live and none of them says so.** No timestamp, no staleness signal,
  no change indication anywhere in the module. **Prompt 11 draws the liveness vocabulary
  for all six**, in the page head's `ds-meta` slot beside the filters — the other thing
  that determines what the user is looking at. The staleness line doubles as the retry,
  which is how mandate 8's ban on a Refresh button is honoured rather than argued with.
- **Prompt 05 is owed a correction.** `RfqList` was drawn without catching either half.
  Noted in that file.

**Two boards, one file.** `DeclarantQueue.vue` (351) and `LogistBoard.vue` (346) have
**identical import lists** and differ in **80 and 75 lines** — roughly **77 % the same
file**. What is shared is the whole projection: load, filters-from-URL, view toggle, both
branches, the lane board, the item card and the table view. What differs is the API
method, five lanes versus six, the labels and the card's metrics.

- **And the copies have already drifted on something that matters.** `DeclarantQueue`
  ignored the server's derived `risk` and re-derived it inline with a hard-coded `7`,
  **twice**, so the same PO rendered differently on the two boards.
  **Corrected while writing prompt 12 — the cause stated here was wrong.** The two
  endpoints derive `risk` from **two different comparisons**: `declarant_queue` from
  days-to-ETA (three tiers), `logist_board` from `eta > delivery` (two tiers), and the
  latter paints the **deadline**, not the ETA. They are two questions sharing a field
  name; giving `logist_board` a `warn` tier would invent a third meaning rather than
  reconcile anything. The observable symptom stands, the diagnosis did not. Prompt 12
  §S1 carries the measurement.
- **The client half is fixed and on prod** (`26481f1`, deployed as `746ece2`):
  `DeclarantQueue` reads `risk` through one `etaClass()`. The number `7` now lives in
  **three** places, all server-side — `tender.py:1651`, `:2279`, `:3125`.
  `LogistBoard` never had one and has no day arithmetic at all.
- **Decision, matching the `TenderFunnel` one:** prompt 11 draws the **read-only lane
  projection** once, as a named component; prompt 12 draws only what is genuinely
  different — six lanes in the same grid, which is **~193 px** of lane at 1280 against
  235 for five.

**The payload knows more than the board.** `missing_customs_docs` — the list of *which*
documents are missing — rides every row and is rendered nowhere; the card shows only the
count, so the declarant is told a number and must open screen 09 to learn the noun.
`risk` and `due` are read by neither twin. `stage`, `status` and `lane` are **one value
under three names**. `customs_declaration_status` — *Red channel* — is a `:title`. And
`out.append(row_item)` plus `lanes[key]["items"].append(row_item)` put the **same object
in the payload twice**, so `rows` and the union of the lanes are identical sets that the
client then filters separately. The last one is a server change: raised, not solved.

**Two more that generalise:**

- **A failed first load renders as an empty queue.** `catch` fires a toast and does not
  touch `data`, so the initial `{rows: [], lanes: {}}` makes the count zero and the
  screen says *"No active customs declarations or won lots in the pipeline."* A
  declarant reads that as *nothing to do today*. Same family as screen 10's *"Pick a
  tender deal"*, and worse: this one is a plausible sentence.
- **The empty state is half in the component and half beside it** — an `EmptyState` plus
  a loose `<p>` carrying the explanation. **Every screen in the package will ask whether
  that sentence belongs inside the component's contract**; 11 raises it and does not
  settle it.

### From 12 — 2026-09-01

**Prompt 12 draws a delta, and the delta turned out to be bigger than the lane count.**
The ordering decision (11 draws the projection, 12 draws only the difference) held; what
did not hold is the assumption that the difference was cosmetic.

- **The twins' `risk` fields answer different questions** — the correction above. This
  is the first time in the package that a finding recorded from one screen was refuted
  by measuring its twin, and it is an argument for the per-screen measurement discipline
  rather than against it.
- **Four of the six lanes cannot be reached on a seeded site.** *Booking*, *In Transit*,
  *Border Crossed* and *Delivered* are all selected by a **Freight Booking**; the
  doctype exists (`stabler/stabler/doctype/freight_booking`) and `seed_tender_demo.py`
  never creates one. The board a logistician opens is two populated lanes and four
  permanently empty ones. Same class as 05's *the seed creates no RFQ at all* — the
  surface exists, the record it projects does not.
- **And nothing in the module creates a Freight Booking.** Raised as a product question
  in the prompt, not answered with a schema.
- **The board's only money column is zero in every row.** `transport` sums landed
  charges of type `transport` **and `loading`** (`tender.py:2384`) under a column headed
  *Transport*; the seed writes only `{"type": "customs"}` charges, so the sum is `0`,
  and `v-if="item.transport"` erases the line entirely. **The third `name promising
  what the code does not do` in this package**, after 09's `upload_tender_document` and
  10's `l.amount`.
- **`freight_booking_status` is a `:title`.** The literal value the lane chain branches
  on is reachable only by hovering a badge (`:244`) — the same defect as 11's *Red
  Channel*, on a field with more consequence: the channel described a row, this one
  places it.
- **A missed ETA is invisible here.** `late` compares the ETA to the *deadline*, never
  to today, so a purchase order six days past its ETA with nothing received draws as
  on time — while the same row is red on the customs board. The seed contains exactly
  that row (*Hebei Rail Parts*). **Neither board asks whether the ETA has passed.**
- **`per_received` is thresholded away.** The server sends `received` as
  `per_received >= 100`; a 40 %-delivered shipment is indistinguishable from one that
  has not left the factory. The value exists and the boolean discards it.
- **The fix that shipped between prompts widened the gap.** The twins were ~77 %
  identical when the package began; `26481f1` moved them to **90 differing lines here
  and 75 there**. Fixing one copy of a duplicated screen makes the duplication worse,
  which is the concrete argument for L17's single component.

**The data tables in prompts 10 and 11 do not match the seed.** Prompt 11 §7 lists six
purchase orders against lots `UTY-2026-4291` and `UTY-2026-4277`, which **do not exist**
in `seed_tender_demo.py`, and vendors — *Alfa Kabel MChJ*, *Shenzhen Hualing Ltd*,
*Uz-Tex Logistics*, *Termiz Metall*, *Andijon Kabel*, *Guangzhou Metal Co* — **none of
which the seed creates**. The seed writes **five** purchase orders across the **two won
lots** (`UTY-2026-4314`, `UTY-2026-4315`), from five vendors. Prompt 10 §7 draws the PO
board for `UTY-2026-4308` — a real lot the seed leaves at the *sourcing* stage, with no
purchase order against it — using vendors the seed also does not create.

**This is not the same as the RFQ family's tables.** 05–08 had no records to draw from
and said so in the prompt itself: the seed creates no RFQ, which is the finding those
screens exist to expose. 10 and 11 had real rows available and used invented ones
instead, which contradicts the rule at the top of this file.

**Both §7 sections were rewritten on 2026-09-02**, on Zafar's instruction, by executing
`po_control_board` · `_po_lane` and `declarant_queue`'s lane and risk logic against the
seed. Each carries a line saying what it replaced. Checked across the whole folder while
correcting them: **every lot number in every prompt now resolves to a seeded lot**, and
the invented vendors appear nowhere else — 03's comparison table was already using the
five real ones. The scope of the defect was exactly 10 and 11.

**The rewrite changed findings, not just names**, which is why the canvases matter:

- **10's KPI figure moves from `Received 40 %` to `26,2 %`**, and three findings are new
  — every seeded PO is a **draft** (`docstatus 0`, deliberate, `seed_tender_demo.py:392`)
  so three of four lanes never fill; `delayed` is unreachable because it requires
  `docstatus == 1`; and **no seeded PO is in a foreign currency**, so **S1 — the landed
  total that omits the charge printed above it — cannot be reproduced on demo data at
  all.** The four-line multi-currency plan now appears as a **labelled constructed
  example**, because the seed writes exactly one customs line per order.
- **11's board is four cards in one lane and one in another**, with three lanes
  unreachable (*Declared* and *Under Inspection* need a Customs Declaration the seed
  never creates; *Ready for GTD* needs zero missing customs documents, which never
  happens). Its *Released* row is painted `warn` because urgency knows nothing about the
  lane — the old table made the same point with a red *Released* row that does not exist.
- **`cheapest` lands on the two purchase orders with no charges recorded**, in both
  deals. The seed writes no landed charges when the customs amount is zero, so the
  vendor nobody has costed wins — the module's own warned-about failure
  (*"reads as CHEAP and hands the tender to the wrong vendor"*), reproduced by its own
  demo data.

**Both canvases were redrawn on 2026-09-02** and republished to their existing URLs, so
the *not chosen* artboards and the settled rulings survive. 11's board is now four cards
in one lane, one in another and three drawn as unreachable; its twin artboard no longer
carries the refuted drift diagnosis. 10's board is one populated lane, and its
four-line multi-currency plan is now labelled a **constructed case** rather than demo
data, because the seed cannot produce one.

**And a product ruling from Zafar, 2026-09-02, that bounds prompt 12:** the logistics
and customs figures are entered directly at the sourcing stage, only to compute the bid
price — so the surface must stay simple. Confirmed in code: `BidPricing.vue` takes the
whole import cost as **one field** (`landed_goods`, *"Landed cost (goods + import)"*),
and the structured per-type charge list lives on the Purchase Order, after award. The
consequence is written into prompt 12: the four unreachable lanes are **not** a hole to
fill by designing a freight-booking flow, and the prompt now forbids proposing one.

### The pre-win costing rule — 2026-09-02, and it is a council item

Zafar, immediately after the 10/11 redraw: **in the pre-win stage there are no customs,
logistics or real landed-cost calculations.** Fixed landed-cost items are entered onto
the incoming quotations; the sourcing officer works them out alone, from experience,
without a declarant, a customs broker or a logistics colleague, so a sales quotation can
go out quickly. *"Kurul bunu tekrar görsün."*

Measured while recording it, and it moves the problem:

- **The pre-win path already exists and it is on the quotation, not the order.**
  `LandedChargesEditor.vue` (253 lines) is mounted in `SourcingWorkspace.vue` and writes
  `custom_landed_charges` on the **Supplier Quotation** through
  `update_quotation_landed`. Six charge types, recoverable VAT correctly excluded from
  the landed total. The comparison already ranks on landed and already knows when the
  estimate is incomplete.
- **Prompt 03 contradicted itself about where that figure comes from.** Its §5 table said
  *"the quotation's own"*; its §7 said the column is empty *because no purchase order
  exists*. The second is wrong — `get_quotation_landed` never touches a purchase order —
  and it is corrected.
- **The missing piece is the word *fixed*.** No preset, template, standard set or
  per-company default exists anywhere; `addChargeLine()` appends a blank line defaulting
  to *Freight*. An officer comparing five bids types five copies of the same four
  charges under deadline. The rule says this must be quick and it is the slowest thing
  on the screen.

**The council question**, written into prompt 03: what is a *fixed* landed-cost item — a
per-company default set, a per-tender set applied to every bid, or a per-supplier
memory — and what does applying one to five quotations look like as **one gesture**.

This also draws the line the later prompts were missing: **pre-win is a costing
estimate, post-win is an operational record.** 10's per-type charge editor and 12's
six-lane journey board are both post-win, and 12 is already forbidden from designing
anything that feeds its unreachable lanes.

---

## Decisions taken while writing these prompts — 2026-09-01

Two of them close a contradiction between the council record and Phase A. Both were
put to Zafar rather than resolved silently.

### 1 · The file chip — `ds-file-list`, one component with two modes

ADR-302 said `tgm-file-chip/-list/-name` become a **new `ds-*` component**, and ADR-303
called it *"the only known real gap"*. Phase A §1.2 and §4.2 item 11 said the opposite:
file attachment is the **same token list** as multi-select, no new component, because
*"drawing them apart would produce a third dialect"*.

Measured, both are half right. The document center's files are server facts it cannot
edit (`TenderDocuments.vue:78` — *"Files and waivers are server facts: this editor cannot
touch them"*): **no delete**, a **gated download** link, an **upload date** instead of a
size, and status chips the drawer has no equivalent for (`ready` / `Missing file` /
a legacy tick with no verified attachment). The drawer, by contrast, is composing files
before a save.

**Decision:** one component, `ds-file-list[data-mode="edit"|"read"]`. Same row anatomy;
the trailing slot, the meta column and the status chip switch by mode.

**Consequence, and it is a real one:** Phase A §1.2 and §4.2 item 11 now carry a claim
that no longer holds. That correction is owed to the Phase A document and has not been
made yet.

### 2 · The section frame — adjacent stack

ADR-302 says converting `tgm-section` to `ds-form-section` is a **visual** decision:
*"the designer must approve this, the engineer must not do it silently."* Both were drawn
on screen 01's canvas.

**Decision: adjacent stack.** Sections sit flush inside one bordered card, divided by
their own heads. Denser, more of a long form on screen, and it is what the drawer already
does — so the migration changes class names without changing what the user sees. Separate
cards remain drawn on the canvas, marked "not chosen".

### 2b · S7 — one form, not a stepped flow

**Decision: single form.** A three-step alternative was drawn and rejected; it stays on
the canvas as the record rather than being deleted.

The case that motivated it is real and survives the decision: a user holding the tender
notice who does not yet know the item list. The single form answers it by leaving **items
unrequired at save** — only buyer, title and submission deadline block. If items ever
become mandatory, S7 reopens rather than getting worked around.

### 3 · Phase A's `<tr role="button">` count is one short

Phase A §1.3 records **one** live violation (`TenderDocuments.vue:257`). Re-measured with
a multi-line-aware search there are **two** — the second is `TenderCrm.vue:535`, where
the attribute sits four lines below the opening tag and a single-line grep cannot see it.
Also owed to the Phase A document.

---

## Council requirements every prompt must carry

From the council's own output contract, not from the screens:

- **ADR-306 — an acceptance section per screen.** Observable criteria, each moving a
  number measured from source, turned into tests that **read the `.vue` as text**, never
  mount it. The repo's working pattern is `stabler/public/js/tests/sourcingAwardPanel.spec.js`.
  Measured: 17 specs mention `@vue/test-utils`, **0** call `mount(`.
- **`RfqPrint.vue` must gain a `.stbl-ds` ancestor. `BidPricing.vue` already has one** —
  and the earlier claim that both lacked it was **wrong. Corrected 2026-09-01 while
  writing prompt 10.** The measurement counted the string `stbl-ds` *in each file*; what
  matters is the render tree. `RfqPrint` is a **route component**
  (`router.js:302`, `/tender/rfq/:name/print`), so its `.print-wrapper` root mounts at
  the router outlet with nothing above it — genuinely outside, and it also has no `ds-*`,
  no layer tokens and no print rules to inherit (prompt 08's S1, where the ancestor is
  one of two drawn answers rather than a foregone conclusion). `BidPricing` has **one
  call site**, `PoControlBoard.vue:369`, inside `<TenderPage>`'s default slot — and
  `TenderPage.vue:12` is `<div class="tender-page stbl-ds">`. Slot content renders at the
  slot's DOM position, so `BidPricing`'s root card **is** a descendant of the layer today.
  **This is the second time in this package that "the file does not write the class" was
  read as "the component is not under it"** — the first was `ds-* = 0`, corrected at
  screen 05. Grep the render tree, not the file.
- ~~Four dead files are out of scope and must not be prettified~~ — **stale, corrected
  2026-09-01 by the coverage audit.** `TenderCrmWrapper`, `TenderExecutionFlow`,
  `TenderExecutiveKpis` and `TenderTrendChart` **were already deleted** (Phase A §10.5,
  Zafar's decision); measured **0** `.vue` files today. The Python references that made
  them look alive are **deletion guards**, not blockers:
  `self.assertFalse(os.path.exists(path), "... should be deleted")`
  (`test_tender_dashboard_spa.py:143-144`) and
  `self.assertNotIn("TenderCrmWrapper", router)` (`test_tender_master_board_spa.py:50-53`).
  Nothing is left to delete; three test modules exist to keep it that way. The old note
  described work that had already happened.
- **`SourcingWorkspace`'s horizontal overflow closes, and a spec asserts it.** Measured:
  `table-responsive` **0**, `card-table` **2**, `ds-` **0**. Prompt 03.
- **ADR-304 — `TenderIntake.vue` is an orphan.** No route; embedded only at
  `PoControlBoard.vue:368`. The council said it is *either connected or removed, but not
  left orphaned*. Prompt 10 carries it as a question.

---

## The decision that left this folder — SETTLED 2026-09-01

**The third currency exception (screen 03, S2) edits `.claude/rules/10-frontend.md`,
not a component.** That file governs all sixteen remaining screens, so the paragraph is
*drafted* on the canvas and *not* adopted. Measured state today:
`SourcingWorkspace.vue` renders base-currency amounts at **nine sites** and the rule
documents **zero** exceptions covering them — while explicitly saying of this very
pattern that the per-row hints it replaced *"must not come back"*.

The design narrows nine sites to one column plus one banner and writes the paragraph to
the standard of the two existing exceptions, including the condition that makes it
disappear: **when every bid on a lot is in one currency the column is not rendered at
all** — which is every lot in the demo data, and is why nobody noticed.

**Zafar adopted it on 2026-09-01**: Mikas's home currency is **UZS** and the sourcing
comparison resolves in the home currency. The paragraph is now the **third documented
exception** in `.claude/rules/10-frontend.md`, and screen 03's K10 asserts against it
rather than against an open question.

The decision corrected the draft in two places, and both corrections matter to the
fifteen screens that have not been drawn yet:

- **The currency is `Company.default_currency` read from the server, never the literal
  `UZS`.** Stabler is multi-tenant — `_accounts.py:94` already resolves it per company.
  A literal would have been correct for Mikas and wrong for everyone else.
- **What disappears when every bid is already in the home currency is the conversion,
  not the column.** `Delivered total` is the bid's total *plus its landed charges*, so
  it keeps doing work with nothing to convert. The draft had the column vanishing —
  which would have deleted the landed-charge sum along with it.

---

## Three decisions that stay open

These are carried into the prompts as questions. Do not let a design close them
quietly:

- **10.1** — tables have no server-side pagination (`list_rfqs` and
  `tender_quotations` both return every row, `limit_page_length=0`).
- **10.3** — an undocumented third currency exception.
- **10.6** — `z-index` layering between drawer, backdrop and toast.

And two things explicitly out of scope for Phase B: closing the `ds-btn:disabled`
debt (written in the delta, absent from the layer), and ADR-210 / ADR-211, which the
previous council deferred on purpose.
