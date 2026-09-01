# 01 · Tender intake drawer

**Source:** `stabler/public/js/components/TenderMasterDrawer.vue` — 777 lines,
**0 `ds-*`**, **46 `tgm-*` sites across 15 distinct classes**.
**Opens from:** `pages/tender/TenderCrm.vue:753`, in both new and edit mode.
**Why first:** ADR-301 — the whole third dialect is in this one file, and by ADR-201
this drawer is the *sole writer* of tender intake.

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

The first three entries of every row are the same three people — an administrator
sees all four windows. **This screen belongs to `sourcing`.**

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

## 4 · Hard rules

- **Severity is carried by three codes at once: colour + shape + word.** Colour alone
  carries no information. Urgency, delay and policy breach each need a shape and a
  word alongside the colour.
- **Text colour and fill/border colour are different tokens.** The bright orange
  "today" token measures 2.3:1 on white; there is a separate dark text token at 7:1.
  Never put a bright severity colour on body text.
- **The procurement policy numbers are server values** (minimum quotations, minimum
  distinct supplier countries). They must **never** appear as literal digits in the
  design. Draw the counter; do not draw the threshold as text.
- **No fixed-width label, badge or nav item.** Measured worst-case interface-language
  growth is **3.75×** (`RFQs`, 4 characters → Uzbek `Narx so'rovlari`, 15). Four
  languages ship: en, ru, uz, tr — plus `uzc` (Uzbek Cyrillic), no longer selectable
  but still rendered, and it must not break.
- **String interpolation exists; plurals do not.** You cannot write "1 quotation /
  5 quotations". Phrase every string so it never needs a plural.
- **No new backend field, doctype or migration.** If your design appears to need one,
  raise it as a **question**. Do not assume it silently.
- **Do not write code.**

## 5 · Five states — every region, every time

| state | how it is drawn |
|---|---|
| **loaded** | the real data below |
| **empty** | the shared empty-state component, in its compact form inside a drawer |
| **error** | a danger alert with `role="alert"`, the raw message in monospace, and a "Try again" action |
| **forbidden** | a warning alert with `role="alert"`, a lock icon, and a route button |
| **not measurable** | the fifth state, and it is real — see §7 |

Every region carries a test hook `data-region-state="loading|empty|error|forbidden"`.
**No CSS may bind to that attribute** — it exists for tests only.

## 6 · The screen

**Tender intake drawer.** Its one job: capture a tender the moment it is published,
so that it appears on the CRM board at the Intake stage.

**What it actually creates** is not a "Tender Master" — it creates a **CRM Deal** with
`deal_type = Tender`. There is no parent/lot dance; the tender lands directly in the
kanban's Intake column. Saving writes the deal, then overlays the items and files.

**The form as it stands today — five sections, lettered A–E:**

| § | heading | contents |
|---|---|---|
| A | Who is the Tender From? | Customer / Buyer (typeahead, required) + a "＋ New" escape to Sales |
| B | Tender Information | Tender Title (required) · Tender No · Source · Publication Date · Submission Deadline · Estimated Total + Currency |
| C | Tender Files | one dropzone, several PDFs |
| D | Requested Items | line editor — Item · Qty · UOM · Price · Amount — with a section-level Currency select, "Add Item", and a "New Item" escape to Inventory |
| E | Should We Bid? | Decision (Go / No-go) · Purchase method (Auction / Shop / Selection / Tender) · Penalty %/day · Guarantee · Guarantee return · Certificate required |
| foot | | Cancel · Save Tender |

### A measured discrepancy — resolve it, do not paper over it

The file's own header comment says **"4 sections"** and lists A–D. The template
renders **five**. Section E, *"Should We Bid?"*, was added later and the comment was
never updated. So this screen carries a go/no-go decision that its own author's
summary does not mention.

Decide whether E belongs in this drawer at all, or whether bid/no-bid is a separate
act on the CRM card once the tender exists. Draw your answer, and give the reason.

### S7 — settled 2026-09-01: one form, not a stepped flow

The drawer stays a **single form**: five sections, one Save. A three-step alternative was
drawn and rejected.

**The case that motivated the alternative is real and does not disappear with the
decision:** a user holding the tender notice who does not yet know the item list. The
single form answers it by leaving **items unrequired at save** — only buyer, title and
submission deadline block. Section D states this in its own hint, and the empty-items
state must be drawn as a normal condition, not an error.

