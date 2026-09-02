# 13 · Operations desk

> `/tender/desk` · `stabler/public/js/pages/tender/OperationsDesk.vue` (608 lines)
> Server: `stabler/api/tender_desk.py` (365 lines) + `stabler/api/_desk_rules.py` (284 lines)
>
> **Nothing in this file is invented.** Every number, string, class name and
> absence below was read out of the working tree or produced by executing the
> real rules against `stabler/maintenance/seed_tender_demo.py`. Where a thing
> could not be measured, this file says so instead of guessing.

---

## Read this before anything else

**This screen is not broken the way 10, 11 and 12 are broken.** It is the most
layer-native surface in the module and it already does four things the rest of
the package asks for. Do not arrive with the usual repair list. Your job here is
harder: find what a screen that already looks right still gets wrong.

Measured, this file against the module:

| Signal | Operations desk | What 10 / 11 / 12 have |
|---|---|---|
| `ds-*` tokens | **79** | **0 · 0 · 0** — corrected 2026-09-02 by prompt 17; this row read `43 · 64 · 34`, which are `DirectorBoard`, `TenderFunnel` and `TenderFlow`, i.e. prompts **14 / 15 / 16**. Prompts 10 / 11 / 12 are `PoControlBoard`, `DeclarantQueue` and `LogistBoard`, and each of those files states 0 `ds-*` in its own header |
| Bootstrap `badge bg-*` | **0** | present in all three |
| Bare Bootstrap `btn-*` | **0** | present |
| `spinner-border` | **0** | present |
| `table-responsive` | **0** | present |
| `aria-*` attributes | **3** (`pressed`, `label`, `expanded`) + `role="alert"` | 0–1 |
| Distinct load/failure states rendered | **5** | 2–3 |
| View **and** filter in the URL | **both** | neither (plain refs) |
| Stale-response guard | **`reqToken`** | none |

`ds-*` ranking across the whole tender module, counted (corrected and completed
2026-09-02 by prompt 17 — the earlier version listed only the top of the table and
omitted that most of the module is at zero):

    TenderCrm 107 · OperationsDesk 79 · TenderFunnel 64 · DirectorBoard 43
    TenderFlow 34 · TenderOverview 27 · TenderPage 4 · TenderNav 3 · MyTenders 1
    BidPricing · DeclarantQueue · LogistBoard · PoControlBoard · SourcingWorkspace
    · TenderDocumentChain · TenderDocuments · TenderDocumentsPanel · TenderIntake
    · TenderWorkspaceTabs — all 0

**Ten of nineteen tender files carry no house layer at all**, which is the real
shape of the module: not a migrated system that drifted, but six migrated screens
and ten that were never touched.

---

## Corrections this file owes the package

Four package statements are wrong. Fix them where they live; do not carry them
forward.

**1. `00-SETUP.md`: "No timestamp, no staleness signal, no change indication
anywhere in the module." — false.** `Last read` exists in **two** screens:
`OperationsDesk.vue:8-10` and `DirectorBoard.vue`. Both render
`new Date().toTimeString().slice(0, 5)`.

**2. Prompt 11, acceptance K3: "Six screens auto-refresh and none shows a
timestamp | before 0" — false.** `DirectorBoard` is one of the six
`useAutoRefresh` consumers **and** shows `Last read`. The correct finding is
narrower and more interesting: what both screens show is **the browser's clock
at the moment the response arrived**, not when the server built it. The server
sends `"generated_at": now()` (`tender_desk.py:363`) and **nothing in the entire
SPA reads it** — zero matches for `generated_at` outside the one line that
writes it. The staleness signal that exists is the wrong one; the right one is
on the wire, unread.

**3. `00-SETUP.md` coverage gap #2, "The shell is in no prompt" — resolved by
this file.** `TenderPage.vue` is not neutral scaffolding that happened to wrap
this screen. `OperationsDesk.vue:2-3` says so in its own words: the shell's
padding *came from here* — this screen is the measurement the tender shell was
calibrated against. The shell belongs to prompt 13 and is specified in §6 below.

**4. This file's own first draft claimed the "Today" chip and the "Today" filter
could disagree.** Measured: they cannot, structurally — `tender_desk.py:313` and
`OperationsDesk.vue:306` evaluate the **same** predicate,
`due == today or severity == "today"`. What is real is smaller and stated in S5.

---

## 0 · What you are extending

Prompts 10–12 are boards for one operational stage each. This is the only screen
in the package that is **not** a board. It answers one question, printed as the
page title: **"What should I do today?"** Everything on it exists to make that
answer trustworthy without the reader asking anyone.

You are not drawing a fifth board. You are drawing the one surface a person opens
first, before they know which board they need.

---

## 1 · The product

