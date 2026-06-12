# Tender Orders Board — SO Fulfillment Kanban for Government/Railways Tenant

Date: 2026-06-12 · Supersedes the (uncommitted) generic SO board spec; self-contained.
Tenant profile: government customers (UZ Railways, large industry). Tender-based, buy-to-order,
2–12 month fulfillment, multi-channel intake (Telegram, web, tender portal), treasury payments.
Decisions by Zafar (from board brainstorm): draggable manager-defined stages (Option B) ·
all team may move cards · 5–10 open orders · drafts visible as inbound lane.

## 1. Process spine (two connected boards)

**Pre-win = existing CRM Deals kanban.** Tender = CRM Deal; card carries tender no., deadline,
bid value. Intake channel = native Lead `source` (Lead Source fixtures: Telegram, Web,
Tender portal, Direct). Lost → archived with reason; win-rate per channel is a free report.

**Post-win = new SO fulfillment board.** Won deal → one click **Create contract SO**
(`create_so_from_deal(deal)`: customer + items + value mapped; link field §2). Card then moves
through fulfillment stages; every stage anchors to a real ERPNext finance document:
Procurement→PO (money out), Delivery→DN (+ acceptance act print), Invoiced→SI, Paid→Payment Entry.

## 2. Data model (minimal)

- Doctype **`Stabler SO Stage`** (clone of CRM Deal Status pattern): stage_name, position, color;
  manager CRUD + reorder; delete blocked while referenced.
  Tender fixture set: `Contract signed → Procurement → Delivery → Acceptance → Invoiced → Paid`.
- Custom fields on Sales Order: `custom_board_stage` (Link Stabler SO Stage),
  `custom_crm_deal` (Link CRM Deal). Idempotent fixture patch.
- Everything else native: per_delivered, per_billed, SO-item delivered_qty,
  `Purchase Order Item.sales_order` (MR→PO chain stamps it), SI→SO links, PE allocations.

## 3. Backend (`sales.py`)

```
so_board(company) → {stages, cards[]}
  card: name, customer_name, grand_total, currency, age_days, stage, docstatus,
        per_delivered, per_billed, paid_pct, procured_cost, margin (manager-only),
        next_delivery_date, remaining_items, overdue, exposure_flag, deal (custom_crm_deal)
  paid_pct      = Σ(SI.grand_total − SI.outstanding) / Σ SI.grand_total (SIs against this SO)
  procured_cost = Σ PO Item.amount WHERE sales_order = SO AND docstatus=1
  exposure_flag = per_delivered − paid_pct ≥ 25 pts   (treasury-lag amber signal)
move_so_stage(name, stage)      # all team; soft guards (confirm dialogs, never hard block):
  - → Invoiced while a delivered DN lacks an attached acceptance act
  - → Paid while paid_pct < 100
  - → past Contract signed while docstatus = 0
  writes timestamped Comment on SO (stage history = SO timeline, no log doctype)
so_stage_save / delete / reorder    # manager-only (mirror deal-status trio)
create_so_from_deal(deal)           # won deals only; maps items; sets both link fields
intake_lead(token, channel, customer_name, contact, text, payload_json)
  guest-callable, per-channel secret token, rate-limited; creates CRM Lead with source +
  payload in notes. Telegram bot = thin webhook consumer; web form posts directly.
```

**Lazy stage placement** (no backfill): stage=null cards render in a computed home
(draft→first; 0% delivered→Contract signed; partial→Delivery; 100% delivered & billed<100→
Invoiced; else Paid); first drag persists. `sales_order_detail` gains `remaining_qty` per line,
linked POs/DNs/SIs/PEs timeline, deal chip.

## 4. Frontend — `pages/sales/SalesOrderBoard.vue`

Route `/sales/board`, tab "Order Board". Kanban mechanics cloned from Deals.vue; ListToolbar
grammar (no Apply buttons, ⌘K search, one primary). Column header: stage · count · Σ value.

Card: customer + SO no. + deal chip · contract value + age · progress bars Delivered/Billed/Paid
(three thin bars — Paid is the treasury one) · finance row: margin (role-gated, `font-monospace`)
· footer signal priority: overdue > exposure_flag ("82% delivered, 30% paid") > missing act
count in Acceptance > next delivery date.

