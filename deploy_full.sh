#!/usr/bin/env bash
# FULL DEPLOY — deploys the ENTIRE stabler working tree to prod (anjan.erpstable.com).
# Run from your Mac (has bench-local + the `ice-production` SSH alias).
# rsync copies the whole app, so EVERY local change ships — not just a git-add list.
set -euo pipefail

BENCH=/Users/zafar/frappe-bench-local          # local bench root
APP="$BENCH/apps/stabler"
REMOTE=ice-production                            # SSH alias (lands as root)
REMOTE_BENCH=/home/frappe/frappe-bench
REMOTE_APP="$REMOTE_BENCH/apps/stabler"
SITE=anjan.erpstable.com                         # PRIMARY site of the 7 stabler sites.
                                                 # Used for the pre-flight check and the
                                                 # post-deploy probe only -- step 5
                                                 # migrates EVERY stabler-bearing site.

echo "==> 0) Prove it compiles locally (bench build from bench root)"
( cd "$BENCH" && bench build --app stabler )

echo "==> 1) Confirm the target actually has stabler (never assume the site)"
# SSH lands as root; Frappe's bench refuses to run as root, so use sudo -u frappe.
ssh "$REMOTE" "cd $REMOTE_BENCH && sudo -u frappe bench --site $SITE list-apps | grep -q stabler" \
  || { echo 'ABORT: stabler not on '"$SITE"; exit 1; }

echo "==> 2) Backup prod first (rollback path)"
ssh "$REMOTE" 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C '"$REMOTE_BENCH"'/apps stabler'

echo "==> 3) rsync WHOLE working tree -> prod (NO --delete; excludes junk + docs)"
# The exclude list lives ENTIRELY in .rsync-exclude -- no inline flags here.
# This script and deploy_stabler.sh used to keep their own and shipped different
# file sets; consolidated 2026-07-26 after diffing both lists.
rsync -rltz --no-owner --no-group \
  --exclude-from="$APP/.rsync-exclude" \
  "$APP/" "$REMOTE:$REMOTE_APP/"
ssh "$REMOTE" "chown -R frappe:frappe $REMOTE_APP"

echo "==> 4) Build on prod (rsync excludes dist/, so prod MUST rebuild) + strip sourcemaps"
# Prod has developer_mode off -> esbuild already minifies. It still writes a
# .js.map beside the bundle, and sites/assets is public: measured 2026-07-26,
# the 3.5M bundle came with a 14.5M map any visitor could download, i.e. the
# full unminified Vue source. Delete it; only devtools ever requests it.
ssh "$REMOTE" "cd $REMOTE_BENCH && sudo -u frappe bench build --app stabler \
  && find sites/assets/stabler/dist -name '*.map' -print -delete"

echo "==> 5) Migrate EVERY stabler-bearing site (migrate is PER-SITE; idempotent)"
# rsync + restart are bench-wide, so all 7 sites already have the new code -- but
# only the sites you migrate get the DDL. Sites are DISCOVERED, never hardcoded:
# a hardcoded list goes stale the moment a tenant is added or renamed.
# (2026-07-18 near-miss: msa was skipped and its new Import PI Group columns were
#  missing until a follow-up migrate.)
ssh "$REMOTE" 'cd '"$REMOTE_BENCH"' && for s in $(ls sites); do
  [ -f "sites/$s/site_config.json" ] || continue
  sudo -u frappe bench --site "$s" list-apps 2>/dev/null | grep -qw stabler || continue
  echo "   --- migrate $s"
  sudo -u frappe bench --site "$s" migrate
done'

echo "==> 6) Restart (.py changed). NOTE: restarts the whole bench -> brief blip for ALL tenants"
ssh "$REMOTE" "cd $REMOTE_BENCH && sudo -u frappe bench restart"

echo "==> 7) Post-deploy checks"
ssh "$REMOTE" "cd $REMOTE_BENCH && sudo -u frappe bench --site $SITE execute frappe.client.get_count --args '[\"Role\", {\"name\": \"Stabler Declarant\"}]'" \
  && echo '   ^ 1 = tender roles created by migrate'

cat <<'DONE'

==> DONE. Now in the browser (HARD refresh: Cmd+Shift+R):
   - Assign roles: Users -> give Stabler Declarant / Stabler Logist / Sales User /
     Stabler Tender Director to the right people (else their tender windows are empty).
   - Tender -> PO control: deadline chips, landed plan (ТНВЭД + customs auto-calc),
     vendor comparison (landed), bid pricing P&L, plan vs actual.
   - Role windows: /tender/director (win-rate + assign), /tender/customs, /tender/logistics.
   - Badges render OK on: Employees, BPM, Promo Plans, Claims, Payroll.
   - Atomicity: record + cancel one payment / remittance / installment -> works normally.

Rollback = restore the step-2 tar, chown frappe:frappe, bench build --app stabler, bench restart.
DONE