Stabler is a tender operations SPA for a company that bids on Uzbek state
railway tenders, wins some, and then imports the goods. A lot moves
seen → go → sourcing → priced → submitted → won/lost, and after a win it becomes
purchase orders, customs clearance, delivery and invoices.

Six or seven people share the whole pipeline. Nobody owns a stage end to end.
The desk is the shared morning surface: it reads every stage, applies eight
rules, and prints the intersection that belongs to *you*, today.

**The design signature of this screen, in its own comment
(`OperationsDesk.vue:320-322`):**

> Sayaçların dördü de API'den gelir. Alt satır ("rule") sayının hangi koşuldan
> çıktığını yazar — tasarımın imzası bu: **her rakam kendi sorgusunu taşır**,
> kullanıcı sayıya güvenmek için kimseye sormaz.

Every number carries its own query. Keep this.

**Corrected 2026-09-02 by prompt 14.** This paragraph claimed the idea "appears
nowhere else in the module." It appears in `DirectorBoard.vue` too, with the
same comment, and there it is older and larger: six counters, each carrying a
human `note` **and** a raw-query `rule`. What is unique to the desk is not the
idea but its execution — the desk's four rules are true sentences; three of the
director board's six do not describe what the number counted. Measure 14 against
13 on honesty, not on novelty.

**Prompt 15 found a third and larger carrier**: `TenderFunnel.vue` prints a rule
fifteen times (4 counters, 11 stage boxes, one per chevron popover). The desk is
the smallest of the three and the only one where every rule is true.

---

## 2 · The role, and why this gate is the module's most complete one

Views come from the session: `sourcing`, `declarant`, `logist`, `director`.
Three gates run, and unlike every other screen they are three *different*
messages:

1. `session.canAccessModule('tender')` → *"Access denied to tender module."*
2. `session.activeCompany` → *"Please select an active company."*
3. server `_require_tender_view(view, company)` → throws `PermissionError`

One extra server rule (`tender_desk.py:141`): a non-oversight user in the
`sourcing` view sees only deals assigned to or owned by them. Oversight
(director) sees everything, and is the **only** role for whom `team_load` is
populated at all (`tender_desk.py:333`).

**The defect:** gates 1 and 2 render as their own clearly-worded branches, but
gate 3 — the server's `PermissionError` — is caught into `error.value` and lands
in `<div v-else-if="error" role="alert">` (`:72`). *Forbidden collapses into
error.* A person who picked a view they are not entitled to sees a red-flavoured
failure, not "this view isn't yours". Two of three gates are exemplary; the third
throws away the distinction the other two protect.

**Fixed 2026-09-02 (D9), and one thing measured on the way.** The refusal is now
its own branch ahead of the error branch, without `role="alert"` — an assertive
live region is for a failure, and being refused a view you never held is a policy
outcome. The counter strip is hidden while refused: with no payload the four chips
render `0 / 0 / 0 / 0` under rules like *due date passed, still open*, i.e. a
measurement of the very view the server declined to measure.
**The repo's standard forbidden test would not have worked here.** Five screens
carry `err?.status === 403 || /role|permission/i.test(err?.message || "")`
(`UnbilledReceipts.vue:235`). This path throws `_("Not permitted")`
(`tender.py:1893`) — *permitted* does not contain *permission*, so that regex
matches nothing, and a translated message matches nothing in any language. The
**403 is the load-bearing half**; the wording is an English-only backstop.

**A second, recorded gate bug — read the comment, do not repeat the bug**
(`tender_desk.py:295-311`). The Decision box partitions one approval queue into
"Awaiting my approval" and "Waiting others". The old predicate OR'd in
`oversight`, so for a director the term swallowed their **own** requests into
"yours to decide" — decisions the card promised were actionable and were not —
and left `waiting_others` structurally 0. The rule now is exactly:
`self_made or requested_by == user` → waiting others; everything else → yours.
You cannot approve your own request. That single fact is the whole partition.

---

## 3 · Nine mandates — measured, and this screen already meets six

Do not "apply" the mandates here. Verify them, then spend your effort on the
three that fail.

