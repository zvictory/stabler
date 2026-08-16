# Claude Design promptu — Remittance Operations Center

Ekler olarak birlikte gönder:
- `Vehicle Finance Center v3.html` (onaylanmış görsel dil ve yoğunluk referansı)
- `Imports module score cards design.zip`
- `Tender Panel Tasarım Geliştirmesi (2).zip`

Kaynak plan: `docs/plans/2026-08-16-remittance-operations-center.md`

---

```text
STRICT DESIGN-ONLY TASK.

Create only one standalone interactive HTML design prototype.

Do not modify the Stabler repository.
Do not edit Vue, Python, JSON, translations, routes, doctypes or tests.
Do not implement ERPNext APIs, database models, migrations or accounting logic.
Do not run git, bd, bench, migrate, build, deploy, SSH or production commands.

The words "implement" and "interaction" in this task refer only to simulated
client-side behavior inside the standalone HTML prototype.

Write exactly one deliverable:
Remittance Operations Center.dc.html

Inline all CSS and JavaScript. No external dependencies. The file must open
directly in a browser. English-first UI labels. Use clearly illustrative,
anonymized prototype data. Do not present fake data as production data.

REFERENCE MATERIALS

Study the attached files first.

"Vehicle Finance Center v3.html" is the approved house style. Match its:
- compact single-line tables with an explicit № column
- score-card anatomy and per-currency rows
- Operations-first work queues with owner and next-action columns
- 40px primary controls, 24px small desktop table controls
- responsive drawer navigation, horizontally scrollable module tabs
- calm modernist Tabler direction, monospace for money and identifiers

Do not copy Vehicle Finance or Imports domain concepts. This is a different
product.

PRODUCT MODEL

A single company operates a cash remittance network between its OWN branches.
A customer hands cash to a cashier at the origin branch; a different cashier at
the destination branch pays a receiver in cash.

There is no external payout partner, no partner prefunding, no blockchain, and
no KYC engine in this version.

Currencies: USD, EUR and USDT.
USDT is treated purely as another cash/account balance. The interface must NOT
claim on-chain verification, wallet addresses, network names, confirmations or
transaction hashes anywhere.

One transfer has exactly one send currency and one receive currency, fixed at
registration.

Transfer lifecycle:

  Register  → cash taken at origin, receiver obligation created
  Payout    → receiver paid at destination, obligation closed
  Refund    → only before payout, full make-whole to the sender

Commission is NOT revenue at registration. It is deferred and recognized only
when the payout completes. A refund before payout produces no profit or loss.

Refunds are always full: principal plus commission, in the original send
currency. There is no partial refund and no partial payout.

Pricing is never typed by the cashier. A Finance Manager publishes a daily
corridor tariff (customer rate, fixed fee, percentage fee, optional min/max)
and the quote is frozen onto the transfer at registration. The cashier only
enters the amount and chooses whether commission is Inclusive or Exclusive.
That choice is locked once registered.

Receiver verification is name + pickup code only. The code is 8 characters,
server-generated, shown exactly once, valid for 72 hours, single-use, and locks
the transfer after 5 failed attempts. A Finance Manager can unlock it. No read
screen ever redisplays the code.

Authority:
- Cashier registers and pays out directly, and may do both on the same transfer.
- Refund always requires Finance Manager approval.

INDEPENDENT STATE AXES

Show these as four separate axes, never merged into one badge:

1. Operational: Draft, Registered, Paid Out, Refunded, Expired, Exception
2. Accounting:  Unposted, Posted, Reversed, Posting Error
3. Verification: Not Issued, Active, Locked, Consumed, Expired
4. Refund:      None, Requested, Approved, Rejected, Completed

A transfer can be Registered + Posted + Locked at the same time. Locked and
Expired carry visual urgency; the other axes stay visible as secondary facts.

INFORMATION ARCHITECTURE

Build one connected application prototype with working screen transitions:

1. Operations — default landing page
2. Transfers
3. Reconciliation
4. New Transfer — the single prominent primary action

Payout and Refund are not top-level pages. They are entered from a work queue
row or from the transfer detail screen.

SCREEN 1 — OPERATIONS

Score cards:
- Registered today
- In transit / ready for payout
- Paid out today
- Commission and FX revenue recognized (this month)
- Exceptions

Currency rule, non-negotiable: never combine USD, EUR and USDT into one
monetary headline. In "All currencies" show one line per currency. Counts may
be combined. Never show an invented converted equivalent.

Work queues:
- Ready for payout
- Expiring within 12 hours
- Expired / refund required
- Refund awaiting approval
- Locked pickup code
- Accounting / reconciliation exception

Each row shows: reference, sender, receiver, corridor (origin → destination
branch), sender pays, receiver gets, age or time-to-expiry, owner, next action.

Row actions depend on the queue:
- Ready for payout → Pay out, Open transfer
- Expiring / Expired → Request refund, Open transfer
- Refund awaiting approval → Approve refund, Reject, Open transfer
- Locked pickup code → Unlock (Finance Manager only), Open transfer
- Accounting exception → Open transfer, Open reconciliation

Include a branch filter, a currency filter and a corridor filter.

SCREEN 2 — NEW TRANSFER

A compact guided form, not an oversized wizard. Inputs on the left, a sticky
quote summary on the right.

1. Origin branch, destination branch, corridor
2. Sender name, receiver name
3. Amount, and an Inclusive / Exclusive commission toggle
4. Quote panel — presented as computed by the server, read-only:
     sender hands over
     fixed fee + percentage fee (shown separately)
     applied daily corridor rate
     receiver gets
     expires at (72 hours)
5. Cash-in branch and account confirmation
6. Final review, then Register

The cashier must NOT be able to pick the commission account, the in-transit
account or the rate. Show those as policy values coming from the corridor.

Show the invariants visually:
- one send currency and one receive currency per transfer
- the quote is frozen at registration
- commission becomes revenue only at payout

SCREEN 3 — PICKUP CODE RECEIPT

A dedicated post-registration screen, shown exactly once.

- Large monospace Remittance ID and pickup code
- Receiver name and the exact amount they will collect
- Corridor and expiry timestamp
- Copy and Print actions
- A mandatory acknowledgement checkbox ("I handed over / saved the code")
  that gates leaving the screen
- A clear, calm warning that the code cannot be shown again

Reopening the transfer later must visibly show the code as unavailable, not
masked-but-recoverable.

SCREEN 4 — PAYOUT

1. Find the transfer by Remittance ID or reference
2. Show receiver name, corridor and the exact receive amount before any input
3. One accessible pickup-code input, with attempt counter (n of 5)
4. Destination branch and payout account confirmation
5. Cash confirmation and an exact posting preview of what will be recorded
6. Pay out
7. Receipt

Include the locked state: after 5 failed attempts the input is disabled and the
only path forward is a Finance Manager unlock.

SCREEN 5 — REFUND

Available only for Registered or Expired transfers.

- Sender name verification
- Mandatory reason
- Full make-whole preview: principal + commission returned, no profit or loss
- Manager approval step, shown as a distinct authority gate
- On completion, the pickup code is invalidated

SCREEN 6 — TRANSFERS

Compact table:

№ | Reference | Sender | Receiver | Corridor | Sender pays | Receiver gets |
Registered | Expires | Operational | Verification | Owner | Actions

Filters: status, send currency, receive currency, corridor, branch, date range,
expiry window, exceptions only. One search field covering reference, sender,
receiver and branch.

No multi-select. No bulk financial actions.

A row opens a read-only quick-preview drawer. Real work opens the full transfer
detail screen, which contains:
- the frozen quote
- all four state axes
- a stage timeline (Register / Payout / Refund) with timestamps, branch and user
- linked Journal Entries per stage
- pickup-code attempt history (attempts and lock events only, never the code)
- refund request and approval trail
- full audit log

SCREEN 7 — RECONCILIATION

Per branch and per currency:
- register cash-in
- open in-transit liability
- payout and refund cash-out
- deferred versus recognized commission
- FX margin
- master record versus Journal Entry variance
- aged and expired transfers

An exception list with a clear "what to do next" per row. Variances are never
auto-corrected in the UI; they are surfaced as blocking work.

VISUAL DIRECTION

Serious operational ERP: compact, calm, information-rich, highly scannable,
desktop-first, modernist Tabler-inspired, consistent with the attached
Vehicle Finance Center v3.

- restrained neutral palette, one primary accent
- red only for real exceptions (expired, locked, posting error, variance)
- amber for expiring-soon and awaiting-approval
- green for paid out and settled
- monospace for money, references and pickup codes
- subtle borders, negative space instead of card-inside-card
- one compact desktop density

Avoid: gradients, neon, huge headings, decorative illustrations, generic SaaS
styling, giant progress bars, status conveyed by color alone, excessive
animation, fake AI-assistant elements.

INTERACTION AND STATES

Working, simulated client-side behavior required for:
- navigation between all screens
- branch, corridor and currency filters (affecting score cards and queues)
- work-queue actions opening the right flow
- New Transfer: Inclusive/Exclusive toggle recomputing the quote
- amount input recomputing sender pays / fee / receiver gets
- registration producing the one-time pickup-code screen
- payout code entry: correct code, wrong code, attempt counter, locked state
- refund request → manager approval → completed
- quick-preview drawer
- transfer detail tab switching
- loading skeleton, empty state and inline validation examples
- permission-denied example (cashier attempting a manager-only action)

Validate at 1440px, 1024px, 768px and 390px. No page-level horizontal overflow.
Below 992px the navigation collapses to a drawer with no unreachable item.
Below 768px every interactive target is at least 40×40px. Wide tables scroll
inside their own container with a visible overflow affordance.

ACCESSIBILITY

- every visible label bound to its input with for/id
- aria-label on icon-only buttons
- aria-pressed on segmented controls
- visible keyboard focus states
- the pickup-code input has a unique accessible name and an announced
  attempt-counter

DELIVERABLE

1. One self-contained interactive file: "Remittance Operations Center.dc.html"
2. A thumbnail if the design environment supports it.
3. A short design note covering:
   - information architecture and why Operations is the default landing
   - how the one-time pickup code shapes the registration flow
   - how the four state axes are kept visually separate
   - how multi-currency false totals are prevented
   - which UI decisions were intentionally postponed

Do not create Vue components or backend code.
This deliverable is for visual review and product discussion before
implementation.
```

