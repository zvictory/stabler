# Imports (WP-I1…I16) — PRODUCTION Deploy Runbook

**You run this. I cannot SSH.** Prod is **not a git repo** — deploy is rsync of
`apps/stabler/` from your local bench to `ice-production`. A code change under
`apps/stabler/` + restart takes effect on **every stabler tenant at once**
(enumerate them, never hand-write the list), but the imports UI/endpoints are
gated on `enable_imports`, so only companies with the module on will see them.

**This release needs BOTH `migrate` AND `restart`:**
- `migrate` → 3 new doctypes (Proforma Invoice, Proforma Invoice Item, HS Duty
  Rate) + 2 patches (v50 CI earmark, v51 CI↔Proforma) + 3 new Customs
  Declaration fields.
- `restart` → many `.py` changed (imports.py, purchasing.py, and the pure
  helpers). Restart blips the whole bench briefly for every tenant — schedule
  for low traffic or accept the blip.

What ships (this series): `stabler/api/imports.py`, `purchasing.py`, the pure
helpers (`_import_exposure`, `_ci_to_pinv`, `_advance_aging`, `_fx_reval`,
`_customs_estimate`, `_kts_amendment`, `_proforma`); doctypes proforma_invoice(+item),
hs_duty_rate; patches v50/v51; the Customs Declaration field additions; SPA
(ProformaInvoices.vue, Suppliers.vue, ImportsDashboard.vue, router.js, status.js,
api/imports.js); 5 translation CSVs.

---

## 0. Pre-flight — LOCAL, before touching prod

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler

# a) Prove it compiles + the accounting invariants hold.
bench build --app stabler
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_ci_to_pinv stabler.tests.test_import_exposure \
  stabler.tests.test_imports_api_invariants stabler.tests.test_advance_aging \
  stabler.tests.test_fx_reval stabler.tests.test_customs_estimate \
  stabler.tests.test_kts_amendment stabler.tests.test_proforma_transition \
  stabler.tests.test_proforma_invoice_doctype stabler.tests.test_vendor_exposure_isolation
# expect: OK (73 tests)

# b) The working tree has scratch files that must NOT ship. They are covered by
#    the rsync --exclude list in step 3, but eyeball what's dirty first:
git status --short | grep -vE 'stabler/(api|public|stabler|translations|patches)/'
```

If anything business-critical is uncommitted, commit it (explicit paths only —
never `git add -A`). The stray `*.md` prompts, `.cjs`/`.py` check scripts,
`graphify-out/`, `agent-os/`, `.obsidian/` are scratch and are excluded below.

## 1. Confirm the target site actually has stabler

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site anjan.erpstable.com list-apps | grep stabler'
```

## 2. Backup first (mandatory — prod has no git; this tar is the only rollback)

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lh /root/stabler-app-*.tgz | tail -1'
```

## 3. rsync source → prod (NO --delete; exclude scratch + build/junk)

```bash
cd /Users/zafar/frappe-bench-local/apps

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
  --dry-run \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

- **Run with `--dry-run` FIRST** (as above) and read the file list. It must show
  your `stabler/api/*.py`, doctype json, patches, and `public/js` files — and
  NONE of the scratch `.md`/`.cjs`/`.py` prompts. `tests/` is excluded on
  purpose (guard tests don't run on prod).
- When the dry-run looks right, **remove `--dry-run`** and run it for real.
- `--delete-excluded` prunes any previously-shipped scratch on prod but, with NO
  plain `--delete`, never removes real prod files that aren't in your tree.

Then fix ownership:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## 4. Build on prod

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## 5. Migrate (REQUIRED this release — doctypes + patches + fields)

Migrate **every** stabler tenant, not just anjan — the doctypes/patches are
shared app code and each site needs its own DDL sync:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for S in $(ls sites | grep "\."); do
  bench --site "$S" list-apps 2>/dev/null | grep -q "^stabler" || continue
  echo "== migrating $S =="
  bench --site "$S" migrate
done'
```

Watch each run: v50/v51 are under `[post_model_sync]` so they run **after** the
new columns exist — no "unknown column" abort. Spot-check one secondary site
(not just anjan):

```bash
ssh ice-production "cd /home/frappe/frappe-bench && bench --site dts.erpstable.com mariadb -e \"SELECT name FROM tabDocType WHERE name IN ('Proforma Invoice','HS Duty Rate');\""
```

## 6. Restart (REQUIRED — .py changed)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

> This restarts the whole bench → a brief blip for **all** tenants, not just
> anjan. Do it in a low-traffic window.

## 7. Post-deploy smoke (run on at least anjan + one secondary)

1. **Enable the module** for a real company that does imports (if not already):
   `enable_imports` lives on the `Stabler Company Modules` child row, not
   `tabCompany`. Toggle via the SPA company settings, or `bench console`:
   ```python
   from stabler.stabler.doctype.stabler_settings.stabler_settings import get_company_module_row
   r = get_company_module_row("<Company>"); r.enable_imports = 1
   r.save(ignore_permissions=True); frappe.db.commit()
   ```
2. **Record-form direct load** (CLAUDE.md regression class): paste an existing
   Commercial Invoice URL and hit refresh —
   `…/stabler#/imports/commercial-invoices/<existing CI>` — it must open
   populated, NOT a blank "New" form. Repeat for a Sales Invoice / Purchase
   Order / Payment Entry.
3. **Proforma page loads**: `…/stabler#/imports/proformas` lists and opens the
   create modal.
4. **Vendor Center exposure**: a supplier with import CIs shows the Import
   Exposure panel (cash/bank bars) + Open commitments table.
5. **Convert dry-run**: click Convert to Invoice on an open CI → preview modal
   appears and **writes nothing** (re-open the CI, still open). Only Confirm
   creates a DRAFT PInv.
6. **GL log flowing** (unchanged core path): record one payment on anjan and
   confirm a line lands in
   `sites/anjan.erpstable.com/logs/stabler.payments.log`.
7. **Tenant isolation**: on a site WITHOUT imports enabled, the Vendor Center
   shows no import exposure and `/imports/*` routes are blocked — confirms the
   gate.

## 8. Rollback (if a smoke check fails)

```bash
# restore the step-2 tar, re-own, rebuild, restart
ssh ice-production 'cd /home/frappe/frappe-bench/apps && tar xzf /root/stabler-app-<TIMESTAMP>.tgz && chown -R frappe:frappe stabler && cd /home/frappe/frappe-bench && bench build --app stabler && bench restart'
```

The new doctype **tables** stay after a code rollback (harmless — nothing writes
to them once the code is gone). The v50/v51 patches are idempotent, so a
re-deploy re-runs cleanly. Only a draft Purchase Invoice could have been created
by a convert smoke — delete it if unwanted.

---

### Notes
- **HS Duty Rate is empty on first deploy** — the pre-declaration estimate
  returns "unrated" until you seed the table with real TN VED rates (ask me for
  a seed script when ready). Nothing else depends on it being populated.
- **i18n**: all imports strings ship translated in en/ru/uz/uzc/tr.
- **KTS amendment + FX revaluation + advance aging** are **preview/report
  endpoints** — they never post to GL. Nothing in this release auto-submits a
  document.
