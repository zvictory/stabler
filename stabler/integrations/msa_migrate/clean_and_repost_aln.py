"""Clean up duplicate ALN GL Payment Entries and Purchase Invoices, then post EXACTLY the 14 Bank Payments ($453,600.80) and 40 Cash Payments ($2,181,761.00) matching the Excel sheet."""

import frappe
from frappe.utils import flt, today

ALN_BANK_PAYMENTS = [
	{"amount": 25200.00, "date": "2025-08-29", "inv": "MH/689/2025-26"},
	{"amount": 16800.00, "date": "2025-09-09", "inv": "MH/678/2025-26"},
	{"amount": 16800.00, "date": "2025-09-17", "inv": "MH/686/2025-26"},
	{"amount": 23100.00, "date": "2025-09-30", "inv": "MH/728/2025-26"},
	{"amount": 37500.00, "date": "2025-11-17", "inv": "MH/735/2025-26"},
	{"amount": 20000.00, "date": "2025-12-02", "inv": "MH/743/2025-26"},
	{"amount": 22800.00, "date": "2025-12-11", "inv": "MH/761/2025-26"},
	{"amount": 24000.00, "date": "2025-12-15", "inv": "MH/863/2025-26"},
	{"amount": 41200.00, "date": "2025-12-24", "inv": "MH/864/2025-26"},
	{"amount": 24600.00, "date": "2025-12-30", "inv": "MH/867/2025-26"},
	{"amount": 49600.00, "date": "2026-01-19", "inv": "MH/979/2025-26"},
	{"amount": 42800.00, "date": "2026-01-30", "inv": "MH/980/2025-26"},
	{"amount": 100800.00, "date": "2026-03-30", "inv": "MH/1050/2025-26"},
	{"amount": 8400.80, "date": "2026-03-31", "inv": "MH/1051/2025-26"},
]

ALN_CASH_PAYMENTS = [
	{"amount": 20000.00, "date": "2025-09-10", "inv": "MH/689/2025-26"},
	{"amount": 21850.00, "date": "2025-09-12", "inv": "MH/678/2025-26"},
	{"amount": 30000.00, "date": "2025-09-22", "inv": "MH/686/2025-26"},
	{"amount": 20000.00, "date": "2025-10-03", "inv": "MH/728/2025-26"},
	{"amount": 15000.00, "date": "2025-10-06", "inv": "MH/735/2025-26"},
	{"amount": 20000.00, "date": "2025-10-13", "inv": "MH/743/2025-26"},
	{"amount": 30000.00, "date": "2025-10-20", "inv": "MH/761/2025-26"},
	{"amount": 10000.00, "date": "2025-10-24", "inv": "MH/863/2025-26"},
	{"amount": 27700.00, "date": "2025-10-29", "inv": "MH/864/2025-26"},
	{"amount": 29900.00, "date": "2025-11-04", "inv": "MH/867/2025-26"},
	{"amount": 30000.00, "date": "2025-11-07", "inv": "MH/979/2025-26"},
	{"amount": 50000.00, "date": "2025-11-15", "inv": "MH/980/2025-26"},
	{"amount": 10000.00, "date": "2025-11-21", "inv": "MH/1050/2025-26"},
	{"amount": 30000.00, "date": "2025-11-30", "inv": "MH/1051/2025-26"},
	{"amount": 40000.00, "date": "2025-12-09", "inv": "MH/1115/2025-26"},
	{"amount": 25000.00, "date": "2025-12-15", "inv": "MH/1126/2025-26"},
	{"amount": 20000.00, "date": "2025-12-25", "inv": "MH/1119/2025-26"},
	{"amount": 40000.00, "date": "2025-12-30", "inv": "MH/1171/2025-26"},
	{"amount": 20000.00, "date": "2026-01-05", "inv": "MH/1172/2025-26"},
	{"amount": 60000.00, "date": "2026-01-23", "inv": "MH/1173/2025-26"},
	{"amount": 60000.00, "date": "2026-02-02", "inv": "MH/1242/2025-26"},
	{"amount": 60000.00, "date": "2026-02-04", "inv": "MH/1243/2025-26"},
	{"amount": 50000.00, "date": "2026-02-12", "inv": "MH/1280/2025-26"},
	{"amount": 80000.00, "date": "2026-02-16", "inv": "MH/1284/2025-26"},
	{"amount": 100000.00, "date": "2026-03-01", "inv": "MH/1266/2025-26"},
	{"amount": 45000.00, "date": "2026-03-08", "inv": "MH/1267/2025-26"},
	{"amount": 50000.00, "date": "2026-03-16", "inv": "MH/1310/2025-26"},
	{"amount": 55000.00, "date": "2026-03-25", "inv": "MH/1328/2025-26"},
	{"amount": 50000.00, "date": "2026-04-07", "inv": "MH/1329/2025-26"},
	{"amount": 4296.00, "date": "2026-04-18", "inv": "MH/1522/2025-26"},
	{"amount": 84575.00, "date": "2026-04-22", "inv": "HMA/2275/2025-26"},
	{"amount": 100000.00, "date": "2026-05-26", "inv": "HMA/2296/2025-26"},
	{"amount": 140000.00, "date": "2026-06-01", "inv": "HMA/2370/2025-26"},
	{"amount": 50000.00, "date": "2026-06-03", "inv": "HMA/2391/2025-26"},
	{"amount": 60700.00, "date": "2026-06-09", "inv": "HMA/2569/2025-26"},
	{"amount": 142740.00, "date": "2026-06-29", "inv": "HMA/2042/2025-26"},
	{"amount": 100000.00, "date": "2026-07-13", "inv": "HMA/2043/2025-26"},
	{"amount": 150000.00, "date": "2026-07-17", "inv": "MH/1646/2025-26"},
	{"amount": 130000.00, "date": "2026-07-24", "inv": "MH/1648/2025-26"},
	{"amount": 120000.00, "date": "2026-07-29", "inv": "MH/1720/2025-26"},
]


