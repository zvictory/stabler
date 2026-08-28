# Kassa + Tender (K1–K4, T1/T2/T5) — PROD Deploy Runbook

**You run this. I cannot SSH.** Prod is **not a git repo** — deploy is rsync of
`apps/stabler/` from your local bench to `ice-production`. Shared app code → a
change + restart takes effect on **every stabler tenant at once** (anjan, dts,
horeca, laminor, mikas, smartbox). The new behavior is gated (`enable_tender` +
kassa bot `site_config`), so only Mikas actually lights up; the other 5 get the
code, not the behavior.

**This release needs BOTH `migrate` AND `restart`:**
- `migrate` → patch **v52** (`Journal Entry.custom_crm_deal`) + **2 new
  doctypes** (`Stabler Kassir`, `Stabler Kassir Account`). All guarded/idempotent.
- `restart` → `.py` changed (`money.py`, `tender.py`, `integrations/kassa/*`).

Commits in this release (local): `6772cfc` `9c53215` `f3f0e48` `4fb2cd8`
`5b52b86` `c8d8746` `75cc839`.

> If the earlier imports release (Proforma / HS Duty Rate, v50–v51) was NOT yet
> deployed, this same rsync+migrate ships it too — one migrate runs all pending
> patches and syncs all doctypes. That's fine and intended.

Pre-flight already green locally: 105 pure tests, py_compile clean, doctype JSON
valid, working tree committed.

---

## 1. Confirm the target has stabler

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site anjan.erpstable.com list-apps | grep stabler'
```

## 2. Backup FIRST (mandatory — prod has no git)

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lh /root/stabler-app-*.tgz | tail -1'
```

## 3. Dry-run the rsync (SEE what moves before it moves)

**CRITICAL cwd — run from `apps/`, NOT `apps/stabler/`.** The rsync source is
`stabler/` (relative), so cwd must be the bench **apps** dir where `stabler/` =
the whole app `apps/stabler/`. If you `cd apps/stabler` first, `stabler/`
resolves to the inner Python module `apps/stabler/stabler/` while the remote is
still the whole app — rsync then reports a bogus 1500+ deletions and would even
try to delete the sibling `stable-erp-website/`. **Always eyeball the dry-run
delete list; if `stable-erp-website/` or any sibling appears, STOP — wrong cwd.**

