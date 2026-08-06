"""Audit and report all Proforma Invoices on msa.erpstable.com vs the Google Sheet master reference."""

import json

import frappe

from .pi_ref_backfill import PI_ROWS


def run():
	pis = frappe.get_all(
		"Proforma Invoice",
		fields=["name", "supplier", "supplier_pi_ref", "pi_date", "agreed_total", "docs_total", "status"],
	)

	ref_by_ref = {r["ref"]: r for r in PI_ROWS}
	ref_by_tot = {float(r["agreed_total"]): r for r in PI_ROWS}

	report = {
		"total_db": len(pis),
		"total_ref": len(PI_ROWS),
		"with_orig_ref": 0,
		"missing_orig_ref": [],
		"rows": [],
	}

	for pi in pis:
		orig_ref = pi.supplier_pi_ref or ""
		matched_ref = ref_by_ref.get(orig_ref) or ref_by_tot.get(float(pi.agreed_total or 0))

		info = {
			"name": pi.name,
			"supplier": pi.supplier,
			"orig_ref": orig_ref,
			"pi_date": str(pi.pi_date or ""),
			"agreed_total": float(pi.agreed_total or 0),
			"docs_total": float(pi.docs_total or 0),
			"status": pi.status,
			"matched_ref": matched_ref["ref"] if matched_ref else None,
		}
		report["rows"].append(info)

		if orig_ref:
			report["with_orig_ref"] += 1
		else:
			report["missing_orig_ref"].append(info)

	print("\n========================================================")
	print("  MSA PROFORMA INVOICES (PI) AUDIT REPORT")
	print("========================================================")
	print(f"Total PIs in DB: {report['total_db']} | Total in Google Sheet: {report['total_ref']}")
	print(f"PIs carrying original supplier_pi_ref: {report['with_orig_ref']}")
	print(f"PIs missing original supplier_pi_ref: {len(report['missing_orig_ref'])}\n")

	for row in report["rows"]:
		ref_str = (
			row["orig_ref"] if row["orig_ref"] else f"❌ MISSING (Suggest: {row['matched_ref'] or 'Unknown'})"
		)
		print(
			f"PI: {row['name']:15} | Supplier: {(row['supplier'] or ''):35} | Orig Ref: {ref_str:30} | Agreed: ${row['agreed_total']:12,.2f}"
		)

	return report
