"""Ingest all 14 Bank Payments ($453,600.80) and 40 Cash Payments ($2,181,761.00) for ALN Transporter into GL Payment Entries with exact dates."""

import frappe
from frappe.utils import flt, getdate

ALN_BANK_PAYMENTS = [
	{"amount": 25200.00, "date": "2025-08-29"},
	{"amount": 16800.00, "date": "2025-09-09"},
	{"amount": 16800.00, "date": "2025-09-17"},
	{"amount": 23100.00, "date": "2025-09-30"},
	{"amount": 37500.00, "date": "2025-11-17"},
	{"amount": 20000.00, "date": "2025-12-02"},
	{"amount": 22800.00, "date": "2025-12-11"},
	{"amount": 24000.00, "date": "2025-12-15"},
	{"amount": 41200.00, "date": "2025-12-24"},
	{"amount": 24600.00, "date": "2025-12-30"},
	{"amount": 49600.00, "date": "2026-01-19"},
	{"amount": 42800.00, "date": "2026-01-30"},
	{"amount": 100800.00, "date": "2026-03-30"},
	{"amount": 8400.80, "date": "2026-03-31"},
]

ALN_CASH_PAYMENTS = [
	{"amount": 20000.00, "date": "2025-09-10"},
	{"amount": 21850.00, "date": "2025-09-12"},
	{"amount": 30000.00, "date": "2025-09-22"},
	{"amount": 20000.00, "date": "2025-10-03"},
	{"amount": 15000.00, "date": "2025-10-06"},
	{"amount": 20000.00, "date": "2025-10-13"},
	{"amount": 30000.00, "date": "2025-10-20"},
	{"amount": 10000.00, "date": "2025-10-24"},
	{"amount": 27700.00, "date": "2025-10-29"},
	{"amount": 29900.00, "date": "2025-11-04"},
	{"amount": 30000.00, "date": "2025-11-07"},
	{"amount": 50000.00, "date": "2025-11-15"},
	{"amount": 10000.00, "date": "2025-11-21"},
	{"amount": 30000.00, "date": "2025-11-30"},
	{"amount": 40000.00, "date": "2025-12-09"},
	{"amount": 25000.00, "date": "2025-12-15"},
	{"amount": 20000.00, "date": "2025-12-25"},
	{"amount": 40000.00, "date": "2025-12-30"},
	{"amount": 20000.00, "date": "2026-01-05"},
	{"amount": 60000.00, "date": "2026-01-23"},
	{"amount": 60000.00, "date": "2026-02-02"},
	{"amount": 60000.00, "date": "2026-02-04"},
	{"amount": 50000.00, "date": "2026-02-12"},
	{"amount": 80000.00, "date": "2026-02-16"},
	{"amount": 100000.00, "date": "2026-03-01"},
	{"amount": 45000.00, "date": "2026-03-08"},
	{"amount": 50000.00, "date": "2026-03-16"},
	{"amount": 55000.00, "date": "2026-03-25"},
	{"amount": 50000.00, "date": "2026-04-07"},
	{"amount": 4296.00, "date": "2026-04-18"},
	{"amount": 84575.00, "date": "2026-04-22"},
	{"amount": 100000.00, "date": "2026-05-26"},
	{"amount": 140000.00, "date": "2026-06-01"},
	{"amount": 50000.00, "date": "2026-06-03"},
	{"amount": 60700.00, "date": "2026-06-09"},
	{"amount": 142740.00, "date": "2026-06-29"},
	{"amount": 100000.00, "date": "2026-07-13"},
	{"amount": 150000.00, "date": "2026-07-17"},
	{"amount": 130000.00, "date": "2026-07-24"},
	{"amount": 120000.00, "date": "2026-07-29"},
]


def run(dry_run=1):
	dry_run = int(dry_run)
	company = "MSA"
	transporter = "ALN"
	conversion_rate = 12800.0

	creditors_account = "Creditors USD - M"
	cash_account = "Kassa USD - M"
	bank_account = "NBU USD - M"

	# 1. Ensure Transporter Supplier exists with default_currency = USD
	if not frappe.db.exists("Supplier", transporter):
		if not dry_run:
			supp = frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": transporter,
				"supplier_group": "Services",
				"supplier_type": "Company",
				"default_currency": "USD",
			})
			supp.insert(ignore_permissions=True)
	else:
		if not dry_run:
			frappe.db.set_value("Supplier", transporter, "default_currency", "USD", update_modified=False)

	created_bank_pes = 0
	created_cash_pes = 0

	# 2. Process Bank Payments
	for idx, b in enumerate(ALN_BANK_PAYMENTS, 1):
		amt = flt(b["amount"])
		pdate = b["date"]
		remark_str = f"ALN Bank Payment #{idx} ({pdate})"

		# Check duplicate by remark or voucher
		existing = frappe.get_all(
			"Payment Entry",
			filters={"party": transporter, "company": company, "paid_amount": amt, "posting_date": pdate, "mode_of_payment": "Bank Draft"},
			fields=["name"]
		)
		if not existing:
			created_bank_pes += 1
			if not dry_run:
				base_amt = amt * conversion_rate
				pe = frappe.get_doc({
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
				})
				pe.flags.ignore_validate = True
				pe.insert(ignore_permissions=True)
				pe_name = pe.name
				frappe.db.set_value("Payment Entry", pe_name, "docstatus", 1, update_modified=False)

				# Post GL Entries
				frappe.get_doc({
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
				}).insert(ignore_permissions=True)

				frappe.get_doc({
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
				}).insert(ignore_permissions=True)

	# 3. Process Cash Payments
	for idx, c in enumerate(ALN_CASH_PAYMENTS, 1):
		amt = flt(c["amount"])
		pdate = c["date"]
		remark_str = f"ALN Cash Payment #{idx} ({pdate})"

		existing = frappe.get_all(
			"Payment Entry",
			filters={"party": transporter, "company": company, "paid_amount": amt, "posting_date": pdate, "mode_of_payment": "Cash"},
			fields=["name"]
		)
		if not existing:
			created_cash_pes += 1
			if not dry_run:
				base_amt = amt * conversion_rate
				pe = frappe.get_doc({
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
				})
				pe.flags.ignore_validate = True
				pe.insert(ignore_permissions=True)
				pe_name = pe.name
				frappe.db.set_value("Payment Entry", pe_name, "docstatus", 1, update_modified=False)

				# Post GL Entries
				frappe.get_doc({
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
				}).insert(ignore_permissions=True)

				frappe.get_doc({
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
				}).insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	tot_bank = sum(b["amount"] for b in ALN_BANK_PAYMENTS)
	tot_cash = sum(c["amount"] for c in ALN_CASH_PAYMENTS)

	print(f"\n========================================================")
	print(f"  INGEST ALL ALN PAYMENTS INTO GL ({mode})")
	print(f"========================================================")
	print(f"Total Bank Payments: {len(ALN_BANK_PAYMENTS)} (${tot_bank:,.2f}) -> Created: {created_bank_pes}")
	print(f"Total Cash Payments: {len(ALN_CASH_PAYMENTS)} (${tot_cash:,.2f}) -> Created: {created_cash_pes}")
	print(f"Combined Payments Total: ${tot_bank + tot_cash:,.2f}\n")

	return {
		"created_bank_pes": created_bank_pes,
		"created_cash_pes": created_cash_pes,
		"total_bank_amount": tot_bank,
		"total_cash_amount": tot_cash,
	}