| # | Mandate | Measured on this screen |
|---|---|---|
| 1 | House layer, not Bootstrap | **PASS** — 79 `ds-*`, zero `badge bg-`, zero bare `btn-` |
| 2 | Every number carries its rule | **PASS** — all four chips print `rule` under the value |
| 3 | Loading is skeleton, not spinner | **PASS** — `<SkeletonRows :rows="6" :cols="3">`, zero `spinner-border` |
| 4 | Five states per region | **PASS** (2026-09-02, D15) — was PASS in the plan panel only; the other three rendered nothing at all in four of the five, see §5 |
| 5 | State lives in the URL | **PARTIAL** — `view` and `filter` yes (`:470`, `:480`); band collapse (`collapsed`, `:257`) no |
| 6 | Keyboard and screen reader reachable | **PASS** — `aria-pressed`, `aria-label`, `aria-expanded`, `role="alert"`; every interactive thing is a real `<button>` except one (S4) |
| 7 | No raw server identifiers in front of a human | **PASS** (2026-09-02) — was FAIL with four of them, S3 |
| 8 | The empty state must distinguish *nothing to do* from *cannot be computed* | **PASS** (2026-09-02, D14) — three-way in the plan, three-way in the Decision box; S2's own premise was corrected in place |
| 9 | Freshness is the server's, not the browser's | **PASS** (2026-09-02, D12) — `lastReadAt` reads `generated_at`; this row still read FAIL while the D12 acceptance row read *passes*, and was corrected on 2026-09-02 while closing D15. The D12 work itself is not mine |

---

## 4 · Hard rules

- **No dark mode.** One palette. The app has none and never gets one here.
- **No new component vocabulary.** `desk-*` classes exist only to *re-shape*
  house primitives — `.desk-state` is `.ds-panel-foot` turned into a vertical
  stack, and its comment says exactly why: *"ayrı bir kutu tipi icat etmek yerine"*
  — rather than inventing a new box type. Extend that way or not at all.
- **Do not recompute severity on the client.** `severity` is derived server-side
  by `_desk_rules.build_plan`. The client groups it; it must never re-decide it.
  `SEVERITY_ORDER = ["overdue", "today", "soon", "info"]` is a display order, not
  a computation.
- **Do not invent a delivery rule** (see S2). Show the gap; do not close it.
- **Money:** this screen renders **no money at all** — zero `formatMoney` calls.
  Do not add any. The desk is about time and obligation. The boards have money.
- Four languages ship in the pickers (en, ru, uz, tr) plus `uzc` still
  translated. Every string is a `t()` key. If you introduce one, it must be a
  key, and see S3 for what happens when a non-key is passed to `t()`.

---

## 5 · Five states — every region, every time

The plan panel renders all five, in this order, and this is the reference
implementation for the module:

| State | Rendered as | Line |
|---|---|---|
| loading | `<SkeletonRows :rows="6" :cols="3" class="desk-pad">` | `:64` |
| forbidden (module) | `.ds-panel-foot.desk-state` — *"Access denied to tender module."* | `:66` |
| no company | `.ds-panel-foot.desk-state` — *"Please select an active company."* | `:69` |
| error | `.ds-panel-foot.desk-state[role=alert]` | `:72` |
| empty | two lines: *"No tasks scheduled for today"* / *"All items in this view are up to date."* | `:73` |

**Corrected 2026-09-02 while closing D15 — the plan panel renders SIX, and
"forbidden" is two different gates.** The table above says *forbidden (module)*,
which is the client-side module check. D9 added a second refusal that is not the
same thing: `_require_tender_view` raises `frappe.PermissionError` for a **role
view** the reader may not open, and it arrives as a 403 on the same request that
feeds all four regions. Two refusals, opposite recoveries — one needs the module
enabled for the company, the other needs a role — so the chain is now
loading · module · company · **view refusal** · error · empty, in that order,
with `role="alert"` on the error alone.

**And the other three panels did not have ONE state, not four.** The doc says
they "do not have five states"; measured, Team load and Next 7 days rendered
`v-if="teamLoad.length"` / `v-if="week.length"` on the `<section>` itself, so on
anything but a populated payload the panel was **not in the DOM at all**. That is
worse than an unstyled empty and it is the one state a reader cannot interrogate:
the page is simply shorter. A failed request, a module the company does not have,
a refused view, a director's panel shown to a sourcing user and a genuinely quiet
week were five different facts rendered as the same absence.

Draw them. And note what the empty text asserts: *"All items in
this view are up to date"* is a **claim about the world**, and §7 proves it is
false on real data — five of eight rules cannot produce a row at all, so the
panel says "you are up to date" when the honest sentence is "four of the eight
things I check could not be checked."

---

## 6 · The screen

### The shell — specified here because it was measured here

`TenderPage.vue` supplies the module bar, the page title, the `.stbl-ds` scope
and the padding. This screen passes it:

- `:label="t('Operations desk')"` — the module-bar label
- `:title="t('What should I do today?')"` — the H1, a question, deliberately
- `#meta` slot — four spans: today's date (`ds-mono`), weekday, `Last read HH:MM`,
  and the active view
- `#actions` slot — the role `<select class="ds-input">` (rendered only when
  `views.length > 1`) and a `<button class="ds-btn">` that reads
  `Loading…` / `Refresh`

The meta row is the module's only freshness surface. Redesign it against
correction 2: it should show when the **server** built the answer, and it should
be able to say *stale*.

### The counter strip

