#!/usr/bin/env bash
# CI line-item repair — ship the inputs to prod and run the dry run.
#
# Run from the stabler app root on the laptop:
#     bash docs/data/run_ci_repair.sh              # dry run (writes nothing)
#     bash docs/data/run_ci_repair.sh apply        # applies, after you read the dry run
#     bash docs/data/run_ci_repair.sh apply MH/104/202526   # single invoice first
#
# Nothing here restarts the bench or touches other tenants: the maintenance
# module is imported by `bench execute`, so no build and no restart is needed.
set -euo pipefail

HOST="ice-production"
SITE="msa.erpstable.com"
REMOTE_BENCH="/home/frappe/frappe-bench"
REMOTE_APP="${REMOTE_BENCH}/apps/stabler/stabler/maintenance"
REMOTE_DATA="/home/frappe"

MODE="${1:-dry}"
ONLY="${2:-}"

CSV_LOCAL="docs/data/msa_ci_lines.csv"
PY_LOCAL="stabler/maintenance/repair_ci_items_from_sheet.py"
ALIAS_LOCAL="docs/data/msa_item_alias.csv"   # optional; created after the first dry run

for f in "$CSV_LOCAL" "$PY_LOCAL"; do
	[ -f "$f" ] || { echo "missing: $f (run from the stabler app root)"; exit 1; }
done

echo "==> target site: ${SITE} on ${HOST}"
ssh "$HOST" "cd ${REMOTE_BENCH} && bench --site ${SITE} list-apps | grep -q stabler" \
	|| { echo "ABORT: stabler is not installed on ${SITE}"; exit 1; }

echo "==> shipping inputs"
scp "$CSV_LOCAL" "${HOST}:${REMOTE_DATA}/msa_ci_lines.csv"
scp "$PY_LOCAL"  "${HOST}:${REMOTE_APP}/repair_ci_items_from_sheet.py"
ssh "$HOST" "chown frappe:frappe ${REMOTE_APP}/repair_ci_items_from_sheet.py ${REMOTE_DATA}/msa_ci_lines.csv"

# Scope: the five import vendors this repair is about. 351 of the book's 387
# invoices are wholly theirs, and none of the 387 mixes an included vendor with
# an excluded one, so nothing is cut in half. Everything else — the Belarus /
# Ukraine meat trucks and the Слуцкий dairy (СОМ / СЦМ / Сыворотка) — is left
# completely untouched.
ONLY_SUPPLIERS="HMA,Mirha,Al Super,IFF,FAIR"

KW="{\"csv_path\":\"${REMOTE_DATA}/msa_ci_lines.csv\",\"company\":\"MSA\",\"only_suppliers\":\"${ONLY_SUPPLIERS}\""
if [ -f "$ALIAS_LOCAL" ]; then
	scp "$ALIAS_LOCAL" "${HOST}:${REMOTE_DATA}/msa_item_alias.csv"
	ssh "$HOST" "chown frappe:frappe ${REMOTE_DATA}/msa_item_alias.csv"
	KW="${KW},\"alias_path\":\"${REMOTE_DATA}/msa_item_alias.csv\""
	echo "==> using alias map ${ALIAS_LOCAL}"
fi
[ -n "$ONLY" ] && KW="${KW},\"invoices\":[\"${ONLY}\"]"
if [ "$MODE" = "apply" ]; then
	KW="${KW},\"dry_run\":0}"
	echo "==> APPLYING — every touched invoice is backed up to JSON first"
else
	KW="${KW},\"dry_run\":1}"
	echo "==> DRY RUN — nothing will be written"
fi

ssh "$HOST" "cd ${REMOTE_BENCH} && bench --site ${SITE} execute \
	stabler.maintenance.repair_ci_items_from_sheet.run --kwargs '${KW}'"

echo
echo "verify (same scope):"
echo "  ssh ${HOST} \"cd ${REMOTE_BENCH} && bench --site ${SITE} execute \\"
echo "    stabler.maintenance.repair_ci_items_from_sheet.verify \\"
echo "    --kwargs '{\\\"csv_path\\\":\\\"${REMOTE_DATA}/msa_ci_lines.csv\\\",\\\"company\\\":\\\"MSA\\\",\\\"only_suppliers\\\":\\\"${ONLY_SUPPLIERS}\\\"}'\""
echo
echo "reports live in ${REMOTE_BENCH}/sites/${SITE}/private/files/"
echo "  ci_repair_report_*.json      per-invoice before/after"
echo "  ci_repair_unresolved_*.csv   fill item_code -> save as ${ALIAS_LOCAL} -> re-run"
echo "  ci_items_backup_*.json       restore with repair_ci_items_from_sheet.restore"