---

## Prompt sonrası kabul kontrolleri

Design geldiğinde şunları ölç, "güzel görünüyor" ile geçme:

- USD/EUR/USDT hiçbir yerde tek başlıkta toplanmıyor
- Pickup kodu yalnız register sonrası ekranda; transfer detayında "unavailable"
- 5 hatalı deneme → input disabled + manager unlock yolu görünür
- Refund yalnız Registered/Expired'da, manager approval ayrı kapı olarak duruyor
- Dört durum ekseni ayrı ayrı okunabiliyor
- Kasiyer hiçbir ekranda kur, komisyon hesabı veya in-transit hesabı seçemiyor
- Quote'un server-side olduğu ve register'da donduğu görsel olarak anlaşılıyor
- 390px'te hiçbir navigasyon öğesi erişilemez değil, sayfa yatay taşmıyor
- Frappe Desk (`/app/...`) bağlantısı yok

---

# v2 revizyon promptu (2026-08-16)

v1 kurul kararı: **REJECT** — payout kaydı FX marjı kadar dengesizdi ve karşılığı
olan bir hesap dosyada yoktu. Bilgi mimarisi ve görsel dil korunuyor, model
değişiyor.
Gerekçe ve kanıt: `docs/plans/2026-08-16-remittance-design-council-decision.md`