`<div class="ds-kpis" data-cols="4">`, four `<button class="ds-kpi">`, each with
`data-sev` and `aria-pressed`. Each chip is three lines: label, value + caption,
and `rule`. Clicking one filters the plan.

| filter | `data-sev` | label | caption | rule |
|---|---|---|---|---|
| `today` | `today` | Today | must close today | due date is today |
| `overdue` | `crit` | Overdue | past due | due date passed, still open |
| `awaiting_me` | `soon` | Awaiting my approval | decision is yours | approval assigned to you |
| `waiting_others` | *(none)* | Waiting others | no action from you | you requested, someone else answers |

There is no `all` chip, though `all` is the default filter and the only way back
to it — measured — is a chip's second click through `setFilter`. Check that path.

### Panel 1 · Daily work plan (`<h2>`, `:56`)

Sublabel: `{{ filteredPlan.length }} items · {{ overdueInView }} overdue`.

Then, when there are rows:

- **The lead row** — `ds-row ds-row--lead`, marked *"Next up · {severity}"*. Its
  comment (`:78-79`) is load-bearing: *"Manuel bir işaret değil, sıralamadan
  TÜRETİLİR"* — it is not a flag anyone set, it is the first item of the
  highest-severity band. Keep it derived.
- **Severity bands** — `<button class="ds-band" :data-sev :aria-expanded>`,
  collapsible, in fixed order overdue → today → soon → info.
- Each row shows: title, `why`, `kind`, owner (`data-unassigned`), and a due
  label — `PAST DUE` when overdue, `TODAY` when `due === todayStr`.

### Panel 2 · Decision box (`<h3>`, `:157`)
### Panel 3 · Team load (`<h3>`, `:191`) — oversight only, empty for everyone else
### Panel 4 · Next 7 days (`<h3>`, `:214`)

Header sublabel: **"Bid · delivery · due"**. Seven `ds-week-day` cells with
`data-today`, `data-quiet` (weekend), day-of-week, day-of-month, and a count or
`—`. The `title` attribute carries up to two item titles, newline-joined — a
native tooltip, the only place those titles appear.

---

### S1 — the calendar cannot show the row the desk is loudest about

The window is `for d_offset in range(7)` starting at `today_date`
(`tender_desk.py:325-329`). A day's count is `plan_items where due == that day`.

**Everything overdue has a due date in the past, so nothing overdue can ever
appear on this calendar.** On seed data the desk's single loudest row — a bid
deadline that passed yesterday — is absent from the seven cells while the
Overdue chip above reads 1. Two regions of one screen, describing the same four
items, that cannot agree by construction.

Draw the fix. A seven-day window that begins today is a choice, not a law.

**Fixed 2026-09-02 (D13) — and the fix is not an earlier start date.** Overdue is
unbounded (an invoice can be four months past due), so any N-day lead-in still
hides whatever is older than N, *and hides it in a region that now looks like it
covers the past*. The calendar gained a **past-due bucket**: everything with
`due < today`, however old, as one pile — complete by construction. The boundary
is strict, so today's deadline is counted in the today cell and not in both.
The partition moved to `_desk_rules.build_calendar`, which is Frappe-free, so the
property that matters — *no dated plan row disappears between the regions* — is
now **executed** by `test_desk_rules.py` against `build_plan`'s own output rather
than pattern-matched in a module that imports frappe.
It is drawn as the panel's own `.ds-panel-foot` under the seven cells, not as an
eighth cell: `.ds-week` is `repeat(7, minmax(0,1fr))`
(`stabler-modernist.css:361`), and the bucket is not a day. Its colour comes from
`data-sev="crit"` through the layer's `.ds-sev` rules (`:307-308`) — no colour
rule was added to this page. It is **not** a control: `.ds-band` would have
painted it as one, and the past bucket counts by *due date* while the Overdue
chip counts by *severity*, which are not the same set (a `policy_gap` on a lot
whose bid deadline has passed is dated in the past and has severity `today`), so
wiring it to the overdue filter would have created a fresh disagreement of
exactly the kind S1 is about.

### S2 — five of the eight rules cannot produce a row, and the screen claims otherwise

`_desk_rules.build_plan` emits exactly eight kinds. Executed against the seed:

| kind | fires? | why not |
|---|---|---|
| `bid_due` | **yes** | — |
| `bid_soon` | **yes** | — |
| `policy_gap` | **yes** | — |
| `no_parent` | **no** | needs `company_uses_parents` — the seed links no `custom_tender_master` to any deal, so by the rule's own honest reading the lots are not orphaned, the site simply files tenders flat |
| `won_no_po` | **no** | both won lots have POs carrying `custom_crm_deal`, and the filter is `docstatus < 2`, which drafts satisfy |
| `po_late` | **no** | filter is `docstatus: 1`; every seeded PO is a draft |
| `invoice_due` | **no** | the seed creates no Purchase Invoice |
| `approval_pending` | **no** | the seed creates no Approval Request — which is *also* why both `awaiting_me` and `waiting_others` are 0, and the Decision box is empty |