Drawer: header (stage select, deal link), item table (ordered/delivered/remaining/billed),
finance panel (contract · procured · margin · billed · paid — original currencies per v2 rule),
document timeline (PO/DN/SI/PE chips → existing drawers, never Desk), acceptance checklist
(per delivered DN: act attached ✓/✗, upload action attaches scan to the DN), stage history feed.

**Acceptance act:** DN print format "Акт приёмки-передачи" (ru/uz layouts, railway-acceptable),
print route clone of InvoicePrint; signed scan attached back to DN.

## 5. Cross-cutting

i18n ×5 (stage fixtures install EN only where none exist — tenant renames in their language);
hard rules per CLAUDE.md (formatDate, MoneyInput, striped tables, one primary per region);
margin visibility = Sales Manager+ only; module `sales` (no new module key).

## 6. Acceptance

- Won deal → SO with items intact; SO card shows deal chip; deal shows SO chip.
- PO raised via MR→PO against the SO appears in procured_cost on next board load; margin correct.
- PE allocated to the SO's SI moves paid_pct; exposure flag appears at 82% delivered / 30% paid.
- Move to Invoiced with a delivered DN missing an act → confirm dialog naming the DN.
- Telegram webhook → Lead with source badge on Deals board ≤10 s; invalid token → 403, rate-limited.
- 5–10 cards render instantly; stage CRUD live-updates the board; five languages, no overflow @1280.

## 6c. Order calendar (added 2026-06-12 — logistics & milestone view)

Month grid + week agenda over all open orders. Route `/sales/board/calendar` (tab toggle
Board ⇄ Calendar on the same page, shared filters). Reuse `CalendarMonth.vue`.

**Event sources — two kinds, zero new doctypes:**
1. *Derived from documents (auto, read-only):* SO item `delivery_date` (planned delivery, teal) ·
   PO item `schedule_date` (expected arrival from supplier, gray) · SI `due_date` (payment due,
   blue) · CRM Deal tender deadlines (red). Overdue variants tint red.
2. *Manual milestones via native **Event** doctype* (`reference_doctype/_name` → Sales Order;
   no schema): logistics steps the documents can't know — "Загружен у поставщика", "В пути",
   **"На таможне" / "Растаможен"**, "Сертификация", custom notes. Category encoded in Event
   `subject` prefix or `color`; created/dragged from the calendar (drag = update event date;
   document-derived events are not draggable — change the document instead).

**Customs ↔ landed cost tie-in:** the "Растаможен" milestone's drawer offers **"Add landed
costs"** → opens the Landed Cost Voucher flow (purchasing spec §C) prefilled with the order's
Purchase Receipt(s), so customs duty/freight/certification land in item valuation the moment
clearance happens — margin on the board card updates the same day, not at month-end.

**API:** `order_calendar_feed(company, from_date, to_date, customer?, order?)` → merged event
list `{date, kind, label, color, order, customer, ref_doctype, ref_name, draggable}`;
`save_order_milestone(order, date, kind, note?)` / `move_milestone(event, date)` /
`delete_milestone(event)` (team-wide, same access as board).

**UI:** color legend (delivery teal · customs amber · payment blue · acceptance purple ·
deadlines red); day-cell chips max 3 + "+N" overflow → day panel; click chip → SO drawer at the
relevant section; "today" column highlighted; filters shared with the board (customer, owner);
hard rules apply (formatDate, no Desk, plain tables).

**Acceptance:** customs milestone created on the calendar appears on the order drawer timeline;
dragging it updates the Event date and the SO timeline comment; "Растаможен" → LCV created →
card margin reflects landed cost within one reload; SI due_date events turn red the day after
due when outstanding > 0; week with >3 events per day collapses to "+N" correctly.

## 7. Out of scope (v1)

- Telegram bot implementation itself (separate small task; only the intake endpoint is here).
- Auto-advancing stages from DN/SI/PE events (manual drag is the point; revisit with usage).
- Tender-portal scraping/integration; per-stage SLA timers; PO board mirror.
- Weighted pipeline forecasting; bid/bond guarantee tracking (ask if needed — likely P2).
