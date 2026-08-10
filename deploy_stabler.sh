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
# install-stabler-on-msa.md.
#
# THE canonical deploy script. deploy_full.sh described the same 7 steps in its
# own words until 2026-07-27; two descriptions of one pipeline drift apart, which
# is exactly how the rsync exclude lists ended up disagreeing (see .rsync-exclude).
# Its one unique part -- the post-migrate get_count probe -- lives in step 7 here.
#
# Migrate is unconditional below because it is cheap and idempotent; the restart
# is the expensive one and it ASKS first. Rule of thumb: patches.txt or a doctype
# changed -> migrate matters; any .py changed -> restart matters.
#
# Safe by design: ships HEAD rather than the working tree (step 3), stops on any
# error, backs up first, dry-runs the rsync, NO --delete, asks before the bench
# restart. Review it, then: bash deploy_stabler.sh

set -euo pipefail

LOCAL_BENCH="/Users/zafar/frappe-bench-local"
APP_DIR="$LOCAL_BENCH/apps/stabler"
PROD="ice-production"
PROD_APPS="/home/frappe/frappe-bench/apps"
SITE="anjan.erpstable.com"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
confirm() { read -r -p "$1 [y/N] " a; [[ "$a" == "y" || "$a" == "Y" ]]; }

# 0) Branch gate — BEFORE anything touches prod, including the step below's ssh
#    and step 2's backup tarball. Step 3 ships `git archive HEAD`, and HEAD is
#    whatever is checked out: run this from a feature branch and half-finished
#    work lands on ALL 7 tenants at once. rsync has no --delete, so a file that
#    reaches prod that way stays there forever. Until 2026-08-10 nothing in this
#    script mentioned a branch at all.
#
#    Two separate failures, so two separate checks: the wrong branch, and the
#    right branch that nobody pushed (prod would then run commits that exist on
#    no remote -- unreviewable and unrecoverable if this laptop dies).
#
#    ALLOW_BRANCH_DEPLOY=1 is a deliberate escape hatch for a hotfix branch. It
#    prints the branch name rather than going quiet: shipping off-main should be
#    a thing you read out loud, not a thing you get away with.
say "0/7  Branch gate"
BRANCH="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  if [ "${ALLOW_BRANCH_DEPLOY:-0}" = "1" ]; then
    echo "    WARNING: deploying from branch '$BRANCH', NOT main (ALLOW_BRANCH_DEPLOY=1)."
    echo "             Every stabler tenant gets this code. There is no --delete to undo it."
  else
    echo "    ABORT: on branch '$BRANCH', not main. Merge to main first,"
    echo "           or set ALLOW_BRANCH_DEPLOY=1 to ship this branch deliberately."
    exit 1
  fi
else
  git -C "$APP_DIR" fetch origin main --quiet
  AHEAD="$(git -C "$APP_DIR" rev-list --count origin/main..main)"
  BEHIND="$(git -C "$APP_DIR" rev-list --count main..origin/main)"
  if [ "$AHEAD" != "0" ] || [ "$BEHIND" != "0" ]; then
    echo "    ABORT: main is $AHEAD ahead / $BEHIND behind origin/main."
    echo "           Push or pull first -- prod must never run commits no remote has."
    exit 1
  fi
  echo "    OK: on main, in sync with origin/main"
fi

# 0) Confirm prod target actually has stabler (never assume the site).
say "0/7  Confirming $SITE has stabler installed"
ssh "$PROD" "cd /home/frappe/frappe-bench && sudo -u frappe bench --site $SITE list-apps | grep -qw stabler" \
  && echo "    OK: stabler is installed on $SITE" \
  || { echo "    ABORT: stabler not found on $SITE"; exit 1; }

# 1) Prove it compiles locally (esbuild bundle). NOTE: bench builds the app in
#    place, i.e. the WORKING TREE -- so on a dirty tree this proves the working
#    copy compiles, not HEAD. It is a fast local canary, not the gate; step 4
#    rebuilds the exported HEAD on prod and that build is the authoritative one.
say "1/7  Local build (bench build --app stabler)"
( cd "$LOCAL_BENCH" && bench build --app stabler )

