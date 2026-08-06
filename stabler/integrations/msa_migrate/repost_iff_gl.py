"""Re-post Purchase Invoices and GL Entries for IFF to reflect corrected Agreed Totals."""

import frappe
from frappe.utils import flt

PI_CI_MAP = {
	"ACC-PINV-2026-00264": {"ci_number": "IFF/EXP/26/0685", "target_agreed": 361200.0},
	"ACC-PINV-2026-00269": {"ci_number": "IFF/EXP/26/0616", "target_agreed": 347200.0},
	"ACC-PINV-2026-00272": {"ci_number": "IFF/EXP/26/0595", "target_agreed": 340200.0},
	"ACC-PINV-2026-00275": {"ci_number": "IFF/EXP/26/0576", "target_agreed": 347200.0},
	"ACC-PINV-2026-00280": {"ci_number": "IFF/EXP/26/0553", "target_agreed": 340200.0},
	"ACC-PINV-2026-00281": {"ci_number": "IFF/EXP/26/0554", "target_agreed": 354200.0},
	"ACC-PINV-2026-00283": {"ci_number": "IFF/EXP/26/0539", "target_agreed": 340200.0},
}


def run(dry_run=1):
	dry_run = int(dry_run)
	report = []

	for pinv_name, info in PI_CI_MAP.items():
		target = info["target_agreed"]
		ci_num = info["ci_number"]

		if not frappe.db.exists("Purchase Invoice", pinv_name):
			report.append((pinv_name, ci_num, "NOT FOUND", 0, target))
			continue

		doc = frappe.get_doc("Purchase Invoice", pinv_name)
		old_total = flt(doc.grand_total)

		# Calculate item level scaling factor
		items = doc.items or []
		total_qty = sum(flt(it.qty) for it in items)

		report_row = {
			"pinv": pinv_name,
			"ci_num": ci_num,
			"old_total": old_total,
			"new_total": target,
			"delta": target - old_total,
		}

		if not dry_run:
			# 1. Update Purchase Invoice Item rates and amounts
			for it in items:
				qty = flt(it.qty)
				if total_qty > 0 and qty > 0:
					prop = qty / total_qty
					new_amt = round(target * prop, 2)
					new_rate = round(new_amt / qty, 4)
					frappe.db.set_value(
						"Purchase Invoice Item",
						it.name,
						{
							"rate": new_rate,
							"amount": new_amt,
							"base_rate": new_rate,
							"base_amount": new_amt,
							"net_rate": new_rate,
							"net_amount": new_amt,
							"base_net_rate": new_rate,
							"base_net_amount": new_amt,
						},
						update_modified=False,
					)

			# 2. Update Purchase Invoice Header Totals
			frappe.db.set_value(
				"Purchase Invoice",
				pinv_name,
				{
					"total": target,
					"base_total": target,
					"net_total": target,
					"base_net_total": target,
					"grand_total": target,
					"base_grand_total": target,
					"rounded_total": target,
					"base_rounded_total": target,
					"outstanding_amount": target,
				},
				update_modified=False,
			)

			# 3. Update GL Entries for this Purchase Invoice
			gl_entries = frappe.get_all(
				"GL Entry",
				filters={"voucher_type": "Purchase Invoice", "voucher_no": pinv_name},
				fields=["name", "account", "party", "debit", "credit"],
			)
			for gle in gl_entries:
				is_credit = flt(gle.credit) > 0
				new_val = target
				frappe.db.set_value(
					"GL Entry",
					gle.name,
					{
						"credit" if is_credit else "debit": new_val,
						"credit_in_account_currency" if is_credit else "debit_in_account_currency": new_val,
						"debit" if is_credit else "credit": 0.0,
						"debit_in_account_currency" if is_credit else "credit_in_account_currency": 0.0,
					},
					update_modified=False,
				)

		report.append(report_row)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print("\n========================================================")
	print(f"  RE-POST IFF PURCHASE INVOICES & GL ENTRIES ({mode})")
	print("========================================================")
	total_old = sum(r["old_total"] for r in report)
	total_new = sum(r["new_total"] for r in report)
	print(f"Total Old GL Creditors: ${total_old:,.2f}")
	print(f"Total New GL Creditors: ${total_new:,.2f}")
	print(f"Net GL Adjustment:     +${total_new - total_old:,.2f}\n")

	for r in report:
		print(
			f"PInv: {r['pinv']:20} | CI: {r['ci_num']:18} | Old Total: ${r['old_total']:12,.2f} "
			f"-> New Total: ${r['new_total']:12,.2f} | GL Delta: +${r['delta']:10,.2f}"
		)

	return report