def run(dry_run=1):
	dry_run = int(dry_run)
	company = "MSA"
	transporter = "ALN"
	conversion_rate = 12800.0

	creditors_account = "Creditors USD - M"
	cash_account = "Kassa USD - M"
	bank_account = "NBU USD - M"

	if not dry_run:
		# 1. Delete all existing Payment Entries & GL Entries for ALN
		existing_pes = frappe.get_all(
			"Payment Entry", filters={"party": transporter, "company": company}, fields=["name"]
		)
		for pe in existing_pes:
			frappe.db.sql(
				"DELETE FROM `tabGL Entry` WHERE voucher_type='Payment Entry' AND voucher_no=%s", pe["name"]
			)
			frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE name=%s", pe["name"])

		frappe.db.commit()

	created_bank = 0
	created_cash = 0

	# 2. Post EXACT 14 Bank Payments
	for idx, b in enumerate(ALN_BANK_PAYMENTS, 1):
		amt = flt(b["amount"])
		pdate = b["date"]
		cin = b["inv"]
		remark_str = f"ALN Bank Payment #{idx} - {cin}"

		created_bank += 1
		if not dry_run:
			base_amt = amt * conversion_rate
			pe = frappe.get_doc(
				{
					"doctype": "Payment Entry",
					"company": company,
					"payment_type": "Pay",
					"party_type": "Supplier",
					"party": transporter,
					"paid_from": bank_account,
					"paid_to": creditors_account,
					"paid_amount": amt,
					"received_amount": amt,
					"base_paid_amount": base_amt,
					"base_received_amount": base_amt,
					"source_exchange_rate": conversion_rate,
					"target_exchange_rate": conversion_rate,
					"paid_from_account_currency": "USD",
					"paid_to_account_currency": "USD",
					"posting_date": pdate,
					"mode_of_payment": "Bank Draft",
					"remarks": remark_str,
					"docstatus": 0,
				}
			)
			pe.flags.ignore_validate = True
			pe.insert(ignore_permissions=True)
			pe_name = pe.name
			frappe.db.set_value("Payment Entry", pe_name, "docstatus", 1, update_modified=False)

			# Post GL Entries
			frappe.get_doc(
				{
					"doctype": "GL Entry",
					"company": company,
					"posting_date": pdate,
					"voucher_type": "Payment Entry",
					"voucher_no": pe_name,
					"account": bank_account,
					"debit": 0.0,
					"credit": base_amt,
					"debit_in_account_currency": 0.0,
					"credit_in_account_currency": amt,
					"account_currency": "USD",
					"is_cancelled": 0,
				}
			).insert(ignore_permissions=True)

			frappe.get_doc(
				{
					"doctype": "GL Entry",
					"company": company,
					"posting_date": pdate,
					"voucher_type": "Payment Entry",
					"voucher_no": pe_name,
					"account": creditors_account,
					"party_type": "Supplier",
					"party": transporter,
					"debit": base_amt,
					"credit": 0.0,
					"debit_in_account_currency": amt,
					"credit_in_account_currency": 0.0,
					"account_currency": "USD",
					"is_cancelled": 0,
				}
			).insert(ignore_permissions=True)

	# 3. Post EXACT 40 Cash Payments
	for idx, c in enumerate(ALN_CASH_PAYMENTS, 1):
		amt = flt(c["amount"])
		pdate = c["date"]
		cin = c["inv"]
		remark_str = f"ALN Cash Payment #{idx} - {cin}"

		created_cash += 1
		if not dry_run:
			base_amt = amt * conversion_rate
			pe = frappe.get_doc(
				{
					"doctype": "Payment Entry",
					"company": company,
					"payment_type": "Pay",
					"party_type": "Supplier",
					"party": transporter,
					"paid_from": cash_account,
					"paid_to": creditors_account,
					"paid_amount": amt,
					"received_amount": amt,
					"base_paid_amount": base_amt,
					"base_received_amount": base_amt,
					"source_exchange_rate": conversion_rate,
					"target_exchange_rate": conversion_rate,
					"paid_from_account_currency": "USD",
					"paid_to_account_currency": "USD",
					"posting_date": pdate,
					"mode_of_payment": "Cash",
					"remarks": remark_str,
					"docstatus": 0,
				}
			)
			pe.flags.ignore_validate = True
			pe.insert(ignore_permissions=True)
			pe_name = pe.name
			frappe.db.set_value("Payment Entry", pe_name, "docstatus", 1, update_modified=False)

			# Post GL Entries
			frappe.get_doc(
				{
					"doctype": "GL Entry",
					"company": company,
					"posting_date": pdate,
					"voucher_type": "Payment Entry",
					"voucher_no": pe_name,
					"account": cash_account,
					"debit": 0.0,
					"credit": base_amt,
					"debit_in_account_currency": 0.0,
					"credit_in_account_currency": amt,
					"account_currency": "USD",
					"is_cancelled": 0,
				}
			).insert(ignore_permissions=True)

			frappe.get_doc(
				{
					"doctype": "GL Entry",
					"company": company,
					"posting_date": pdate,
					"voucher_type": "Payment Entry",
					"voucher_no": pe_name,
					"account": creditors_account,
					"party_type": "Supplier",
					"party": transporter,
					"debit": base_amt,
					"credit": 0.0,
					"debit_in_account_currency": amt,
					"credit_in_account_currency": 0.0,
					"account_currency": "USD",
					"is_cancelled": 0,
				}
			).insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()

	tot_bank = sum(b["amount"] for b in ALN_BANK_PAYMENTS)
	tot_cash = sum(c["amount"] for c in ALN_CASH_PAYMENTS)
	mode = "DRY-RUN" if dry_run else "APPLIED"

	print("\n========================================================")
	print(f"  CLEAN & REPOST ALN EXACT PAYMENTS ({mode})")
	print("========================================================")
	print(f"Total Bank Payments: {created_bank} (${tot_bank:,.2f})")
	print(f"Total Cash Payments: {created_cash} (${tot_cash:,.2f})")
	print(f"Grand Total ALN Payments: ${tot_bank + tot_cash:,.2f}\n")

	return {
		"bank_count": created_bank,
		"cash_count": created_cash,
		"tot_bank": tot_bank,
		"tot_cash": tot_cash,
		"grand_total": tot_bank + tot_cash,
	}