# 2) Backup prod app dir first (rollback point).
#    Echo back the archive this run just wrote, by name -- not `ls *.tgz | tail -1`,
#    which sorts alphabetically and so reported the stale
#    stabler-app-tender-b2-full-2026-06-26 instead of today's file (seen 2026-08-01).
#    A backup step that prints someone else's backup is worse than printing nothing:
#    it names a rollback point that does not contain what you just replaced.
say "2/7  Backup current prod app -> /root/stabler-app-<ts>.tgz"
ssh "$PROD" "TS=\$(date +%F-%H%M) && tar czf /root/stabler-app-\$TS.tgz -C $PROD_APPS stabler && ls -lh /root/stabler-app-\$TS.tgz"

# 3) rsync the COMMITTED tree -> prod (NO --delete). The exclude list lives ENTIRELY
#    in .rsync-exclude -- no inline flags here. This script and deploy_full.sh
#    used to keep their own, disagreed on anchoring, and silently shipped
#    different file sets (this one leaked .github/, every top-level *.md
#    including DEPLOY-SECURITY.md, and all three deploy_*.sh to prod).
#
#    The SOURCE is `git archive HEAD`, not the working tree. It used to be the
#    working tree, which meant "what is committed" and "what is running on prod"
#    were two different things that nobody reconciled. Measured 2026-07-31 on
#    design/modernist-operations-desk: a working-tree deploy would have pushed 19
#    half-finished edits to live code (api/sales.py, router.js, MoneyInput.vue,
#    all five translation CSVs mid-harvest) plus 36 files that exist in no commit
#    at all (_to_delete/ git-lock debris, an entire uncommitted msa_migrate/
#    script set, TransporterCenter.vue) onto all 7 tenants at once. None of it was
#    visible in the dry run's file list as *uncommitted* -- rsync only reports
#    paths, and a half-done file looks exactly like a finished one.
#
#    Exporting from HEAD makes the deployed set equal to the reviewed set by
#    construction, so a dirty tree can no longer leak. It also means: commit
#    first, or your change does not ship.
say "3/7  Exporting HEAD ($(git -C "$APP_DIR" rev-parse --short HEAD)) to a clean staging dir"
EXPORT_DIR="$(mktemp -d)"
trap 'rm -rf "$EXPORT_DIR"' EXIT
git -C "$APP_DIR" archive HEAD | tar -x -C "$EXPORT_DIR"

#    Say out loud what is being withheld. Silence here would read as "the tree is
#    clean" when it is merely being ignored -- the same failure mode as the -v
#    flag below.
WITHHELD="$(git -C "$APP_DIR" status --porcelain | wc -l | tr -d ' ')"
if [ "$WITHHELD" != "0" ]; then
  echo "    NOTE: $WITHHELD working-tree entries are dirty/untracked and will NOT ship."
  echo "          Anything you need on prod must be committed first."
fi

#    Source sanity first. CLAUDE.md's cwd trap: run from inside apps/stabler/ and
#    a relative `stabler/` resolves to the INNER python package, which rsync then
#    ships as if it were the whole app. $EXPORT_DIR is absolute so it cannot
#    happen here, but the assertion is one line and it is what makes that
#    guarantee checkable rather than assumed. hooks.py only exists at the app
#    root -- so this also catches an archive that came out empty or truncated.
[ -f "$EXPORT_DIR/stabler/hooks.py" ] \
  || { echo "    ABORT: HEAD export is not a stabler app root"; exit 1; }

#    Dry run BEFORE the real one. -v is not optional: `rsync -n` without it
#    prints nothing, so an empty dry run reads as "clean" while having verified
#    nothing (that cost us a bogus 2026-07-24 verification).
say "3/7  rsync DRY RUN -> $PROD:$PROD_APPS/stabler/"
DRY="$(rsync -rltzvn --no-owner --no-group \
  --exclude-from="$APP_DIR/.rsync-exclude" \
  "$EXPORT_DIR/" "$PROD:$PROD_APPS/stabler/")"
echo "$DRY"
if echo "$DRY" | grep -qE '^(deleting |stable-erp-website/|professional-excel-export/|recon/)'; then
  echo "    ABORT: dry run deletes files or touches a sibling project."
  exit 1