**This is the fourth consecutive screen** (10, 11, 12, 13) where whole regions
cannot populate from demo data. On the boards it was lanes. Here it is the
reasoning itself.

---

**Corrected 2026-09-02 while closing D14 — this section's premise is wrong, and
the row it motivates is right for a different reason.**

This section is headed *"five of the eight rules **cannot produce a row**"* and
asks for a panel that says *"4 rules ran · 4 could not"* (a count that also
contradicts its own table, which is 3 fire / 5 do not). Measured against the
table's own "why not" column, **all eight rules run on seed data.** Five of them
find nothing because there is nothing of that kind in the data, which is an
answer, not a failure — and this file says so itself, rule by rule: both won lots
*have* POs; every PO is a draft, and an unsubmitted PO cannot be late; the seed
creates no Purchase Invoice; it creates no Approval Request; and with no parent
tender anywhere *"the lots are not orphaned, the site simply files tenders flat."*
A rule that ran and found nothing is *nothing to do*. **"Did not fire" is not
"could not be checked."**

So the deliverable as written — a coverage report over eight rules — would have
manufactured a warning where there was none. **The row is still real**, because
this screen does have *could not be computed* states, and both were already in
the code and both were being thrown away:

1. **A swallowed exception.** `list_pending` was wrapped in a bare
   `except Exception: all_pending_approvals = []`. It throws
   `frappe.PermissionError` for anyone who is not an approver
   (`approvals.py:119-121`) — most of this desk's readers — and can throw for any
   other reason too. Both produced an empty list, so a failure and a quiet queue
   rendered identically: two counters at 0, an empty Decision box, and the plan
   asserting *"All items in this view are up to date"*. **Four confident
   statements out of one swallowed exception.**
2. **A discarded count.** `build_plan` returns `skipped` — the rows it had to drop
   because a date would not parse — and the caller read only `["items"]`. A lot
   with a malformed bid deadline vanished from the plan and the panel then said
   the view was up to date.

The fix names three approval outcomes (`read` / `not_yours` / `unreadable`) and
ships `skipped`. `not_yours` is deliberately **not** a gap: the queue exists and
is not yours, so a plan without it is complete *for you*, and a warning that fires
every day for most users would bury the one that matters.

**A third meaning of empty was found and closed at the same time**, and it is the
most reachable of all: `filteredPlan` is empty whenever a counter chip hides every
row. One click from the default view, on a desk with three items due today,
pressing **Overdue** made the panel say *"No tasks scheduled for today · All items
in this view are up to date."* The empty state is now three-way — the filter, the
gap, and the genuine all-clear — and the world-claim sentence survives only in the
third.

**And one fact is resolved, carried, and never read.** `tender_desk.py:100-107`
resolves `delivery_deadline` out of the intake JSON — with a long comment about
the bug that made it unconditionally `None` — passes it into `lots_fact` as
`"delivery_deadline"`, and **no rule in `_desk_rules.py` consumes it.** Zero
delivery rules exist. Meanwhile the calendar's own sublabel promises
"Bid · **delivery** · due". The screen advertises a dimension the engine does
not compute.

Your deliverable is not the missing rule. It is the state that tells the truth:
a plan panel that can say *"4 rules ran · 4 could not"* instead of *"All items in
this view are up to date."*

**D19 resolved 2026-09-02, and one more thing measured.** The rule was *not*
invented (§4 forbids it); the calendar's sublabel stopped promising it, and now
reads *"Plan items by due date"*. Measured while doing it: even the one
delivery-flavoured rule that does exist, `po_late`, can never reach that calendar
— its severity is unconditionally `overdue` (`_desk_rules.py:186`, `sched_date <
today_date`), so it is always outside a window that begins today. "delivery" was
impossible in that region twice over. The fact stays on the wire and stays
unread; `test_operations_desk_source.py` now ties the promise and the engine
together **in both directions**, so writing a delivery rule and forgetting to
re-advertise it fails too.

**And the second half of the sublabel was also measured.** The header said
*"Next 7 days · Bid · delivery · due"*. Of the eight rules, only `bid_due`
(today), `bid_soon` and `policy_gap` can ever produce a future-dated row; every
other kind's `due` is `today_str` or a past date. The seven cells therefore show
bid deadlines and a pile of today — which is what the new sublabel claims and the
old one did not.

### S3 — ~~three~~ **four** raw server identifiers are printed at the user

**Corrected 2026-09-02 while closing D10.** This section said *three*; measured,
there are **four** sites, and the missing one is the higher-volume of the two
`kind` leaks. Method: every `{{ … }}` interpolation in the template was extracted
and read (58 of them), rather than the three the first pass happened to find.

