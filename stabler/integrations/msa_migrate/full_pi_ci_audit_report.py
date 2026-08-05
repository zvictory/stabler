"""Full audit and verification report for all PIs and CIs on msa.erpstable.com vs Google Sheet master references."""

import json
import frappe
from .pi_ref_backfill import PI_ROWS
from .ci_backfill import _load_rows as load_ci_rows

def run():
	ci_ref_rows = load_ci_rows()
	pi_ref_rows = PI_ROWS

	# 1. Audit Proforma Invoices
	db_pis = frappe.get_all(
		"Proforma Invoice",
		fields=["name", "supplier", "supplier_pi_ref", "pi_date", "agreed_total", "docs_total", "status"]
	)

	ref_pi_by_tot = {round(float(r["agreed_total"]), 2): r for r in pi_ref_rows}
	ref_pi_by_ref = {r["ref"]: r for r in pi_ref_rows}

	pi_report = []
	for pi in sorted(db_pis, key=lambda x: x.name):
		tot = round(float(pi.agreed_total or 0), 2)
		orig = pi.supplier_pi_ref or ""
		ref = ref_pi_by_ref.get(orig) or ref_pi_by_tot.get(tot)
		expected_ref = ref["ref"] if ref else "N/A"
		is_match = bool(orig and orig == expected_ref)

		pi_report.append({
			"name": pi.name,
			"supplier": pi.supplier,
			"orig_ref": orig,
			"expected_ref": expected_ref,
			"pi_date": str(pi.pi_date or ""),
			"agreed_total": tot,
			"status": pi.status,
			"is_ok": is_match,
		})

	# 2. Audit Commercial Invoices
	db_cis = frappe.get_all(
		"Commercial Invoice",
		fields=["name", "ci_number", "supplier", "ci_date", "agreed_total", "docs_total", "cash_difference", "status"]
	)

	ref_ci_by_cin = {r.get("ci_number"): r for r in ci_ref_rows if r.get("ci_number")}

	ci_report = []
	for ci in sorted(db_cis, key=lambda x: x.ci_number or x.name):
		cin = ci.ci_number or ci.name
		ref = ref_ci_by_cin.get(cin)

		ag_db = float(ci.agreed_total or 0)
		dc_db = float(ci.docs_total or 0)

		if not ref:
			ci_report.append({
				"name": ci.name,
				"ci_number": cin,
				"supplier": ci.supplier,
				"ci_date": str(ci.ci_date or ""),
				"ag_db": ag_db,
				"ag_ref": 0,
				"dc_db": dc_db,
				"dc_ref": 0,
				"status": ci.status,
				"is_ok": False,
				"reason": "NOT_IN_LEGACY_SHEET"
			})
			continue

		ag_ref = float(ref.get("agreed_total") or 0)
		dc_ref = float(ref.get("docs_total") or 0)

		is_ok = (abs(ag_db - ag_ref) <= 0.01 and abs(dc_db - dc_ref) <= 0.01 and cin and not cin.startswith("CI-2026-"))

		ci_report.append({
			"name": ci.name,
			"ci_number": cin,
			"supplier": ci.supplier,
			"ci_date": str(ci.ci_date or ""),
			"ag_db": ag_db,
			"ag_ref": ag_ref,
			"dc_db": dc_db,
			"dc_ref": dc_ref,
			"status": ci.status,
			"is_ok": is_ok,
			"reason": "OK" if is_ok else "DISCREPANCY"
		})

	print("\n=========================================================================")
	print("  FULL PI & CI ORIGINAL REFERENCE AUDIT REPORT (msa.erpstable.com)")
	print("=========================================================================")
	print(f"Total Proforma Invoices (PI): {len(pi_report)}")
	print(f"PIs with 100% Valid Original Reference: {len([p for p in pi_report if p['is_ok']])}")
	print(f"PIs with Missing/Invalid Reference: {len([p for p in pi_report if not p['is_ok']])}\n")

	print(f"Total Commercial Invoices (CI): {len(ci_report)}")
	print(f"Legacy Sheet CIs Matched 100%: {len([c for c in ci_report if c['reason'] == 'OK'])}")
	print(f"Newer / Post-Migration CIs: {len([c for c in ci_report if c['reason'] == 'NOT_IN_LEGACY_SHEET'])}\n")

	return {"pis": pi_report, "cis": ci_report}