If items ever become mandatory, S7 has to be reopened rather than worked around.

## 7 · Data — use these rows, invent nothing

Do not write "Acme Corp / Lot-001 / $1,000". That tests nothing. These are the real
seeded rows.

**Edit mode — draw the drawer on `UTY-2026-4309`:**

| field | value |
|---|---|
| Buyer | `Qurilish materiallari kombinati` |
| Tender no | `UTY-2026-4309` |
| Stage | sourcing — moved **26 days ago**, against a 14-day threshold, so this step is **overrun** |
| Estimated total | `410 000 000` |
| Submission deadline | today + 25 days |
| Quotations gathered | **3, from 1 country** — this lot fails the policy on *both* counts |

**On currency:** the seed data names no currency anywhere — zero occurrences in the
file. The amount comes from the record and the site default (most likely UZS). **Do
not hard-code a currency symbol into the design.** Draw it as a value that arrives
with the record.

**New mode:** draw the same drawer as it opens, with nothing filled in.

**The fifth state is real, and it is in this data set.** Lots `UTY-2026-4312` and
`UTY-2026-4313` carry **no stage stamp at all**. Any surface that averages stage age
must say **"Not measurable"** and **"{n} without a stage stamp — not averaged"**,
never a number. In this drawer, that surface is whatever you draw to show how long
the tender has sat at its current stage.

## 8 · Vocabulary for this drawer

Use these. Where you need something that is not here, say so explicitly as a proposal.

**Shell** — `ds-drawer[data-size="lg"]` at **760 px**, with `-backdrop`, `-head`,
`-title`, `-kicker`, `-close`, `-body`, `-foot`.

**Sections** — `ds-form-section` + `-head` + `ds-form-body`. The lettered heading is
`<span class="ds-label">A · …</span>`, and the letter stays **part of the heading
string**, never a separate badge element — a letter in its own box drifts from its
section the first time the form is reordered, and a translator cannot see what it
belongs to.

**Framing — settled 2026-09-01: adjacent stack.** Sections sit flush inside **one**
bordered card and are divided by their own heads (each head carries a `border-top`
except the first). Not five separate cards on the grey body. ADR-302 reserved this for
the designer, both were drawn, and the stack won: it is denser, puts more of a long form
on screen, and is what the drawer already does — so the migration changes class names
without changing what the user sees.

**Grid** — `ds-form-grid[data-cols="2"]`. **`data-cols="3"` is forbidden in this
module** — three columns do not survive 3.75× label growth.

**Fields**
- Required: `ds-field-req` on the label **and** `aria-required` on the control. The
  asterisk alone is not the contract.
- `ds-field-hint` **never renders empty**. No rule to state → no element.
- Field error: `ds-field-err` + `aria-invalid="true"` on the control.
- Percentage (Penalty %/day): `.input-group` + `.form-control` +
  `<span class="input-group-text">%</span>`. **`ds-input` is forbidden inside an
  input-group** — it sits outside the flex contract and the `%` drops to the next line.
- Checkbox (Certificate required): `form-check` + `form-check-input`.
  **`form-switch` is forbidden in new markup.**
- **Multi-select** uses the token-list pattern: `ds-table` + `ds-cut-del` + `ds-cut-add`
  + an adder.
- **File attachments** use `ds-file-list[data-mode="edit"]` — a component with a fixed
  row anatomy (icon · name · meta · one trailing slot) whose trailing slot, meta column
  and status chip switch by mode. In `edit` mode the slot is `ds-cut-del`, the meta is a
  file size, and there is **no status chip** — nothing is verified before a save. The
  `read` mode belongs to the document center, where files are server facts that screen
  cannot edit: no delete, a gated download link, an upload date, and a status of
  `ready` / `missing` / `ticked-but-unverified`.
  This is a decision taken on 2026-09-01 that closed a contradiction between ADR-302
  (a new component) and Phase A §1.2 (the same token list as multi-select). Both were
  half right; the two surfaces differ in deletability and a permission gate, not in
  anatomy.
- In-field loading: a 44 px skeleton inside the field.

**Actions** — `ds-btn`; at most **one** `ds-btn--primary`, in the footer. A disabled
button must carry **its reason next to it** (a hint or a `title`). A greyed-out Save
that does not say why is precisely the defect being removed. Waiting state is a
**label swap** plus `aria-busy="true"` plus `disabled` — there is no spinner element
inside a button.