fi
confirm "Ship exactly the file list above?" || { echo "    Aborted."; exit 1; }

say "3/7  rsync source -> $PROD:$PROD_APPS/stabler/"
rsync -rltz --no-owner --no-group \
  --exclude-from="$APP_DIR/.rsync-exclude" \
  "$EXPORT_DIR/" "$PROD:$PROD_APPS/stabler/"
ssh "$PROD" "chown -R frappe:frappe $PROD_APPS/stabler"

# 4) Node deps, then build on prod, then drop the sourcemaps.
#
#    node_modules is excluded from the rsync (correctly -- it is build output),
#    which means NO deploy step ever creates or refreshes it, while `bench build`
#    silently depends on it: esbuild resolves @vue-flow/* out of
#    apps/stabler/node_modules. Measured 2026-08-07: the directory was simply
#    gone and the build died on ProcessEditor.vue's @vue-flow/controls import.
#    A new runtime dependency in package.json is the same bomb with a fuse --
#    prod would still be carrying the previous install.
#
#    So install when the tree is missing or when the manifests we just shipped no
#    longer match the ones it was built from. The stamp is the manifests' own
#    checksum because prod is not a git repo and has nothing else to compare
#    against; package.json is hashed alongside the lock, since a dependency can
#    land in it while package-lock.json stays stale (stabler-qee).
#
#    --ignore-scripts is a requirement, not tidiness: package.json's preinstall
#    is `npx only-allow npm`, which would fetch a package off the network in the
#    middle of a deploy. --omit=dev keeps eslint/prettier/vitest off prod; only
#    the runtime deps are what esbuild resolves. `npm ci` is the right command
#    here and is not usable yet -- package-lock.json is out of sync with
#    package.json (stabler-qee) -- so switch to it when that lands.
say "4/7  node deps on prod (only if missing or the manifests changed)"
ssh "$PROD" "set -e
  cd $PROD_APPS/stabler
  STAMP=node_modules/.stabler-deps-md5
  WANT=\$(cat package.json package-lock.json | md5sum | cut -d' ' -f1)
  if [ ! -d node_modules ] || [ \"\$(cat \$STAMP 2>/dev/null)\" != \"\$WANT\" ]; then
    echo '    node_modules missing or built from other manifests -> npm install'
    sudo -H -u frappe npm install --omit=dev --no-save --ignore-scripts --no-audit --no-fund
    echo \"\$WANT\" | sudo -H -u frappe tee \$STAMP >/dev/null
  else
    echo '    node_modules matches the shipped manifests -- nothing to install'
  fi"

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

# 7) Automated probe, then the manual smoke checks.
#    The probe is the one piece deploy_full.sh had and this script did not: a
#    round trip that only succeeds if the new code imports AND the site's DB
#    answers. It counts rows in a doctype stabler itself owns, so a failed
#    migrate or a broken import surfaces here instead of under the first user.
say "7/7  Post-deploy probe (stabler code + DB reachable on $SITE)"
ssh "$PROD" "cd /home/frappe/frappe-bench && sudo -u frappe bench --site $SITE \
  execute frappe.client.get_count --args '[\"Stabler Company Modules\", {}]'" \
  && echo "    ^ >=1 means stabler's own doctypes are live on $SITE"

say "Done. Now run the smoke checks:"
cat <<'SMOKE'
    - Direct-URL/refresh load of an existing record (NOT a blank New form):
        .../stabler#/purchasing/invoices/<existing PINV>   (refresh)
        repeat for one Sales Invoice, Purchase Order, Quotation, Payment Entry.
    - Money/GL log flowing: after one payment, a line lands in
        sites/anjan.erpstable.com/logs/stabler.payments.log
    - Release-specific checks live in that release's plan doc, not here: this
      script is repeatable, so a hardcoded feature list goes stale by the next
      deploy (it used to carry the 2026-07 service-map/dimensional-pricing list).
    - Then:  make prod-drift    # files running on prod that are not in git
    Rollback if needed: restore the step-2 tar, chown, bench build, bench restart.
SMOKE
