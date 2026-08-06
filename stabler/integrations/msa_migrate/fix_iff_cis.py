"""Fix IFF Commercial Invoices on msa.erpstable.com to match Google Sheet master reference."""

import json
import os

import frappe


def run(dry_run=1):
	dry_run = int(dry_run)
	module_path = os.path.join(os.path.dirname(__file__), "data", "msa_ci_rows.json")
	with open(module_path, encoding="utf-8") as f:
		ref_rows = json.load(f)

	ref_by_cin = {r.get("ci_number"): r for r in ref_rows if r.get("ci_number")}

	cis = frappe.get_all(
		"Commercial Invoice",
		filters={"supplier": ["like", "%IFF%"]},
		fields=["name", "ci_number", "supplier", "agreed_total", "docs_total", "cash_difference"],
	)

	updates = []
	for ci in cis:
		cin = ci.ci_number or ci.name
		ref = ref_by_cin.get(cin)
		if not ref:
			continue

		ag_ref = float(ref.get("agreed_total") or 0)
		dc_ref = float(ref.get("docs_total") or 0)
		cd_ref = float(ref.get("cash_difference") or 0)

		updates.append(
			{
				"name": ci.name,
				"ci_number": cin,
				"old_agreed": float(ci.agreed_total or 0),
				"new_agreed": ag_ref,
				"old_docs": float(ci.docs_total or 0),
				"new_docs": dc_ref,
				"old_diff": float(ci.cash_difference or 0),
				"new_diff": cd_ref,
			}
		)

		if not dry_run:
			frappe.db.set_value(
				"Commercial Invoice",
				ci.name,
				{
					"agreed_total": ag_ref,
					"docs_total": dc_ref,
					"cash_difference": cd_ref,
				},
				update_modified=False,
			)

			items = frappe.get_all(
				"Commercial Invoice Item",
				filters={"parent": ci.name},
				fields=["name", "qty", "rate", "amount", "docs_price", "docs_amount"],
			)
			if items:
				total_qty = sum(float(it.get("qty") or 0) for it in items)
				for it in items:
					qty = float(it.get("qty") or 0)
					if total_qty > 0 and qty > 0:
						prop = qty / total_qty
						it_ag_amt = round(ag_ref * prop, 2)
						it_ag_rate = round(it_ag_amt / qty, 4)
						it_dc_amt = round(dc_ref * prop, 2)
						it_dc_rate = round(it_dc_amt / qty, 4)
						frappe.db.set_value(
							"Commercial Invoice Item",
							it["name"],
							{
								"rate": it_ag_rate,
								"amount": it_ag_amt,
								"docs_price": it_dc_rate,
								"docs_amount": it_dc_amt,
							},
							update_modified=False,
						)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print(f"\n=== FIX IFF COMMERCIAL INVOICES ({mode}) ===")
	for u in updates:
		print(
			f"CI: {u['name']:15} ({u['ci_number']:18}) | Agreed: ${u['old_agreed']:12,.2f} -> ${u['new_agreed']:12,.2f} "
			f"| Docs: ${u['old_docs']:10,.2f} -> ${u['new_docs']:10,.2f} | CashDiff: ${u['old_diff']:10,.2f} -> ${u['new_diff']:10,.2f}"
		)
	return updates
