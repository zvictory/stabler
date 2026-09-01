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
| 09 | Document center | the one surface all four roles share |
| 10 | PO control board | post-award; 765 lines, 0 `ds-*` |
| 11–12 | Customs queue · Logistics board | read-only projections; drag-to-advance is forbidden |
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

Five canvases exist. The first two **were** the gate the table above stops at: the
language was approved on them before the rest were drawn in it.

| # | canvas | artboards | what it settles |
|---|---|---|---|
| 01 | [Tender intake drawer](https://claude.ai/code/artifact/3d45f238-495f-4832-a25f-eac7c301820e) | 10 | single form (not stepped) · adjacent stack · `ds-file-list[data-mode]` (D14) |
| 02 | [Tender CRM kanban](https://claude.ai/code/artifact/564c73b0-6e7a-49ab-b6c9-87c7db56fb2c) | 10 | S1(a) drawer width → **760** via the existing `[data-size="lg"]` · S1(b) six orphans → **one** new component · one accessibility rule for the card and the row |
| 03 | [Sourcing workspace](https://claude.ai/code/artifact/477c7af9-3734-4986-a842-dc215c56e76e) | 8 | S2 currency → a **third documented exception**, narrowed from 9 sites to one column · nine comparison columns → **seven** · a table row is **not** a region |
| 04 | [Quotation entry drawer](https://claude.ai/code/artifact/16250885-0340-4e6b-a6ca-9421ae5f00d1) | 6 | S3 a failed load is a **state, not a toast** · the module's **reference patterns**, named so the other fourteen can copy them |
| 05–08 | [RFQ family](https://claude.ai/code/artifact/623be708-1d87-4213-a274-b5670a75d4f3) | 8 | `ds-* = 0` does **not** mean outside the layer · the layer has **zero** `@media print` rules · the demo seed creates **no RFQ at all** · 07's `Mark as sent` writes a record nothing can read back |

Each canvas carries its own **not chosen** artboards rather than deleting the rejected
option — the stepped intake on 01, the 542 px drawer on 02, the per-bid conversion on 03,
both readings of the two denominators on 05. A decision whose alternative has been erased
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
- **`RfqPrint.vue` and `BidPricing.vue` must gain a `.stbl-ds` ancestor.** Both measure
  **0** today (`TenderPage.vue` has 1). Prompts 08 and 10. **Confirmed 2026-09-01 by
  measuring the whole module**: these are the only two tender files whose root sits outside
  the shell, and `RfqPrint.vue` also has no `ds-*`, no layer tokens and no print rules to
  inherit — see prompt 08's S1, where the ancestor is one of two drawn answers rather than
  a foregone conclusion.
- **Four dead files are out of scope and must not be prettified**: `TenderCrmWrapper`,
  `TenderExecutionFlow`, `TenderExecutiveKpis`, `TenderTrendChart` — measured **0**
  JS/Vue imports each, but **1–2 Python references** apiece across three test modules
  that sit in the push gate. Deleting them is a three-module change, not a cleanup.
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
