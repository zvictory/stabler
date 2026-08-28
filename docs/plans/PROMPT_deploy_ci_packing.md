# Deploy prompt — Stabler `37e5996` (CI packing/GRN + imports work)

Paste this whole file into Claude Code from `~/frappe-bench-local/apps/stabler`.

---

You are deploying the Stabler app to production. Work carefully and stop at the
first failure — do not improvise past an error.

## What is shipping

Local `main` is at **`37e5996`** — a merge of `codex/ci-packing-grn-foundation`
(`c76f92a`) into `a11b222`. Production was last at **`338478f`**, so this deploy
carries **50 commits**. Highlights:

- **CI packing / GRN foundation** (msa): packing aggregate math, container →
  GRN expected-quantity snapshot with row-level locking, snapshot freeze on the
  first Truck Receipt, CI logistics workspace panel.
- **MSA imports**: PI/CI smart lists with original refs, vendor-category
  dropdown on PI lines, supplier filters scoped to import vendors, CI form
  linked-trucks table, new report pages (PI Progress, PI Group Container
  Status, Sales Detail, Payments Register).
- **anjan**: manufacturing operator board (BOM preview, batch capture),
  asset picker on expense entries.
- **mikas**: kassa shadow bot + mini app.
- **Payments fix**: cancelled/non-submitted invoices excluded from
  `party_payment_defaults` and `create_payment_entry`.
- **i18n**: 72 new strings filled in for all five locales.

## Pre-flight already done locally (do not redo)

- 49 unit tests pass (`test_packing_math`, `test_ci_logistics_workspace_source`,
  `test_receipt_math`, `test_grn_variance_math`, `test_imports_api_invariants`).
- All 20 changed `.vue` files parse + compile (SFC, template, script).
- All 24 changed `.py` files compile.
- `git diff --check` clean; no `/app/` Desk redirects; no bare
  `<input type="date">`; no bare number inputs for money.

## Schema impact

- `patches.txt` is **unchanged** — no new patches.
- `GRN Checklist` gains two columns: `expected_snapshot_locked` (Check) and
  `expected_snapshot_locked_at` (Datetime). Plain `ALTER TABLE ADD COLUMN`,
  no backfill, no unique constraint added (`commercial_invoice` was already
  unique on main).
- **`migrate` is therefore required on every stabler site**, not just anjan.

---

## Step 1 — confirm the target sites

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep -v assets | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q stabler && echo "STABLER: $s"; done'
```

**Record the exact names and the count** — you will migrate every one. The
number is measured, not known: it was 7 until `zuma` was added and every
hand-written copy of the list silently skipped it. If the count differs from
what the last deploy recorded, say so before continuing.

## Step 2 — backup (mandatory, this is the only rollback path)

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lh /root/stabler-app-*.tgz | tail -1'
```

## Step 3 — rsync DRY RUN (cwd trap — read this)

Run from the bench **`apps/`** directory so the relative source `stabler/`
resolves to the whole app. Running it from inside `apps/stabler/` would make
`stabler/` resolve to the inner Python module and produce a bogus mass-delete.

```bash
cd ~/frappe-bench-local/apps
rsync -rltzn --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

**Abort immediately** if the output mentions `stable-erp-website/`, any sibling
app directory, or a large `deleting` list. Show me the summary before Step 4.

## Step 4 — rsync for real

Same command **without** `n` (i.e. `-rltz`), then fix ownership:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Step 5 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## Step 6 — migrate EVERY stabler site

`migrate` is per-site; rsync and restart are bench-wide. Skipping a site leaves
its `expected_snapshot_locked` columns missing and the GRN snapshot freeze will
throw at runtime. Run them one at a time and report each result:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  echo "=== $s ==="; bench --site "$s" migrate 2>&1 | tail -5; done'
```

Adjust the site list to whatever Step 1 actually returned.

## Step 7 — restart

`bench restart` restarts the whole bench, so **every tenant gets a brief blip**.
Confirm the timing is acceptable, then:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

## Step 8 — verify the new columns landed everywhere

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  printf "%-28s " "$s"; bench --site "$s" execute frappe.db.has_column --kwargs "{\"doctype\":\"GRN Checklist\",\"column\":\"expected_snapshot_locked\"}" 2>&1 | tail -1; done'
```

Every line must report `True`.

## Step 9 — MSA backfill DRY RUN ONLY

**Do not apply.** Run both with `dry_run=1`, capture the full output, and show
it to me. I will review the reports before any apply.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.integrations.msa_migrate.pi_ref_backfill.run --kwargs "{\"dry_run\": 1}"' 2>&1 | tail -60
```

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.integrations.msa_migrate.ci_backfill.run --kwargs "{\"dry_run\": 1}"' 2>&1 | tail -80
```

Both are idempotent and read-only in dry-run mode. Report the `summary:` line
from each, plus every `NO_SUPPLIER`, `PI unresolved`, and `MULTI_PI` row.

## Step 10 — smoke checks (every release)

1. **Direct-URL / refresh load of a record form.** Paste an existing record URL
   (do not click through from the list) and hit refresh. It must open populated
   and in view/edit state — **not** a blank "New …" form. Do one each for:
   - `https://msa.erpstable.com/stabler#/imports/commercial-invoices/<existing CI>`
   - `https://msa.erpstable.com/stabler#/imports/proformas/<existing PI>`
   - `https://anjan.erpstable.com/stabler#/purchasing/invoices/<existing PINV>`
   - one Sales Invoice, one Purchase Order, one Payment Entry.
2. **Supplier filters** on `#/imports/commercial-invoices` and
   `#/imports/proformas` list only meat suppliers, not the full supplier table.
3. **CI detail page loads** and the Logistics readiness panel renders (it may
   say Incomplete — that is fine; it must not be blank or error).
4. **Money/GL log is flowing.** Record one payment on anjan, then confirm a new
   line appears in
   `sites/anjan.erpstable.com/logs/stabler.payments.log`.
5. **Spot-check a secondary site** (not anjan) — open `dts` or `horeca` and load
   any list page, to prove the shared code change did not break a tenant that
   does not use imports.

## Rollback

Restore the Step 2 tarball, `chown -R frappe:frappe`, `bench build --app stabler`,
`bench restart`. The schema columns are additive and harmless if left in place.

## Known-pending (do NOT try to finish in this session)

- Task 6 steps 2–4 of the CI-packing plan: `bench --site <site> run-tests
  --module stabler.tests.test_ci_packing_grn_integration`, plus browser evidence
  for the Ready / Incomplete / Mismatch states and the snapshot-lock rejection.
- Codex has **uncommitted work in progress** in
  `.worktrees/ci-packing-grn-foundation` (`grn_checklist.py`,
  `packing_service.py`, `test_ci_packing_grn_integration.py`). It is **not** in
  this deploy. Do not commit or discard it.
- The operational consequence of the "Ready" gate: the **first** Truck Receipt
  on a CI is blocked until every container packing list is complete and
  reconciled. If msa staff hit this, it is by design — report it, do not patch
  around it.