```bash
cd /Users/zafar/frappe-bench-local/apps        # apps dir, not apps/stabler
pwd                                             # must end in /frappe-bench-local/apps
rsync -rltzn --no-owner --no-group --delete-excluded \
  --exclude='.git' --exclude='node_modules' --exclude='dist' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.claude' \
  --exclude='.tx_*.json' --exclude='stabler/translations/.tx_*.json' \
  --exclude='graphify-out' --exclude='.smoke' --exclude='.smoke_*' \
  --exclude='tests' --exclude='*.tgz' --exclude='.DS_Store' \
  --exclude='.obsidian' --exclude='agent-os' --exclude='.beads' \
  --exclude='*.cjs' --exclude='.sfc_*' --exclude='.chk*' --exclude='.check_*' \
  --exclude='*_PROMPT.md' --exclude='ORCHESTRATOR_PROMPT.md' \
  --exclude='deploy_*.sh' --exclude='settings.local.json' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Eyeball the list. You MUST see: `integrations/kassa/{__init__,_flow,bot,webhook}.py`,
`stabler/doctype/stabler_kassir/*`, `stabler/doctype/stabler_kassir_account/*`,
`patches/v52_je_tender_deal.py`, `patches.txt`, `api/money.py`, `api/tender.py`,
`public/js/pages/money/Expenses.vue`, `public/js/pages/tender/{PoControlBoard,BidPricing}.vue`,
`translations/{en,ru,uz,uzc,tr}.csv`. You must NOT see `tests/`, `graphify-out/`,
any `*_PROMPT.md`, or scratch. `dist/` is gitignored/excluded (rebuilt on prod).

## 4. Real rsync (drop the `n`)

Still from `apps/` (same cwd as the dry-run — re-check `pwd`).

```bash
rsync -rltz --no-owner --no-group --delete-excluded \
  --exclude='.git' --exclude='node_modules' --exclude='dist' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.claude' \
  --exclude='.tx_*.json' --exclude='stabler/translations/.tx_*.json' \
  --exclude='graphify-out' --exclude='.smoke' --exclude='.smoke_*' \
  --exclude='tests' --exclude='*.tgz' --exclude='.DS_Store' \
  --exclude='.obsidian' --exclude='agent-os' --exclude='.beads' \
  --exclude='*.cjs' --exclude='.sfc_*' --exclude='.chk*' --exclude='.check_*' \
  --exclude='*_PROMPT.md' --exclude='ORCHESTRATOR_PROMPT.md' \
  --exclude='deploy_*.sh' --exclude='settings.local.json' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## 5. Build assets on prod

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## 6. Migrate EVERY stabler tenant (patch v52 + doctype sync)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for S in $(ls sites | grep "\."); do
  bench --site "$S" list-apps 2>/dev/null | grep -q "^stabler" || continue
  echo "=== migrate $S ==="
  bench --site "$S" migrate
done'
```

Spot-check on a secondary + on Mikas:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && bench --site dts.erpstable.com mariadb -e \"SELECT name FROM tabDocType WHERE name LIKE 'Stabler Kassir%';\""
ssh ice-production "cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com mariadb -e \"SELECT fieldname FROM \\\`tabCustom Field\\\` WHERE dt='Journal Entry' AND fieldname='custom_crm_deal';\""
```

## 7. Restart (blips ALL tenants — schedule for low traffic)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

> `bench restart` restarts the whole bench → a brief blip for **all** tenants,
> not just Mikas. Do it in a quiet window or accept the blip explicitly.

---

## 8. Post-deploy smoke (per CLAUDE.md + this release)

Record-form regression (direct-URL refresh must open populated, not blank "New"):

- Open an existing PINV / Sales Invoice / PO / Quotation / Payment by pasting its
  URL and hitting refresh — must render in view/edit state.

Kassa + tender arc (Mikas):

1. `…/stabler#/money/expenses` — the expense form shows the optional **Tender
   (Deal)** picker (tender module on). Record an expense with a deal → the list
   row shows the deal chip.
2. `…/stabler#/tender/board` → open a deal → a PO's **landed editor**:
   - customs line: enter a ТН ВЭД → duty/excise/VAT auto-fill with a green
     "from HS table" source (needs HS Duty Rate rows seeded — see below).
   - "VAT recoverable (registered)" switch ON → landed = duty(+excise) only; the
     footer shows a green recoverable-VAT figure.
   - Actual cell: link a PInv/PE/JE + pull → actual becomes read-only from GL,
     "N from GL" shows in the footer.
3. Bid pricing (actual block): a **Kassa expenses (GL)** line appears for
   deal-tagged expenses; Остаток drops by the after-tax kassa spend.
4. Money log flowing: after one payment, a line lands in
   `sites/anjan.erpstable.com/logs/stabler.payments.log`.

## 9. Data + config the features need (NOT shipped by deploy)

- **HS Duty Rate rows** (for T2 auto-fill): seed per ТН ВЭД (duty/excise/VAT +
  effective_from) via the HS Duty Rate doctype. Without rows, the calc falls
  back to manual entry (orange hint) — no crash.
- **Kassa CoA tree** (Mikas): open the Kassalar › {AKassa…} × {UZS/PK/USD} Cash
  accounts — see `docs/plans/2026-07-17-kassa-bot-runbook.md` §2.
- **Telegram kassa bot** (Mikas): `kassa_telegram_token` + `kassa_telegram_secret`
  in the Mikas site_config, `setWebhook`, and a **Stabler Kassir** record per
  kassir — same runbook §3. Fail-closed: no secret → webhook 403, other tenants
  unaffected.

## 10. Rollback

```bash
# restore the step-2 tar, re-own, rebuild, restart
ssh ice-production 'cd /home/frappe/frappe-bench/apps && tar xzf /root/stabler-app-<TIMESTAMP>.tgz && chown -R frappe:frappe stabler && cd /home/frappe/frappe-bench && bench build --app stabler && bench restart'
```

The v52 field + new doctypes carry no data on first deploy, so a rollback of code
is clean; migrate is idempotent, so re-running it after a re-deploy is safe.