| Where | Renders | Value on real data |
|---|---|---|
| `:11` | `{{ t(deskData.view) }}` | `sourcing` / `declarant` / `logist` / `director` — **none is a key**; 0 hits in `en.csv`, so `t()` returns the id |
| `:24` | `{{ t(v.label \|\| v.id) }}` | the server builds `available_views = [{"id": v, "label": v}]` (`:40`) — **the label *is* the id**, so the option text is `logist` |
| `:96` | `<div class="ds-row-ev">{{ leadItem.kind }}</div>` | `bid_due`, `policy_gap`, `won_no_po`, `approval_pending` — snake_case internals, unlabelled, in the most prominent row on the page |
| **`:128`** | `<div class="ds-row-ev">{{ item.kind }}</div>` | **the same leak in every ordinary band row.** On the seed's four rows the lead row leaks `bid_due` once and this one leaks `bid_due`, `policy_gap` and `bid_soon` — three of the four |

Four different mechanisms, one result: the machine's vocabulary on a surface
whose whole promise is *you will not need to ask anyone*.

**Fixed 2026-09-02 (D10, D11).** Two literal-keyed maps in the component —
`KIND_LABEL` (eight rules) and `VIEW_LABEL` (four views) — the same idiom as
`TenderDocumentsPanel.vue:29`. Literal because `t()` is harvested by scanning
source, so a key computed anywhere (including on the server) can never be
translated. The **server fix was made too**: `available_views` is now
`[{"id": v}]` — the field had exactly one consumer, and a key called `label`
holding an id invites the next screen to render it.
The two fallbacks differ **on purpose**: an unknown `kind` renders nothing (the
evidence line is `v-if`-guarded, so it vanishes rather than leaking), while an
unknown view falls back to its id (an `<option>` with empty text is a row the
reader can select and cannot name). Completeness of both maps against
`_desk_rules.py` and `_TENDER_VIEW_ROLES` is asserted in
`test_operations_desk_source.py`, so a ninth rule or a fifth view fails the build
instead of reaching a user.

### S4 — the primary action is not a control

`:100`:

    <span class="ds-btn ds-btn--primary desk-lead-cta">{{ t("Open") }} →</span>

It is a `<span>` painted as the primary button, nested inside the real
`<button class="ds-row--lead">` that actually handles the click. It works — the
parent takes the event — but it is the same class of defect as commit `b1d67f0`
(*"the disabled ds-btn does not take clicks — it just looks like it would"*):
the most action-shaped pixels on the page are not the action. Hover, focus ring
and keyboard target all belong to the row, not to the thing drawn as the button.

Decide deliberately: either the row is the control and the CTA stops pretending
to be one, or the CTA is the control and the row stops being a button. Not both.

### S5 — one predicate, two clocks

`todayStr = todayIso()` (`:266`) is the **browser's** local calendar date. The
comment above it documents the bug that produced it (measured 2026-08-02 03:53:
`toISOString()` gave UTC, Tashkent is UTC+5, and between 00:00 and 05:00 the
desk's "today" fell a day behind the server's). That bug is fixed.

What remains is not a bug, it is a seam: the server counts with
`frappe.utils.today()` (site timezone) and the client re-filters with the
browser's date. The predicate is identical; the clock is not. On a Tashkent site
read from a Tashkent browser they always agree, which is precisely why nobody
will notice the day they do not.

`todayStr` drives four things: the header date, the TODAY filter, the calendar's
today cell, and the row badge. Show which clock a reader is looking at.

