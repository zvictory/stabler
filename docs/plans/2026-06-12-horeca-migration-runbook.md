# HoReCa Migration Runbook — P2

**Prod site:** `horeca.erpstable.com` (SSH alias `ice-production`)
**DO NOT RUN**: this is a manual process you run yourself.

---

## 0. Pre-flight — verify target before export

Run these checks first. If any fail, stop and investigate.

```bash
ssh ice-production
# Confirm the site has the horeca company
bench --site horeca.erpstable.com execute frappe.client.get \
  --kwargs '{"doctype":"Company","name":"HorecaGroup"}' 2>&1 | grep -q '"name": "HorecaGroup"' \
  && echo "OK: company found" || echo "FAIL: company not found — wrong site?"

# Confirm the four custom columns exist
bench --site horeca.erpstable.com mariadb --execute \
  "SELECT COUNT(*) FROM \`tabCustom Field\`
   WHERE fieldname IN ('custom_horeca_id','custom_interval_days');" 2>&1
# Expected: 4 (two horeca_id + one interval_days + one day_of_month at minimum)
```

Stop if the company is not "HorecaGroup" or if `tabCustom Field` count is 0.

---

## 1. Export from HoReCa Node API

On the horeca server (or locally if `.env` points to prod DB):

```bash
cd ~/Documents/horeca
npx tsx scripts/export-for-erp.ts --output /tmp/horeca-export-$(date +%F).json
```

Produces a JSON file with keys `exported_at`, `equipment`, `tickets`, `reports`.
Verify counts printed to stdout (equipment / approved-unsynced-reports).

---

## 2. Copy export to prod server

```bash
EXPORT=/tmp/horeca-export-$(date +%F).json
scp $EXPORT ice-production:/tmp/horeca-export.json
```

---

## 3. Dry run

```bash
ssh ice-production
bench --site horeca.erpstable.com execute stabler.service.migrate_horeca.run \
  --kwargs '{"json_path": "/tmp/horeca-export.json", "dry_run": true, "company": "HorecaGroup"}'
```

Review output line-by-line:
- `[create]` lines show what would be created
- `[skip]` lines show existing records (safe to ignore)
- `[error]` lines must be investigated before proceeding

Expected dry-run summary format:
```
  Equipment: N created, M skipped, 0 errors
  Tickets:   N created, M skipped, 0 errors
  Reports:   N created, M skipped, 0 errors
```

**Zero errors required before proceeding.**

---

## 4. Execute

```bash
bench --site horeca.erpstable.com execute stabler.service.migrate_horeca.run \
  --kwargs '{
    "json_path": "/tmp/horeca-export.json",
    "dry_run": false,
    "company": "HorecaGroup",
    "results_path": "/tmp/horeca-results.json"
  }'
```

`results_path` is written only on `dry_run=false`. It maps each report's `horeca_id`
to the ERPNext document names created (Maintenance Visit, Stock Entry).

---

## 5. Mark synced in HoReCa Prisma DB

Back on the horeca machine:

```bash
scp ice-production:/tmp/horeca-results.json /tmp/horeca-results.json
cd ~/Documents/horeca
npx tsx scripts/export-for-erp.ts --mark-synced /tmp/horeca-results.json
```

Sets `syncedToErpnext = true` and `erpnextStockEntry` on each report row.
Subsequent exports will exclude these — re-run safety confirmed.

---

## 6. Verification queries

Run on prod after execution:

```sql
-- Serial No count by horeca source
SELECT COUNT(*) FROM `tabSerial No` WHERE custom_horeca_id IS NOT NULL AND custom_horeca_id != '';

-- Issue count
SELECT COUNT(*) FROM `tabIssue` WHERE custom_horeca_id IS NOT NULL AND custom_horeca_id != '';

-- Maintenance Visit count
SELECT COUNT(*) FROM `tabMaintenance Visit` WHERE custom_horeca_id IS NOT NULL AND custom_horeca_id != '';

-- Unsynced reports remaining (should be 0 or near-0 after mark-synced)
-- Run in horeca DB:
-- SELECT COUNT(*) FROM "ServiceReport" WHERE approved = true AND "syncedToErpnext" = false;

-- Verify no orphaned MV (has horeca_id but no linked issue)
SELECT name, custom_horeca_id, custom_issue
FROM `tabMaintenance Visit`
WHERE custom_horeca_id IS NOT NULL
  AND (custom_issue IS NULL OR custom_issue = '')
LIMIT 10;
```

Expected: orphan query returns 0 rows.

---

## 7. Idempotency guarantee

The migration is safe to re-run at any time:
- `_horeca_exists(doctype, horeca_id)` looks up `custom_horeca_id` before creating any record
- `[skip]` is logged for every already-existing record; no duplicates are possible
- `dry_run=true` is always safe (reads only, no writes, no commits)

---

## 8. Kill switch 1

After P3 is deployed and you've confirmed service tickets flow in natively:

**Disable the Node approval-sync** in `apps/api/src/routes/reports.ts` — the webhook
that was pushing approved tickets to ERPNext is no longer needed once Stabler handles it.
