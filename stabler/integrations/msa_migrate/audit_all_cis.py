"""Audit and report all Commercial Invoices on msa.erpstable.com vs the Google Sheet master reference (msa_ci_rows.json)."""

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
		fields=[
			"name",
			"ci_number",
			"supplier",
			"ci_date",
			"agreed_total",
			"docs_total",
			"cash_difference",
			"total_boxes",
			"total_kg",
			"status",
		],
	)

	report = {
		"total_in_db": len(cis),
		"total_in_ref": len(ref_rows),
		"iff_cis": [],
		"other_discrepancies": [],
		"matched_count": 0,
	}

	for ci in sorted(cis, key=lambda x: x.ci_number or x.name):
		cin = ci.ci_number or ci.name
		ref = ref_by_cin.get(cin)

		ag_db = float(ci.agreed_total or 0)
		dc_db = float(ci.docs_total or 0)
		cd_db = float(ci.cash_difference or 0)

		if not ref:
			report["other_discrepancies"].append(
				{
					"name": ci.name,
					"ci_number": cin,
					"supplier": ci.supplier,
					"issue": "NOT_IN_GOOGLE_SHEET_REF",
					"ag_db": ag_db,
					"ag_ref": 0,
					"ag_diff": ag_db,
					"dc_db": dc_db,
					"dc_ref": 0,
					"dc_diff": dc_db,
				}
			)
			continue

		ag_ref = float(ref.get("agreed_total") or 0)
		dc_ref = float(ref.get("docs_total") or 0)
		cd_ref = float(ref.get("cash_difference") or 0)

		is_iff = "IFF" in (ci.supplier or "").upper() or "IFF" in cin.upper()
		has_discrepancy = abs(ag_db - ag_ref) > 0.01 or abs(dc_db - dc_ref) > 0.01

		item_info = {
			"name": ci.name,
			"ci_number": cin,
			"supplier": ci.supplier,
			"ci_date": str(ci.ci_date or ""),
			"ag_db": ag_db,
			"ag_ref": ag_ref,
			"ag_diff": ag_db - ag_ref,
			"dc_db": dc_db,
			"dc_ref": dc_ref,
			"dc_diff": dc_db - dc_ref,
			"cd_db": cd_db,
			"cd_ref": cd_ref,
			"status": ci.status,
		}

		if is_iff:
			report["iff_cis"].append(item_info)
		elif has_discrepancy:
			report["other_discrepancies"].append(item_info)
		else:
			report["matched_count"] += 1

	print("\n========================================================")
	print("  MSA COMMERCIAL INVOICES VS GOOGLE SHEET AUDIT REPORT")
	print("========================================================")
	print(f"Total CIs in DB: {report['total_in_db']} | Total in Google Sheet: {report['total_in_ref']}")
	print(f"Perfectly Matched CIs: {report['matched_count']}")
	print(f"IFF Vendor CIs: {len(report['iff_cis'])}")
	print(f"Other Discrepancies: {len(report['other_discrepancies'])}\n")

	print("--- IFF VENDOR COMMERCIAL INVOICES AUDIT ---")
	for i in report["iff_cis"]:
		status = "⚠️ DISCREPANCY" if (abs(i["ag_diff"]) > 0.01 or abs(i["dc_diff"]) > 0.01) else "✅ OK"
		print(
			f"{status} | CI: {i['name']:15} ({i['ci_number']:18}) | Date: {i['ci_date']} "
			f"| DB Agreed: ${i['ag_db']:12,.2f} | Ref Agreed: ${i['ag_ref']:12,.2f} | Diff: ${i['ag_diff']:12,.2f} "
			f"| DB Docs: ${i['dc_db']:10,.2f} | Ref Docs: ${i['dc_ref']:10,.2f}"
		)

	if report["other_discrepancies"]:
		print(f"\n--- OTHER VENDORS DISCREPANCIES AUDIT ({len(report['other_discrepancies'])}) ---")
		for o in report["other_discrepancies"][:30]:
			print(
				f"⚠️ DISCREPANCY | CI: {o['name']:15} ({o.get('ci_number'):18}) | Supplier: {o.get('supplier')!s:30} "
				f"| DB Agreed: ${o.get('ag_db', 0):12,.2f} | Ref Agreed: ${o.get('ag_ref', 0):12,.2f} | Diff: ${o.get('ag_diff', 0):12,.2f}"
			)
		if len(report["other_discrepancies"]) > 30:
			print(f"  ... and {len(report['other_discrepancies']) - 30} more.")

	return report