**Fixed 2026-09-02 (D18).** The seam is closed *and* stated, because closing it
silently would leave the acceptance row open — a reader still could not tell
which clock. The payload now carries `"today": today_str`, the same variable the
counters and the calendar window were already built from (not a second read of
`today()`, which would let a request straddling midnight ship one day's counters
under the next day's label). The client prefers it and falls back to
`todayIso()` only when the key is absent — an older server mid-deploy, or the
render before the first response. The meta row names the clock in both cases
(*server date* / *device date*), and on a day the two disagree it adds what the
device says. `todayIso()` is now called exactly once in the file, which is what
makes "two sources of today" fail a test rather than a night.

---

## 7 · Data — derived by execution, invent nothing

Produced by running the real rules against `seed_tender_demo.py`. `DEMO_LOTS`
has 13 lots; `DEADLINE_OFFSETS` sets bid deadlines relative to today;
`MIN_QUOTATIONS = 5` (`stabler/api/_procurement_policy.py:23`).

Three lots are dropped before any rule runs — `result in ("won", "lost",
"cancelled")` → `continue` (`_desk_rules.py:57`): `UTY-2026-4314` (won),
`UTY-2026-4315` (won), `UTY-2026-4316` (lost). Ten lots reach the rules.

**The complete plan. Four rows. Not four examples — four.**

| # | kind | title | why | severity | due | band |
|---|---|---|---|---|---|---|
| 1 | `bid_due` | Bid due: UTY-2026-4305 [DEMO] | Deadline past by 1 day | `overdue` | today − 1 | Overdue |
| 2 | `bid_due` | Bid due: UTY-2026-4308 [DEMO] | 5/5 quotes · deadline today | `today` | today | Today |
| 3 | `policy_gap` | Missing supplier quotes: UTY-2026-4309 [DEMO] | 3/5 quotes collected (minimum 5 required) | `today` | today + 25 | Today |
| 4 | `bid_soon` | Bid deadline soon: UTY-2026-4310 [DEMO] | 6/5 quotes · deadline in 2 days | `soon` | today + 2 | Soon |

Sort is `severity weight → due → title`, so that order is the rendered order.
**The lead row is #1** — the overdue bid, band Overdue.

**The four chips, computed by the server's own expressions:**

| chip | value | how |
|---|---|---|
| Today | **2** | rows 2 and 3 — `due == today` **or** `severity == "today"` |
| Overdue | **1** | row 1 |
| Awaiting my approval | **0** | no Approval Request exists |
| Waiting others | **0** | same |

**The seven-day calendar:**

| offset | +0 | +1 | +2 | +3 | +4 | +5 | +6 |
|---|---|---|---|---|---|---|---|
| count | **1** | — | **1** | — | — | — | — |

Row 2 lands on +0, row 4 on +2. Row 1 is in the past and **invisible** (S1);
row 3 is 25 days out and outside the window. Two of four items are on the
calendar; the loudest one is not.

**Decision box: empty. Team load: empty for every non-director; for a director,
built from site users.**

**Corrected 2026-09-02 (D16) — from deal OWNERS, not site users.** `team_load`
is `for d in deals: owner = assigned_to or owner or "Unassigned"`
(`tender_desk.py` §9), so the rows are the people who hold lots, not the people
who have accounts. On seed data the two nearly coincide, because the seeder
assigns round-robin over the team (`seed_tender_demo.py:655`) — but the `seen`
lots are deliberately left unassigned and fall back to the document owner, so the
seeder gets a row of their own. A site with twelve users and four lots held by two
of them renders two rows, and adding a user changes nothing.

**Which also fixes the sentence the merged empty state would have used.** The map
takes a row for **every** deal owner and only then counts the open lots, so a
team whose lots are all won or lost still renders rows reading 0. `team_load ==
[]` therefore means *the company has no lots at all* — never *nobody is busy*.

**Three states you cannot exercise from this data — say so on the canvas rather
than faking rows:**

1. `data-unassigned` on a row owner. The seed assigns round-robin to the site's
   non-Administrator users and deliberately leaves only `seen` lots unassigned
   (`seed_tender_demo.py:655`) — and neither `seen` lot produces a plan row.
2. The `info` band. Its only source is `no_parent`, which cannot fire.
3. The `waiting_others` filter. Its only source is `approval_pending`.

Owner names are **not specified here** because they depend on which users exist
on the site. Draw a plausible name and label it as a placeholder; do not present
it as seed data.

---

## 8 · Vocabulary

Words this screen owns. Use them; do not synonymise.

| Term | Means, exactly |
|---|---|
| **Next up** | the first row of the highest-severity band — derived, never set |
| **rule** | the one-line query printed under a counter, e.g. *due date passed, still open* |
| **band** | a collapsible severity group: Overdue · Today · Soon · Info |
| **kind** | the internal rule name (`bid_due`, `policy_gap`, …) — never rendered; `KIND_LABEL` names it for the reader (S3) |
| **why** | the server's sentence for *why this row is here*, e.g. *3/5 quotes collected* |
| **view** | the role lens: sourcing · declarant · logist · director |
| **oversight** | director; the only role with Team load |
| **Last read** | today: the browser's clock at receipt. Should be: when the server built the answer |
| **PAST DUE / TODAY** | the row's due badge, from `severity` and `due` respectively |

---

## 9 · Responsive

Measured: **one** media query in the entire file (`:548`) —
`@media (max-width: 992px) { .desk-grid { grid-template-columns: 1fr } }`.
Below 992px the side column drops under the plan. That is the whole responsive
story.

Specify at least: the four-across `ds-kpis data-cols="4"` strip on a phone (four
chips each carrying a three-line rule caption is the hard case), the seven-cell
week, and the lead row, whose right-hand owner + CTA column has nowhere to go.

---

## 10 · Deliverables

Artboards. Every one at 1440×900 unless stated.

1. **Desk, populated** — the four real rows of §7, correct bands, correct lead
   row, correct chip values (2 / 1 / 0 / 0), correct calendar (+0 and +2).
2. **The meta row, redesigned** — server generation time, and a stale state.
   This is correction 2 made visible.
3. **Plan panel · five states** — the four non-loading ones side by side, plus
   the sixth this screen needs: *rules that could not run* (S2).
4. **Decision box · five states**, including the empty it actually has on real
   data. *Corrected 2026-09-02 (D15): its empty is THREE empties. The box is fed
   by `list_pending`, which raises `PermissionError` for a non-approver — most
   readers — and can fail outright; D14 split those into `not_yours` and
   `unreadable`, and both used to render the same "No pending decisions" as a
   genuinely quiet queue. Only the third may say it. The head counter goes to `—`
   for `unreadable` and stays a number for `not_yours`, because zero decisions
   waiting on you is the true answer when the queue is not yours.*
5. **Team load · five states**, including "not your role" — which today renders
   as an empty panel indistinguishable from "nobody has any work".
   *Corrected 2026-09-02 (D16): it renders as NO PANEL — `v-if="teamLoad.length"`
   removes the `<section>`. And "nobody has any work" is not what the other empty
   means either (see §7). The role answer cannot be inferred from the list at all;
   it now ships as `oversight` on the payload, the name the rest of the tender API
   already uses (`tender.py:2525`, `:3554`).*
6. **Next 7 days · the S1 problem, and your answer to it.** Two artboards: what
   it does now (overdue invisible) and what it should do.
7. **The three identifier leaks** (S3), before and after, all three in one board.
8. **The lead row control** (S4) — the two legitimate resolutions, drawn, with
   the one you chose marked and the other kept.
9. **Forbidden ≠ error** (§2) — the view-permission refusal as its own state.
10. **Filter interaction** — a chip pressed, `aria-pressed` visible in the
    design, and the route back to `all`.
11. **Band collapsed / expanded**, and a note on whether collapse belongs in the
    URL alongside `view` and `filter`.
12. **Mobile, 390×844** — chips, week, lead row.
13. **An annotation board** listing the four package corrections at the top of
    this file, so the decision survives without this prompt.

Keep artboards you rejected. A decision whose alternative was erased cannot be
re-examined.

---

## 11 · Acceptance — what a test must be able to see

| # | Assertion | Today |
|---|---|---|
| D1 | The plan renders exactly the four rows of §7, in severity → due → title order | passes |
| D2 | The lead row is row 1 and is derived from the ordering, not a flag | passes |
| D3 | Chip values are 2 / 1 / 0 / 0 | passes |
| D4 | Every chip prints its `rule` line | passes |
| D5 | Zero `badge bg-*`, zero bare `btn-*`, zero `spinner-border` | passes |
| D6 | Loading renders `SkeletonRows`, not a spinner | passes |
| D7 | `view` and `filter` round-trip through the URL | passes |
| D8 | Band collapse round-trips through the URL | **passes** — `?collapsed=` (2026-09-02) |
| D9 | A view the user lacks renders as *forbidden*, distinct from *error* | **passes** (2026-09-02) — own branch, no `role="alert"`, counters hidden |
| D10 | No snake_case identifier appears in rendered text | **passes** (2026-09-02) — `KIND_LABEL`; the leak was in **four** places, not three (S3) |
| D11 | The role `<select>` shows translated labels, not ids | **passes** (2026-09-02) — `VIEW_LABEL`; the server stopped sending `label == id` |
| D12 | The freshness stamp reflects `generated_at`, not the browser clock | **passes** (2026-09-02) — first reader of `generated_at` in the SPA |
| D13 | An overdue item is discoverable from the calendar region | **passes** (2026-09-02) — a past-due bucket, not an earlier start date |
| D14 | The empty plan distinguishes *nothing to do* from *could not be computed* | **passes** (2026-09-02) — three-way, and S2's premise was corrected: the silent five had *run* |
| D15 | The Decision box, Team load and calendar each render five states | **passes** (2026-09-02) — one `regionState` for the four page-level gates, drawn in all three; the plan panel's inline chain kept as the reference and pinned equal by test |
| D16 | Team load empty-for-your-role ≠ Team load empty-of-work | **passes** (2026-09-02) — `oversight` on the payload; and empty-of-work is *no lots in the company*, not *nobody busy* (§7) |
| D17 | The primary CTA is the focusable, hoverable control, or is not drawn as one | **passes** (2026-09-02) — the row is the control; the span is no longer painted as one |
| D18 | Which clock produced "today" is legible to the reader | **passes** (2026-09-02) — the server sends `today`; the meta row names the clock and flags disagreement |
| D19 | `delivery_deadline` is either consumed by a rule or absent from the calendar's promise | **passes** (2026-09-02) — absent from the promise; the rule was NOT invented |
