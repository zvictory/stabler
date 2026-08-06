"""Set Transporters default_currency to USD and post real GL Purchase Invoices & Payment Entries for Cash/Bank freight payments."""

import frappe
from frappe.utils import flt, today


def run(dry_run=1):
	dry_run = int(dry_run)
	company = "MSA"
	conversion_rate = 12800.0
	cost_center = "Main - M"

	# 1. Update all Transporter Suppliers to default_currency = 'USD'
	transporters = frappe.get_all(
		"Supplier", filters=[["disabled", "=", 0]], fields=["name", "supplier_name", "default_currency"]
	)

	updated_ccy = 0
	for t in transporters:
		if t.default_currency != "USD":
			updated_ccy += 1
			if not dry_run:
				frappe.db.set_value("Supplier", t.name, "default_currency", "USD", update_modified=False)

	# 2. Process Freight Bookings to create/sync GL Purchase Invoices & Payment Entries
	fbs = frappe.get_all(
		"Freight Booking",
		filters={"docstatus": ["<", 2]},
		fields=[
			"name",
			"transporter",
			"commercial_invoice",
			"container",
			"vehicle_number",
			"amount",
			"cash_payment",
			"bank_payment",
			"currency",
			"route",
		],
	)

	created_pinvs = 0
	created_pes = 0

	expense_account = "Freight and Forwarding Charges - M"
	creditors_account = "Creditors USD - M"
	cash_account = "Kassa USD - M"
	bank_account = "NBU USD - M"

	for fb in fbs:
		transporter = fb.transporter
		cost = flt(fb.amount)
		cash = flt(fb.cash_payment)
		bank = flt(fb.bank_payment)

		if not transporter:
			continue

		# Ensure Transporter currency is USD
		if not dry_run:
			frappe.db.set_value("Supplier", transporter, "default_currency", "USD", update_modified=False)

		# A. Create / Update Purchase Invoice for Freight Expense if cost > 0
		if cost > 0:
			existing_pinv = frappe.get_all(
				"Purchase Invoice",
				filters={"supplier": transporter, "company": company, "remarks": f"Land Freight - {fb.name}"},
				fields=["name"],
			)
			if not existing_pinv:
				created_pinvs += 1
				if not dry_run:
					base_cost = cost * conversion_rate
					pinv = frappe.get_doc(
						{
							"doctype": "Purchase Invoice",
							"company": company,
							"supplier": transporter,
							"currency": "USD",
							"conversion_rate": conversion_rate,
							"posting_date": today(),
							"credit_to": creditors_account,
							"remarks": f"Land Freight - {fb.name}",
							"docstatus": 0,
							"items": [
								{
									"item_name": f"Land Freight - {fb.container or fb.vehicle_number or fb.name}",
									"qty": 1.0,
									"rate": cost,
									"amount": cost,
									"base_rate": base_cost,
									"base_amount": base_cost,
									"uom": "Nos",
									"stock_uom": "Nos",
									"conversion_factor": 1.0,
									"stock_qty": 1.0,
									"expense_account": expense_account,
									"cost_center": cost_center,
								}
							],
							"total": cost,
							"base_total": base_cost,
							"net_total": cost,
							"base_net_total": base_cost,
							"grand_total": cost,
							"base_grand_total": base_cost,
							"outstanding_amount": max(0.0, cost - cash - bank),
						}
					)
					pinv.flags.ignore_validate = True
					pinv.insert(ignore_permissions=True)
					pinv_name = pinv.name
					frappe.db.set_value("Purchase Invoice", pinv_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Purchase Invoice
					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Purchase Invoice",
							"voucher_no": pinv_name,
							"account": expense_account,
							"cost_center": cost_center,
							"debit": base_cost,
							"credit": 0.0,
							"debit_in_account_currency": base_cost,
							"credit_in_account_currency": 0.0,
							"account_currency": "UZS",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Purchase Invoice",
							"voucher_no": pinv_name,
							"account": creditors_account,
							"party_type": "Supplier",
							"party": transporter,
							"debit": 0.0,
							"credit": base_cost,
							"debit_in_account_currency": 0.0,
							"credit_in_account_currency": cost,
							"account_currency": "USD",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

		# B. Create Payment Entry for Cash Payment if cash > 0
		if cash > 0:
			existing_pe_cash = frappe.get_all(
				"Payment Entry",
				filters={"party": transporter, "company": company, "remarks": f"Cash Freight - {fb.name}"},
				fields=["name"],
			)
			if not existing_pe_cash:
				created_pes += 1
				if not dry_run:
					base_cash = cash * conversion_rate
					pe_cash = frappe.get_doc(
						{
							"doctype": "Payment Entry",
							"company": company,
							"payment_type": "Pay",
							"party_type": "Supplier",
							"party": transporter,
							"paid_from": cash_account,
							"paid_to": creditors_account,
							"paid_amount": cash,
							"received_amount": cash,
							"base_paid_amount": base_cash,
							"base_received_amount": base_cash,
							"source_exchange_rate": conversion_rate,
							"target_exchange_rate": conversion_rate,
							"paid_from_account_currency": "USD",
							"paid_to_account_currency": "USD",
							"posting_date": today(),
							"mode_of_payment": "Cash",
							"remarks": f"Cash Freight - {fb.name}",
							"docstatus": 0,
						}
					)
					pe_cash.flags.ignore_validate = True
					pe_cash.insert(ignore_permissions=True)
					pe_cash_name = pe_cash.name
					frappe.db.set_value("Payment Entry", pe_cash_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Cash Payment Entry
					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Payment Entry",
							"voucher_no": pe_cash_name,
							"account": cash_account,
							"debit": 0.0,
							"credit": base_cash,
							"debit_in_account_currency": 0.0,
							"credit_in_account_currency": cash,
							"account_currency": "USD",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Payment Entry",
							"voucher_no": pe_cash_name,
							"account": creditors_account,
							"party_type": "Supplier",
							"party": transporter,
							"debit": base_cash,
							"credit": 0.0,
							"debit_in_account_currency": cash,
							"credit_in_account_currency": 0.0,
							"account_currency": "USD",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

		# C. Create Payment Entry for Bank Payment if bank > 0
		if bank > 0:
			existing_pe_bank = frappe.get_all(
				"Payment Entry",
				filters={"party": transporter, "company": company, "remarks": f"Bank Freight - {fb.name}"},
				fields=["name"],
			)
			if not existing_pe_bank:
				created_pes += 1
				if not dry_run:
					base_bank = bank * conversion_rate
					pe_bank = frappe.get_doc(
						{
							"doctype": "Payment Entry",
							"company": company,
							"payment_type": "Pay",
							"party_type": "Supplier",
							"party": transporter,
							"paid_from": bank_account,
							"paid_to": creditors_account,
							"paid_amount": bank,
							"received_amount": bank,
							"base_paid_amount": base_bank,
							"base_received_amount": base_bank,
							"source_exchange_rate": conversion_rate,
							"target_exchange_rate": conversion_rate,
							"paid_from_account_currency": "USD",
							"paid_to_account_currency": "USD",
							"posting_date": today(),
							"mode_of_payment": "Bank Draft",
							"remarks": f"Bank Freight - {fb.name}",
							"docstatus": 0,
						}
					)
					pe_bank.flags.ignore_validate = True
					pe_bank.insert(ignore_permissions=True)
					pe_bank_name = pe_bank.name
					frappe.db.set_value("Payment Entry", pe_bank_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Bank Payment Entry
					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Payment Entry",
							"voucher_no": pe_bank_name,
							"account": bank_account,
							"debit": 0.0,
							"credit": base_bank,
							"debit_in_account_currency": 0.0,
							"credit_in_account_currency": bank,
							"account_currency": "USD",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

					frappe.get_doc(
						{
							"doctype": "GL Entry",
							"company": company,
							"posting_date": today(),
							"voucher_type": "Payment Entry",
							"voucher_no": pe_bank_name,
							"account": creditors_account,
							"party_type": "Supplier",
							"party": transporter,
							"debit": base_bank,
							"credit": 0.0,
							"debit_in_account_currency": bank,
							"credit_in_account_currency": 0.0,
							"account_currency": "USD",
							"is_cancelled": 0,
						}
					).insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print("\n========================================================")
	print(f"  SYNC TRANSPORTER USD CURRENCY & GL ENTRIES ({mode})")
	print("========================================================")
	print(f"Transporter Suppliers updated to USD: {updated_ccy}")
	print(f"GL Purchase Invoices created: {created_pinvs}")
	print(f"GL Payment Entries created: {created_pes}\n")

	return {
		"updated_ccy": updated_ccy,
		"created_pinvs": created_pinvs,
		"created_pes": created_pes,
	}