**Form-level submit error** — `ds-empty[data-tone="crit"]` + `role="alert"` +
`tabindex="-1"`, so focus can land on it.

**Forbidden here:** hand-written `class="badge bg-*"`; a page-local badge factory;
`spinner-border` anywhere; `btn-xs`; `ds-table-wrap` (the wrapper is
`table-responsive`); a second confirmation dialog.

## 9 · Responsive

Draw at **1280**, **992** and **640** px. At 640 the drawer is full-bleed. Nothing may
scroll the page horizontally; wide content scrolls inside its own container. Remember
that every label in your artboards may be four times longer in another language —
draw at least one artboard with the Uzbek-length strings to prove the layout holds.

## 10 · Deliverables

1. The drawer at 1280 / 992 / 640, loaded, on `UTY-2026-4309`.
2. All five states of the drawer body.
3. The empty-items case drawn as a **normal** condition with Save still enabled — the
   consequence of settling S7 on a single form.
4. Section E resolved: in the drawer or out of it, with the reason.
5. The disabled-Save case, drawn with its reason visible.
6. A **15-row mapping table**: each `tgm-*` class in this file → the `ds-*` class that
   replaces it, or a new class you are proposing. These are the fifteen, measured
   from the file: `tgm-drawer`, `tgm-drawer-dialog`, `tgm-drawer-content`,
   `tgm-drawer-header`, `tgm-drawer-title`, `tgm-drawer-body`, `tgm-drawer-footer`,
   `tgm-kicker`, `tgm-section`, `tgm-sec-head`, `tgm-sec-num`, `tgm-sec-body`,
   `tgm-file-list`, `tgm-file-chip`, `tgm-file-name`.
   Note what is **absent**: there is no `tgm-drawer-backdrop`. The `ds-drawer` family
   has a `-backdrop`; this drawer does not. Whether that is a missing scrim or a
   deliberate omission is a **question** for you to raise, not to answer by drawing
   one in silently. Anything else you cannot map is likewise a question.
7. A list of every question your design raised. A screen this ambiguous that produces
   no questions has been answered by guessing.

## 11 · Acceptance — what a test must be able to see

Your design has to be checkable without a rendered DOM. This repo's test suite is
deliberately DOM-less: 17 specs mention `@vue/test-utils` and **zero** call `mount(`.
The working pattern reads the `.vue` file as text, pulls the decision expressions out and
runs them.

So: **do not** propose a criterion that needs a browser. "The drawer is 760 px wide" is
not checkable; "it carries `data-size='lg'`" is, and the layer owns the pixel.

Every number below was measured from `TenderMasterDrawer.vue` on 2026-09-01. Your design
must move each one, so that no change which does nothing can pass:

| # | Criterion | Before | After |
|---|---|---|---|
| K1 | `tgm-` count is 0 **and** `ds-drawer` > 0 **and** `ds-form-section` > 0 **and** the drawer carries `data-size="lg"` | 46 / 0 / 0 | 0 / >0 / >0 |
| K2 | Every region carries `data-region-state`, and no two of its `v-if` branches can be true at once | 0 | 5 |
| K3 | The form-level submit error has `role="alert"` **and** `tabindex="-1"` | 0 | 1 |
| K4 | The percentage field is inside `.input-group` and does **not** carry `ds-input` | 0 | 1 |
| K5 | Zero bare `<input type="number">` — today there are two, at `:517` and `:606` | 2 | 0 |
| K6 | Count of `ds-field-req` equals the count of controls carrying `aria-required` or native `required` | 0 aria | paired |
| K7 | No `spinner-border` anywhere in the file — there is one today | 1 | 0 |
| K8 | Every `:disabled` control has an `aria-describedby` resolving to an element rendered in that same state | 0 | = disabled count |
| K9 | A null stage stamp renders `ds-sla[data-state="unknown"]` — never `0`, never blank. Runs against lots `4312` and `4313` | n/a | 1 |
| K10 | No `form-switch`. Already 0 — a **regression guard**, because three live switches elsewhere in the module migrate into this grammar later | 0 | 0 |

K1 is the council's own gate, verbatim. Note why it is written as a conjunction: deleting
the class names satisfies the first clause and fails the rest, so an unstyled drawer
cannot pass.

State plainly which of these your design satisfies, and name anything it cannot — a
criterion you quietly drop is worse than one you argue against.
