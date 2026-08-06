import json
import os

import frappe


def run():
	module_path = os.path.join(os.path.dirname(__file__), "data", "msa_ci_rows.json")
	with open(module_path, encoding="utf-8") as f:
		ref_rows = json.load(f)

	ref_by_cin = {r.get("ci_number"): r for r in ref_rows if r.get("ci_number")}
	cis = frappe.get_all(
		"Commercial Invoice",
		fields=["name", "ci_number", "supplier", "agreed_total", "docs_total", "cash_difference"],
	)

	discrepancies = []
	for ci in cis:
		cin = ci.ci_number or ci.name
		ref = ref_by_cin.get(cin)
		if not ref:
			continue

		ag_db = float(ci.agreed_total or 0)
		dc_db = float(ci.docs_total or 0)

		ag_ref = float(ref.get("agreed_total") or 0)
		dc_ref = float(ref.get("docs_total") or 0)

		if abs(ag_db - ag_ref) > 0.01 or abs(dc_db - dc_ref) > 0.01:
			discrepancies.append(
				{
					"name": ci.name,
					"ci_number": cin,
					"supplier": ci.supplier,
					"ag_db": ag_db,
					"ag_ref": ag_ref,
					"ag_diff": ag_db - ag_ref,
					"dc_db": dc_db,
					"dc_ref": dc_ref,
					"dc_diff": dc_db - dc_ref,
				}
			)

	print(f"Total CIs in database: {len(cis)}")
	print(f"Discrepancies found vs Google Sheet reference: {len(discrepancies)}\n")
	for d in discrepancies:
		print(
			f"CI: {d['name']:15} | Ref CI: {d['ci_number']:20} | Supplier: {d['supplier']:40} "
			f"| DB Agreed: ${d['ag_db']:12,.2f} | Ref Agreed: ${d['ag_ref']:12,.2f} | Diff: ${d['ag_diff']:12,.2f}"
		)
	return discrepancies
