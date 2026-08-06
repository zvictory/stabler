"""Fix all HMA Commercial Invoices and corresponding Purchase Invoices / GL Entries to match Google Sheet master reference."""

import json
import os

import frappe
from frappe.utils import flt


def run(dry_run=1):
	dry_run = int(dry_run)
	module_path = os.path.join(os.path.dirname(__file__), "data", "msa_ci_rows.json")
	with open(module_path, encoding="utf-8") as f:
		ref_rows = json.load(f)

	hma_ref_by_cin = {
		r.get("ci_number"): r
		for r in ref_rows
		if r.get("ci_number")
		and ("HMA" in (r.get("vendor") or "").upper() or "MH/" in (r.get("ci_number") or ""))
	}

	cis = frappe.get_all(
		"Commercial Invoice",
		filters={"supplier": ["like", "%HMA%"]},
		fields=["name", "ci_number", "supplier", "agreed_total", "docs_total", "cash_difference"],
	)

	ci_updates = []
	for ci in cis:
		cin = ci.ci_number or ci.name
		ref = hma_ref_by_cin.get(cin)
		if not ref:
			continue

		ag_ref = float(ref.get("agreed_total") or 0)
		dc_ref = float(ref.get("docs_total") or 0)
		cd_ref = float(ref.get("cash_difference") or 0)

		ag_db = float(ci.agreed_total or 0)
		dc_db = float(ci.docs_total or 0)

		if abs(ag_db - ag_ref) > 0.01 or abs(dc_db - dc_ref) > 0.01:
			ci_updates.append(
				{
					"name": ci.name,
					"ci_number": cin,
					"old_agreed": ag_db,
					"new_agreed": ag_ref,
					"old_docs": dc_db,
					"new_docs": dc_ref,
					"old_diff": float(ci.cash_difference or 0),
					"new_diff": cd_ref,
				}
			)

			if not dry_run:
				# 1. Update Commercial Invoice Header
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

				# 2. Update Commercial Invoice Item rows if present
				items = frappe.get_all(
					"Commercial Invoice Item",
					filters={"parent": ci.name},
					fields=["name", "qty", "rate", "amount", "docs_price", "docs_amount"],
				)
				if items:
					total_qty = sum(flt(it.get("qty")) for it in items)
					for it in items:
						qty = flt(it.get("qty"))
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

				# 3. Update linked Purchase Invoice and GL Entries if present
				pinvs = frappe.get_all(
					"Purchase Invoice",
					filters={"supplier": ["like", "%HMA%"], "docstatus": 1},
					fields=["name", "grand_total"],
				)
				# Check if any Purchase Invoice matches the old agreed_total or old docs_total
				for pinv in pinvs:
					p_tot = flt(pinv.grand_total)
					if abs(p_tot - ag_db) <= 0.5 or abs(p_tot - dc_db) <= 0.5:
						p_items = frappe.get_all(
							"Purchase Invoice Item", filters={"parent": pinv.name}, fields=["name", "qty"]
						)
						p_total_qty = sum(flt(pi_it.qty) for pi_it in p_items)
						for pi_it in p_items:
							p_qty = flt(pi_it.qty)
							if p_total_qty > 0 and p_qty > 0:
								p_prop = p_qty / p_total_qty
								p_amt = round(ag_ref * p_prop, 2)
								p_rate = round(p_amt / p_qty, 4)
								frappe.db.set_value(
									"Purchase Invoice Item",
									pi_it.name,
									{
										"rate": p_rate,
										"amount": p_amt,
										"base_rate": p_rate,
										"base_amount": p_amt,
										"net_rate": p_rate,
										"net_amount": p_amt,
									},
									update_modified=False,
								)

						frappe.db.set_value(
							"Purchase Invoice",
							pinv.name,
							{
								"total": ag_ref,
								"base_total": ag_ref,
								"net_total": ag_ref,
								"base_net_total": ag_ref,
								"grand_total": ag_ref,
								"base_grand_total": ag_ref,
								"rounded_total": ag_ref,
								"base_rounded_total": ag_ref,
								"outstanding_amount": ag_ref,
							},
							update_modified=False,
						)

						# Update GL Entries for this Purchase Invoice
						gl_entries = frappe.get_all(
							"GL Entry",
							filters={"voucher_type": "Purchase Invoice", "voucher_no": pinv.name},
							fields=["name", "credit", "debit"],
						)
						for gle in gl_entries:
							is_credit = flt(gle.credit) > 0
							frappe.db.set_value(
								"GL Entry",
								gle.name,
								{
									"credit" if is_credit else "debit": ag_ref,
									"credit_in_account_currency"
									if is_credit
									else "debit_in_account_currency": ag_ref,
									"debit" if is_credit else "credit": 0.0,
									"debit_in_account_currency"
									if is_credit
									else "credit_in_account_currency": 0.0,
								},
								update_modified=False,
							)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print("\n========================================================")
	print(f"  FIX HMA COMMERCIAL INVOICES & GL ENTRIES ({mode})")
	print("========================================================")
	print(f"Total HMA CIs updated: {len(ci_updates)}")
	for u in ci_updates:
		print(
			f"CI: {u['name']:15} ({u['ci_number']:18}) | Agreed: ${u['old_agreed']:12,.2f} -> ${u['new_agreed']:12,.2f} "
			f"| Docs: ${u['old_docs']:10,.2f} -> ${u['new_docs']:10,.2f} | CashDiff: ${u['old_diff']:10,.2f} -> ${u['new_diff']:10,.2f}"
		)

	return ci_updates