Ekler: `Remittance Operations Center -standalone source-.html` (v1) ve
`support.js`. v1'in bilgi mimarisi, örnek verisi ve görsel dili korunacak.

```text
Revise the existing "Remittance Operations Center" prototype in place.

DESIGN-ONLY:
- Modify only the standalone HTML prototype.
- Do not modify the Stabler repository or any production file.
- Preserve the existing information architecture, sample data, screens,
  filters, visual language and everything not listed below. Do not redesign.

The prototype was reviewed and accepted in substance. Fix only these items.

0. PRICING MODEL REPLACED — one percentage, charged on the principal

This is the largest change in this revision. The old pricing model is cancelled:
there is no fixed fee, no minimum and no maximum. Pricing is exactly one
percentage — for example 1.00% or 0.50%. Section 0c below says where that
percentage comes from: the cashier types it. There is no tariff record and no
corridor object anywhere in this design.

The percentage is always charged on the PRINCIPAL — the amount that actually
gets transferred — in both Inclusive and Exclusive mode. It is never a
percentage of what the customer hands over.

  Exclusive: principal = the typed amount
             commission = round(principal x pct / 100)
             sender hands over = principal + commission        (derived)

  Inclusive: sender hands over = the typed amount
             commission = round(tendered x pct / (100 + pct))
             principal = tendered - commission                 (derived)

One rounding per branch — the commission — and the third money figure is always
the plug, never rounded independently. principal + commission = tendered must
close exactly at currency precision in every case.

Worked at 1.00%, so you can check the screen against it:

  Exclusive, typed 500.00 -> principal 500.00, commission 5.00, tendered 505.00
  Inclusive, typed 500.00 -> tendered 500.00, commission 4.95, principal 495.05

Both charge 1.000% of the principal: 5.00/500.00 and 4.95/495.05. Under the old
model the Inclusive case charged 5.00 on a 495.00 principal, which is 1.0101% —
a different price for the same tariff depending on how the cashier entered it.
That is the defect this change removes, so do not reintroduce it anywhere.

THE QUOTE PANEL, rewritten. Same seven rows in both modes, same order, same
labels — only the values change and only the "(entered)" badge moves. Group them
under two sub-headers with a divider so a cashier can either read the two bold
lines or walk a customer through one cluster:

  Route                             Tashkent · TAS-C -> Istanbul · IST-1
                                    note: "USD -> EUR"
  --- What the customer pays ---
  Principal                         500.00 USD  (entered)      [Exclusive]
  Commission                        5.00 USD
                                    note: "1.00% of principal (500.00 USD)"
  Sender hands over  (bold)         505.00 USD
  --- What the receiver collects ---
  Exchange rate applied             1 USD = 0.9250 EUR
                                    note: "Entered by you · frozen at registration"
  Receiver gets  (bold)             462.50 EUR
  Expires at                        Aug 19, 09:12

Principal is a permanent, visible line in BOTH modes and sits directly above
Commission, so the two numbers that demonstrate the percentage are always
adjacent. The commission note must always cite the principal, never the tendered
amount — "1.00% of principal (495.05 USD)" in the Inclusive case above. Writing
"1.00% of amount tendered" is factually wrong under this model.

TOGGLE MICROCOPY, exact strings, one line each beside the control — not
buried in the quote panel where it only appears after the choice is made:

  Exclusive:  "Fee is added on top. Customer hands over more than you type."
  Inclusive:  "Fee comes out of this. Customer hands over exactly what you type."

The microcopy says what the customer experiences; the Principal row carries the
arithmetic. Do not try to explain the percentage basis in the toggle text.

SWITCHING THE MODE IS A RE-QUOTE, NOT A VIEW CHANGE. This is a measured fact,
not a preference: rounding to cents makes the two modes mathematically
non-invertible, so for roughly 1 amount in 100 the numbers shift by exactly one
minor unit when you flip the toggle. Design for it instead of hiding it:

- Flipping the toggle with an amount already typed replaces the quote. Show a
  short inline notice directly under the toggle, not a modal:
  "Quote updated — switching how the fee is charged recalculates the amounts."
  It appears on flip and fades on the next keystroke.
- Never present the two modes as the same transfer shown two ways. Do not
  animate the numbers as if they were converting; replace them.
- The registered transfer stores principal, commission and tendered as three
  fixed values. Every later surface — pickup receipt, payout receipt, transfer
  detail, refund, reconciliation — displays those stored values verbatim. Do not
  design any screen that re-derives an amount from a percentage after
  registration; a recomputed figure can disagree with the receipt in the
  customer's hand by one cent.

THE AMOUNT FIELD changes meaning with the mode, so its label and helper must
change with it:

  Exclusive:  label "Amount to send"
              helper "Commission is added on top of this."
  Inclusive:  label "Amount customer hands over"
              helper "Commission comes out of this; the rest is sent."

DELETE, because the fixed fee and clamp no longer exist:
- the "fixed", "min" and "max" pricing fields;
- the clamp branch in the quote computation;
- the "Fixed fee" quote row, in both the New Transfer panel and the Frozen
  Quote detail tab;
- the "min X / max Y" note under the percentage row;
- the "fixed ..." substring in the audit log's quote-frozen event, leaving
  "rate 0.9250 · 1.00% · exclusive";
- the over-20,000 pre-approval error described in item 10, which belonged to the
  old tariff model.
Reconciliation columns are untouched — they already track commission as one
figure and never split it.

ADD the Principal row wherever Commission already appears: the New Transfer
quote panel, the Frozen Quote detail tab, the pickup-code receipt and the payout
receipt. On the receipts print all four money rows in order: Principal,
Commission, Sender handed over, Receiver collects, plus the applied rate.

0b. THERE ARE NO CORRIDOR RECORDS — DELETE THE WHOLE CONCEPT

This replaces everything an earlier revision said about corridors, corridor
selectors, corridor tariffs and published daily rates. A transfer is simply:
money taken in at one cash desk, a commission, money paid out at another cash
desk. Receivable, commission, payable. Nothing else.

- The origin desk is the cashier's OWN desk. It is displayed, never chosen.
- The cashier chooses a DESTINATION CASH DESK from a flat list. Each entry reads
  as "Istanbul · IST-1", city then desk. There is no corridor picker, no city
  pair object, no "TAS -> IST · USD/EUR" compound row.
- Send currency and receive currency are two ordinary selects, USD / EUR / USDT.
  They may be the same or different.
- Cities are labels on desks. Do not design a city management screen.

Delete from the prototype: the corridor selector, the corridor column in every
table, corridor filters, corridor tariff/limit UI, the corridors settings screen,
and any "corridor" wording in labels, empty states and audit strings. Where a
table needs to show the route, show "Tashkent · TAS-C -> Istanbul · IST-1".

0c. THE CASHIER TYPES THE PERCENTAGE AND THE RATE

There is no published tariff and no mid rate anywhere in this product. Both
numbers are ordinary editable inputs on the New Transfer form:

- "Commission %" — a number input, e.g. 1.00 or 0.50.
- "Exchange rate" — a number input, shown ONLY when send currency differs from
  receive currency. When the two currencies are the same, hide the field
  entirely; do not show it disabled or set to 1.

Both fields are STICKY: the last value the cashier used comes back pre-filled on
the next transfer, so the common case is type-amount-and-go. Mark a pre-filled
value visibly as a carried-over default, e.g. a quiet caption under the field
reading "Same as your last transfer". The cashier can overwrite it freely.

At registration both values are FROZEN onto the transfer. After that no screen
recalculates anything — see the stored-triple rule above. The Frozen Quote tab
shows the commission % and the rate that were used, labelled "entered by
<cashier> at registration".

The words "mid rate", "FX margin", "published rate", "tariff" and "not editable"
must not appear anywhere in the design. Delete every occurrence.

0d. ONE COMPANY, REAL CASH DESKS, REAL GL ACCOUNTS

All four cities live in ONE company. Cash desks are branches, not companies.

- There is NO company selector anywhere. Do not add one. The user picks a CASH
  DESK, never a company or a country.
- Register debits the ORIGIN desk's own cash account. Payout credits the
  DESTINATION desk's own cash account, in the receive currency. Every desk has
  its own cash account per currency, so a desk's book balance equals the
  physical count in that drawer.
- Everything shown on screen posts to a real GL account. Nothing is display-only.
- The in-transit / receiver-obligation balance is a single-company liability
  account, NOT an inter-company due-to/due-from. Do not draw it as a transfer
  between entities.

The settings surface maps exactly THREE accounts, plus the desk accounts:

  Receiver obligation (in-transit)   Liability
  Deferred commission                Liability
  Commission income                  Income

Plus, per cash desk, one cash account per currency it handles. Design a blocking
validation state: a desk missing an account for a currency is shown as
"Not ready — no USD account" and cannot be used for that currency. The error
belongs on the settings screen; at registration the message says which account is
missing and where to fix it.

USDT is treated as an ordinary cash desk. Same screens, same account type, no
wallet integration, no separate "crypto" surface — do not design one. The only
difference is the reconciliation evidence label: "Counted" for USD/EUR rows,
"Wallet balance" for USDT rows. Everywhere else USDT is just a third currency.

1. ACCOUNTING MODEL — receivable, commission, payable. Three items.

The prototype carries the in-transit liability in the SEND currency, invents an
FX margin, and credits it to income at payout with no matching debit — so the
payout preview is out of balance by exactly the margin (0406 +10.74, 0407 +7.80,
0344 +26.32, 0409 +6.31). All of that is gone. There is no FX margin account, no
FX margin income, no FX margin line, no FX margin column.

The approved model, using the existing sample transfer REM-0406
(TAS-C -> BUX-1, USD -> EUR, sender hands over 1,165.65 USD, commission 15.65,
principal 1,150.00, receiver gets 1,049.26 EUR). Company currency is USD:

  REGISTER
    Dr Cash on hand - TAS-C            1,165.65 USD   base 1,165.65
    Cr Receiver obligation - BUX-1                 1,049.26 EUR  base 1,150.00
    Cr Deferred remittance commission                 15.65 USD  base    15.65

  PAYOUT
    Dr Receiver obligation - BUX-1     1,049.26 EUR   base 1,150.00
    Cr Cash on hand - BUX-1                        1,049.26 EUR  base 1,150.00
    Dr Deferred remittance commission     15.65 USD   base    15.65
    Cr Commission income                              15.65 USD  base    15.65

  REFUND (before payout only, full make-whole, profit and loss exactly zero)
    Dr Receiver obligation - BUX-1     1,049.26 EUR   base 1,150.00
    Dr Deferred remittance commission     15.65 USD   base    15.65
    Cr Cash on hand - TAS-C                        1,165.65 USD  base 1,165.65

Apply this to every posting preview, the Journal entries tab, the New Transfer
step-4 policy panel, and the Payout and Refund previews. Each one must balance
on screen. A panel titled "Exactly what will be recorded" that does not balance
is worse than no panel.

Consequences you must carry through:
- The receiver obligation is shown in the RECEIVE currency everywhere. Today five
  places carry it in the send currency (register, payout and refund journal
  entries, the payout preview, the refund preview) while the Operations card
  shows it in the receive currency. The two disagree: Operations totals
  USD 6,614.55 / EUR 7,152.27 / USDT 2,082.48 against reconciliation's
  USD 14,458.25 / EUR 3,278.00 / USDT 2,200.00, with no reconciling item. Both
  screens must read from one source.
- The obligation's company-currency value ALWAYS equals principal, i.e. what the
  sender handed over minus the commission. That is what makes the entry balance.
- A same-currency transfer looks identical, minus the second currency column.
- Reconciliation shows two positions only: deferred commission and recognized
  commission. Delete the "deferred FX margin" position.
- Rounding: never round three legs independently — they stop balancing
  (RMT-2026-0401: 880.47 + 7.54 + 12.00 = 900.01, not 900.00). Round commission,
  derive the rest.

2. NEVER PRINT THE PICKUP CODE ON THE PAYOUT SCREEN

Remove the payHint line that renders "the valid code for <id> is <code>" and
remove the code from the payout view model entirely. It directly contradicts
the line six rows above it ("The code is never displayed on this screen").
If a demo affordance is needed, put it in the browser console, never in the DOM.

3. THE ONE-TIME CODE SCREEN MUST BLOCK NAVIGATION, NOT JUST ITS OWN BUTTON

Today the acknowledgement gates only "Done - open transfer". Clicking the
Transfers tab or any sidebar module leaves the screen and the code is lost
forever. Make every navigation path - module tabs, sidebar, and the
New Transfer action - refuse to leave the receipt screen while the
acknowledgement is unchecked, with the same deny modal used elsewhere.

4. SPLIT REFUND APPROVAL FROM REFUND CASH-OUT

Approving a refund currently posts the cash in one click, from anywhere, with
no cash confirmation - while Payout correctly demands a counted-cash checkbox.
Use the two-step flow the state machine already describes:

  Requested -> (Finance Manager) Approved -> (origin branch, cash counted) Completed

The Approved state must be reachable and visible: it needs its own badge, its
own queue row action ("Pay refund cash"), and a cash-count confirmation before
the refund posts. Rejected remains a terminal manager decision.

5. DRIVE ROW ACTIONS FROM allowed_actions

Add an allowed_actions array to every transfer in the sample data, computed
once, and render every row action list and detail action bar from it. Today the
same eligibility rule is duplicated in three places and the role is not part of
it at all. As a direct consequence: a Cashier must not be offered
"Approve refund", "Reject" or "Unlock" as buttons. The refund screen already
does this correctly with its rfIsMgr / rfGate pattern - make that pattern win
everywhere.

6. MOBILE NAVIGATION AND TOUCH TARGETS

Measured at 390px:
- the module tab strip collapses to 52px while holding 385px of tabs, so no tab
  label is fully visible;
- the "New Transfer" primary action extends past the right edge and is
  unreachable;
- drawer navigation rows are 33px tall;
- the queue reference buttons (REM-0412 etc.) are 62x19px.

Fix all four. Below 992px the header must reflow so that the module tabs and the
primary action are both fully reachable - shorten or drop the page title at that
width rather than clipping the controls. Below 768px every interactive target,
including drawer rows and the bare reference buttons, must be at least 40x40px.
Note that the page reports no horizontal overflow while these controls are
clipped, so verify by measuring control positions, not by checking scrollWidth.

7. PAYOUT LOOKUP BY NAME

The Find box must also match receiver name and sender name, not only an exact
Remittance ID or reference. When more than one transfer matches, show a short
pick list. Receivers routinely arrive without the printed receipt; today the
cashier has to leave Payout, search in Transfers, and copy an ID back.

8. PAGINATION

The Transfers table shows only a count. Add real pagination controls.

9. QUEUE SORTING AND RECONCILIATION SCOPE

- Sort every Operations queue by its own urgency signal: soonest expiry first,
  oldest request first, most failed attempts first.
- Give Reconciliation a date/shift filter defaulting to today, using the same
  pattern as the Transfers date range. A cashier must be able to close their
  own shift; today the figures are all-time cumulative.

9b. NEVER SUM A VARIANCE ACROSS CURRENCIES

The reconciliation JE-variance column adds different currencies into one number.
There are only two real variances in the data: 12.40 USDT (REM-0409) and
-3.20 USD (REM-0410). The table spreads them over three rows and prints 9.20 in
the TAS-C / USD cell, which is literally 12.40 USDT + (-3.20 USD). It does this
directly beneath its own banner reading "Every figure belongs to one branch and
one currency. Nothing is converted or combined."

Carry every variance as a {currency, amount} pair belonging to exactly one
(branch, currency) cell. Never reduce across currencies. Feed the
branch-by-currency table and the exceptions list from one source so they agree
row for row — today the upper table shows a BUX-1 / EUR variance while the
exceptions list has no EUR row at all, because the same transfer is listed
there as TAS-C / USD.

9c. REVENUE AND QUEUE ELIGIBILITY MUST RESPECT THE ACCOUNTING STATE

- Recognize revenue only when the accounting state is Posted. Today the
  month-to-date filter checks only "Paid Out", so REM-0409 — whose own
  exception reads "Payout journal entry rejected: destination cash account
  closed for the period" — supplies the entire USDT 15.90 in "Recognized this
  month" and 1,791.00 of "Paid out today". The same fault feeds the recognized
  and FX columns in reconciliation, where one row shows recognized 15.90 and
  variance 12.40 at the same time.
- The payout queue excludes "Posting Error" but not "Unposted". REM-0414 is
  Registered + Unposted, sits in "Ready for payout" with an active Pay out
  button, and would debit a liability that was never created. Meanwhile the
  journal-entries tab shows it a Posted register entry and the detail header
  claims "Journal entries mirror the master record". Registered + Unposted must
  not be a reachable combination.
- Gate the refund form on eligibility: it currently renders as a sibling block
  to the "not eligible" notice rather than instead of it, so a working refund
  form can appear next to a warning saying refund is impossible.
- Re-validate operational state inside the refund approval action, not just the
  role. Concurrent payout-versus-refund is an explicit acceptance test.

9e. PRECISION FROM METADATA

Amounts are hard-coded to two decimals and rates to four, USDT included. Drive
amount precision from the currency and keep the rate at high precision.

10. SMALLER CORRECTIONS

- Put a one-line plain-English explanation of Inclusive vs Exclusive directly
  beside the toggle, not only as a footnote in the quote panel after the choice.
- Either give the over-20,000 amount an actual "Request Finance Manager
  pre-approval" action, or drop the message.
- Add a "receiver identity checked against document" confirmation to Payout, so
  the name half of "name + pickup code" is actually recorded. Refund already
  requires the sender name to be typed.
- Show a single total commission line next to the fixed/percentage split.
- Move "Recognized this month" to Reconciliation; keep Operations same-day.
- Make the Exceptions card a full-width lifecycle strip below the four financial
  cards instead of an orphaned fifth card.
- Disable the Pay out button until the code is verified and the cash is
  confirmed, instead of catching it with a toast after the click.
- Show a "Request ID" line on the payout receipt and in the audit tab.
- Fix the reconciliation figures so the branch-by-currency table and the
  exceptions list agree with each other.
- Fix data slips: the Exceptions card says 2 expired while the queue holds 1;
  one exception is detected at Aug 16 23:20, in the future; rename the sample
  sender "Zafar Umarov".
- On role="tab" elements keep aria-selected and drop aria-pressed; give the
  transfer-detail sub-tabs the same role="tablist"/role="tab" treatment.
- Ghost or disable the header "New Transfer" button while the New Transfer form
  is open.

11. PRESERVE EVERYTHING THAT PASSED

Do not regress: currency lines never summed; commission deferred at
registration; refund full make-whole with zero profit and loss; cashier cannot
choose rate, commission account or in-transit account; four independent state
axes; pickup code unavailable (not masked) on reopen and absent from lists,
drawer, timeline, audit, data attributes, console and storage; five-attempt
lock with manager-only unlock; real permission-denied modal stating nothing was
posted; no Desk links; every label bound with for/id; aria-live attempt
counter; visible focus states; 100dvh; tables scrolling in their own container;
one centralized status vocabulary; skeleton, empty, inline-validation and
permission-denied states; one compact desktop density.

12. SELF-CONTAINED

Inline the runtime and the CSS. The current file needs support.js and three CDN
stylesheets, so it renders raw template placeholders when opened directly.

Validate at 1440px, 1024px, 768px and 390px by measuring control positions and
sizes, not only page overflow.

DELIVERABLE

One self-contained file: "Remittance Operations Center v2.html"

Plus a short change log: accounting-model changes, security fixes, refund
two-step, mobile fixes, and anything intentionally deferred.
```
