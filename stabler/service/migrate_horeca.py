"""
HoReCa → ERPNext historical data migration.

Reads the JSON export produced by scripts/export-for-erp.ts and creates
ERPNext records for historical horeca data:

  Phase 1 — Equipment  →  Serial No  (keyed by custom_horeca_id)
  Phase 2 — Tickets    →  Issue      (keyed by custom_horeca_id)
  Phase 3 — Reports    →  Stock Entry + Maintenance Visit
                          (Stock Entry keyed by custom_horeca_id on Maintenance Visit)

All phases are idempotent: records that already have a matching custom_horeca_id
are skipped. Safe to re-run after partial failures.

Usage (from bench root):

  # Preview — prints plan, writes nothing:
  bench execute stabler.service.migrate_horeca.run \\
    --kwargs '{"json_path": "/tmp/horeca-export.json", "dry_run": true}'

  # Execute — creates records, writes results:
  bench execute stabler.service.migrate_horeca.run \\
    --kwargs '{"json_path": "/tmp/horeca-export.json", "dry_run": false, "results_path": "/tmp/horeca-results.json"}'

  # Override company (auto-detected from site if omitted):
  bench --site horeca.erpstable.com execute stabler.service.migrate_horeca.run \\
    --kwargs '{"json_path": "/tmp/horeca-export.json", "dry_run": True, "company": "HorecaGroup"}'

After execution, run the write-back to mark reports as synced in Prisma:
  tsx scripts/export-for-erp.ts --mark-synced /tmp/horeca-results.json
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import flt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(dry_run: bool, msg: str) -> None:
	prefix = "[DRY RUN] " if dry_run else ""
	print(f"{prefix}{msg}")


def _horeca_exists(doctype: str, horeca_id: str) -> str | None:
	"""Return the ERPNext doc name if a record with custom_horeca_id exists."""
	return frappe.db.get_value(doctype, {"custom_horeca_id": horeca_id}, "name")


def _auto_detect_company() -> str:
	companies = frappe.db.get_all("Company", pluck="name", limit=1)
	if not companies:
		frappe.throw("No Company found in ERPNext. Pass company= explicitly.")
	return companies[0]


# ---------------------------------------------------------------------------
# Phase 1: Equipment → Serial No
# ---------------------------------------------------------------------------

def _migrate_equipment(equip: dict[str, Any], company: str, dry_run: bool) -> str | None:
	"""Create a Serial No for one horeca Equipment record. Returns ERPNext name."""
	existing = _horeca_exists("Serial No", equip["id"])
	if existing:
		_log(dry_run, f"  [skip] Serial No exists: {existing}")
		return existing

	_log(dry_run, f"  [create] Serial No: {equip['serialNo']} — {equip['name']} @ {equip['customerName']}")
	if dry_run:
		return None

	doc = frappe.new_doc("Serial No")
	doc.serial_no = equip["serialNo"]
	doc.item_name = equip["name"]
	# item_code is required but horeca Equipment tracks product name, not ERP item code.
	# Use serialNo as a placeholder; the operator can link a proper Item afterward.
	doc.item_code = equip["serialNo"]
	doc.company = company
	doc.custom_horeca_id = equip["id"]
	doc.custom_placement = "Loaned"
	if equip.get("installedAt"):
		doc.purchase_date = equip["installedAt"]
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
# Phase 2: Tickets → Issues
# ---------------------------------------------------------------------------

_PRIORITY_MAP = {
	"LOW": "Low",
	"MEDIUM": "Medium",
	"HIGH": "High",
	"URGENT": "Urgent",
}

_STATUS_MAP = {
	"NEW": "Open",
	"ASSIGNED": "Open",
	"ACCEPTED": "Open",
	"EN_ROUTE": "Open",
	"IN_PROGRESS": "Open",
	"ON_HOLD": "On Hold",
	"RESOLVED": "Resolved",
	"CLOSED": "Closed",
	"CANCELLED": "Closed",
}


def _migrate_ticket(ticket: dict[str, Any], dry_run: bool) -> str | None:
	"""Create an ERPNext Issue for one horeca Ticket. Returns ERPNext name."""
	existing = _horeca_exists("Issue", ticket["id"])
	if existing:
		_log(dry_run, f"  [skip] Issue exists: {existing}")
		return existing

	status = _STATUS_MAP.get(ticket["status"], "Open")
	_log(dry_run, f"  [create] Issue: {ticket['code']} — {ticket['customerName']} ({ticket['type']}) → {status}")
	if dry_run:
		return None

	doc = frappe.new_doc("Issue")
	doc.subject = f"[{ticket['code']}] {ticket['type']} — {ticket['customerName']}"
	doc.customer = ticket["customerName"]
	doc.status = status
	doc.priority = _PRIORITY_MAP.get(ticket.get("priority", "MEDIUM"), "Medium")
	doc.description = ticket.get("description") or ""
	doc.opening_date = ticket["createdAt"][:10]
	doc.custom_horeca_id = ticket["id"]
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
# Phase 3: Reports → Stock Entry + Maintenance Visit
# ---------------------------------------------------------------------------

def _migrate_stock_entry(report: dict[str, Any], company: str, dry_run: bool) -> str | None:
	"""
	Create and submit a Material Issue Stock Entry for parts used in a service report.

	Two-phase create-then-submit to match the same pattern used in the live API
	(apps/api/src/routes/reports.ts). A crash between the two phases leaves a
	recoverable Draft (docstatus=0); re-running finds it via custom_horeca_id
	on the linked Maintenance Visit and re-submits.
	"""
	# If the report already carried a stock entry name from a partial sync, use it.
	if report.get("erpnextStockEntry"):
		_log(dry_run, f"  [skip] Stock Entry exists: {report['erpnextStockEntry']}")
		return report["erpnextStockEntry"]

	if not report.get("parts"):
		_log(dry_run, f"  [skip] No parts for {report['ticketCode']} — no Stock Entry needed")
		return None

	_log(
		dry_run,
		f"  [create] Stock Entry: {len(report['parts'])} part(s) for {report['ticketCode']} "
		f"on {report['postingDate']}",
	)
	for p in report["parts"]:
		_log(dry_run, f"           {p['itemCode']} × {p['qty']}  from  {p['warehouse']}")
	if dry_run:
		return None

	doc = frappe.new_doc("Stock Entry")
	doc.stock_entry_type = "Material Issue"
	doc.purpose = "Material Issue"
	doc.company = company
	doc.posting_date = report["postingDate"]
	doc.posting_time = report["postingTime"]
	doc.remarks = f"Service report {report['id']} for ticket {report['ticketCode']}"

	for p in report["parts"]:
		doc.append(
			"items",
			{
				"item_code": p["itemCode"],
				"qty": flt(p["qty"]),
				"s_warehouse": p["warehouse"],
			},
		)

	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	doc.submit()
	frappe.db.commit()
	return doc.name


def _migrate_maintenance_visit(
	report: dict[str, Any],
	issue_name: str | None,
	stock_entry_name: str | None,
	company: str,
	dry_run: bool,
) -> str | None:
	"""Create a Maintenance Visit linking the Issue and Stock Entry."""
	existing = _horeca_exists("Maintenance Visit", report["id"])
	if existing:
		_log(dry_run, f"  [skip] Maintenance Visit exists: {existing}")
		# If the existing MV doesn't have stock_entry yet (orphan recovery), patch it.
		if stock_entry_name and not dry_run:
			current_se = frappe.db.get_value("Maintenance Visit", existing, "custom_stock_entry")
			if not current_se:
				frappe.db.set_value("Maintenance Visit", existing, "custom_stock_entry", stock_entry_name)
				frappe.db.commit()
				_log(dry_run, f"  [patch] Linked Stock Entry {stock_entry_name} to existing MV {existing}")
		return existing

	_log(
		dry_run,
		f"  [create] Maintenance Visit: {report['ticketCode']} @ {report['postingDate']} "
		f"[issue={issue_name}, se={stock_entry_name}]",
	)
	if dry_run:
		return None

	doc = frappe.new_doc("Maintenance Visit")
	doc.company = company
	doc.customer = report["customerName"]
	doc.maintenance_date = report["postingDate"]
	doc.maintenance_time = report["postingTime"]
	doc.purpose = "Repair"
	doc.status = "Closed"
	doc.custom_horeca_id = report["id"]

	if issue_name:
		doc.custom_issue = issue_name
	if stock_entry_name:
		doc.custom_stock_entry = stock_entry_name

	# purposes child table: one row per report; item_code is optional in ignore_mandatory mode.
	doc.append(
		"purposes",
		{
			"work_done": report["workDescription"],
			"description": report.get("resolutionCategory") or report.get("causeCode") or "",
		},
	)

	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
	json_path: str,
	dry_run: bool = True,
	results_path: str | None = None,
	company: str | None = None,
) -> None:
	"""
	Main migration entry point. Called via:
	  bench execute stabler.service.migrate_horeca.run --kwargs '{...}'
	"""
	with open(json_path) as f:
		data: dict[str, Any] = json.load(f)

	if not company:
		company = _auto_detect_company()

	equipment_list: list[dict] = data.get("equipment", [])
	ticket_list: list[dict] = data.get("tickets", [])
	report_list: list[dict] = data.get("reports", [])

	_log(dry_run, f"=== HoReCa Migration  company={company}  dry_run={dry_run} ===")
	_log(dry_run, f"    exported_at: {data.get('exported_at', 'unknown')}")
	_log(dry_run, f"    equipment: {len(equipment_list)}, tickets: {len(ticket_list)}, reports: {len(report_list)}")

	# --- Phase 1: Equipment --------------------------------------------------
	_log(dry_run, "\n--- Phase 1: Equipment → Serial No ---")
	serial_created = 0
	serial_skipped = 0
	serial_errors = 0

	for equip in equipment_list:
		try:
			name = _migrate_equipment(equip, company, dry_run)
			if name and not name.startswith("["):
				serial_created += 1
			else:
				serial_skipped += 1
		except Exception as exc:
			_log(dry_run, f"  [error] equipment {equip.get('id', '?')[:8]}: {exc}")
			serial_errors += 1

	# --- Phase 2: Tickets ----------------------------------------------------
	_log(dry_run, "\n--- Phase 2: Tickets → Issues ---")
	issue_map: dict[str, str] = {}
	issue_created = 0
	issue_skipped = 0
	issue_errors = 0

	for ticket in ticket_list:
		try:
			name = _migrate_ticket(ticket, dry_run)
			if name:
				issue_map[ticket["id"]] = name
				if "[skip]" in str(name):
					issue_skipped += 1
				else:
					issue_created += 1
		except Exception as exc:
			_log(dry_run, f"  [error] ticket {ticket.get('code', '?')}: {exc}")
			issue_errors += 1

	# --- Phase 3: Reports ----------------------------------------------------
	_log(dry_run, "\n--- Phase 3: Reports → Stock Entry + Maintenance Visit ---")
	results: list[dict[str, Any]] = []
	report_ok = 0
	report_errors = 0

	for report in report_list:
		try:
			stock_entry = _migrate_stock_entry(report, company, dry_run)
			issue = issue_map.get(report["ticketId"])
			mv = _migrate_maintenance_visit(report, issue, stock_entry, company, dry_run)

			results.append(
				{
					"reportId": report["id"],
					"erpnextStockEntry": stock_entry,
					"erpnextMaintenanceVisit": mv,
					"status": "ok",
				}
			)
			report_ok += 1
		except Exception as exc:
			_log(dry_run, f"  [error] report {report.get('id', '?')[:8]} ({report.get('ticketCode', '?')}): {exc}")
			results.append(
				{
					"reportId": report.get("id", ""),
					"status": "error",
					"error": str(exc),
				}
			)
			report_errors += 1

	# --- Summary -------------------------------------------------------------
	_log(dry_run, "\n=== Summary ===")
	_log(dry_run, f"  Equipment: {serial_created} created, {serial_skipped} skipped, {serial_errors} errors")
	_log(dry_run, f"  Tickets:   {issue_created} created, {issue_skipped} skipped, {issue_errors} errors")
	_log(dry_run, f"  Reports:   {report_ok} ok, {report_errors} errors")

	if results_path and not dry_run:
		with open(results_path, "w") as f:
			json.dump(results, f, indent=2)
		print(f"\nResults written to: {results_path}")
		print("Next step: tsx scripts/export-for-erp.ts --mark-synced " + results_path)
