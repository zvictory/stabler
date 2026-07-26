#!/usr/bin/env bash
# Stabler production deploy — run on YOUR Mac (has bench + the `ice-production`
# SSH alias). Follows apps/stabler/CLAUDE.md exactly.
#
# Prod = the shared bench. anjan.erpstable.com is the PRIMARY site, not the only
# one: stabler is installed on 7 sites. rsync + bench restart are bench-wide and
# hit all of them at once; `migrate` is per-site, so step 5 discovers every
# stabler-bearing site and migrates each. (2026-07-18 near-miss: msa was skipped
# and its new Import PI Group columns were missing until a follow-up migrate.)
#
# All bench calls go through `sudo -u frappe`: SSH lands as root and Frappe's
# bench CLI refuses to run as root (exits 1 with only a WARN), which under
# `set -e` would abort this script at step 0. See docs/runbooks/
# install-stabler-on-msa.md and the same pattern in deploy_full.sh.
#
# This deploy includes the whole accumulated session: dimensional pricing (commit
# 57b8ab1) + service map/outlet-GPS/dashboard/equipment + xlsx export backend
# (commit 065f675). v23 patch adds custom fields → migrate IS required. Many .py
# changed → bench restart IS required (brief blip for ALL ~22 tenants).
#
# Safe by design: stops on any error, backs up first, NO --delete, asks before
# the bench restart. Review it, then: bash deploy_stabler.sh

set -euo pipefail

LOCAL_BENCH="/Users/zafar/frappe-bench-local"
APP_DIR="$LOCAL_BENCH/apps/stabler"
PROD="ice-production"
PROD_APPS="/home/frappe/frappe-bench/apps"
SITE="anjan.erpstable.com"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
confirm() { read -r -p "$1 [y/N] " a; [[ "$a" == "y" || "$a" == "Y" ]]; }

# 0) Confirm prod target actually has stabler (never assume the site).
say "0/7  Confirming $SITE has stabler installed"
ssh "$PROD" "cd /home/frappe/frappe-bench && sudo -u frappe bench --site $SITE list-apps | grep -qw stabler" \
  && echo "    OK: stabler is installed on $SITE" \
  || { echo "    ABORT: stabler not found on $SITE"; exit 1; }

# 1) Prove it compiles locally (esbuild bundle).
say "1/7  Local build (bench build --app stabler)"
( cd "$LOCAL_BENCH" && bench build --app stabler )

# 2) Backup prod app dir first (rollback point).
say "2/7  Backup current prod app -> /root/stabler-app-<ts>.tgz"
ssh "$PROD" "tar czf /root/stabler-app-\$(date +%F-%H%M).tgz -C $PROD_APPS stabler && ls -lh /root/stabler-app-*.tgz | tail -1"

# 3) rsync working tree -> prod (NO --delete). The exclude list lives ENTIRELY
#    in .rsync-exclude -- no inline flags here. This script and deploy_full.sh
#    used to keep their own, disagreed on anchoring, and silently shipped
#    different file sets (this one leaked .github/, every top-level *.md
#    including DEPLOY-SECURITY.md, and all three deploy_*.sh to prod).
say "3/7  rsync source -> $PROD:$PROD_APPS/stabler/"
rsync -rltz --no-owner --no-group \
  --exclude-from="$APP_DIR/.rsync-exclude" \
  "$APP_DIR/" "$PROD:$PROD_APPS/stabler/"
ssh "$PROD" "chown -R frappe:frappe $PROD_APPS/stabler"

# 4) Build on prod, then drop the sourcemaps.
#    Prod has developer_mode off, so `bench build` already runs esbuild in
#    production mode (minified). It still emits a .js.map next to the bundle,
#    and sites/assets is served publicly -- measured 2026-07-26: the 3.5M
#    bundle shipped a 14.5M map, fetchable over plain HTTPS, i.e. the full
#    unminified Vue source of a 7-tenant ERP. Nothing in prod reads it; only a
#    devtools session would, and that 404 is harmless.
say "4/7  bench build --app stabler (on prod) + strip sourcemaps"
ssh "$PROD" "cd /home/frappe/frappe-bench && sudo -u frappe bench build --app stabler \
  && find sites/assets/stabler/dist -name '*.map' -print -delete"

# 5) Migrate — REQUIRED whenever patches.txt / doctypes changed, and it is
#    PER-SITE. rsync + restart are bench-wide, so every stabler site already got
#    the code; only the sites you migrate get the DDL. Sites are DISCOVERED, not
#    hardcoded — a hardcoded list goes stale the moment a tenant is added.
say "5/7  migrate EVERY stabler-bearing site (per-site DDL)"
ssh "$PROD" 'cd /home/frappe/frappe-bench && for s in $(ls sites); do
  [ -f "sites/$s/site_config.json" ] || continue
  sudo -u frappe bench --site "$s" list-apps 2>/dev/null | grep -qw stabler || continue
  echo "    --- migrate $s"
  sudo -u frappe bench --site "$s" migrate
done'

# 6) Restart — REQUIRED (.py changed). NOTE: restarts the whole bench -> brief
#    blip for ALL tenants, not just anjan. Run at low traffic.
say "6/7  bench restart  (brief blip for ALL ~22 tenants)"
if confirm "Proceed with bench restart now?"; then
  ssh "$PROD" "cd /home/frappe/frappe-bench && sudo -u frappe bench restart"
else
  echo "    Skipped. Run later:  ssh $PROD 'cd /home/frappe/frappe-bench && sudo -u frappe bench restart'"
fi

# 7) Post-deploy smoke checks (manual — see below).
say "7/7  Done. Now run the smoke checks:"
cat <<'SMOKE'
    - Direct-URL/refresh load of an existing record (NOT a blank New form):
        .../stabler#/purchasing/invoices/<existing PINV>   (refresh)
        repeat for one Sales Invoice, Purchase Order, Quotation, Payment Entry.
    - New feature spot-checks:
        #/service/map         pins render (outlets need gps_lat/lng)
        #/sfa/locations       list + map + paste/CSV import
        #/service/dashboard   KPI cards populate
        #/service/equipment   Serial No fleet + coverage badges
        Sales Order: pick a dimensional item -> Boy/En/Adet -> qty computes (m2);
                     ice-cream line stays Qty | Korobka/adet (unchanged).
        Any report -> "Excel — professional" downloads a styled .xlsx.
    - Money/GL log flowing: after one payment, a line lands in
        sites/anjan.erpstable.com/logs/stabler.payments.log
    Rollback if needed: restore the step-2 tar, chown, bench build, bench restart.
SMOKE
