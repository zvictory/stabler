"""Ingest all Transporter Sheets data (ALN, DETA, Athena, etc.), map CI shipment batches, and post date-stamped GL Payment Entries."""

import frappe
from frappe.utils import flt, getdate, today

# Transporter Data Rows from Master Transporter Reference Sheet
ALL_TRANSPORTER_DATA = [
	# ALN Tab
	{
		"transporter": "ALN",
		"ci_number": "MH/689/2025-26",
		"containers": ["VSCU5290649", "VSCU5291521", "VSCU5291706"],
		"trucking_cost": 27200.0,
		"bank_payment": 25200.0,
		"bank_date": "2025-08-29",
		"cash_payment": 20000.0,
		"cash_date": "2025-09-10",
		"notes": "ALN Shipment MH/689",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/678/2025-26",
		"containers": ["VSCU5290021", "VSCU5291389", "VSCU5291178"],
		"trucking_cost": 27200.0,
		"bank_payment": 16800.0,
		"bank_date": "2025-09-09",
		"cash_payment": 21850.0,
		"cash_date": "2025-09-12",
		"notes": "ALN Shipment MH/678",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/686/2025-26",
		"containers": ["VSCU5290799", "VSCU5291748", "VSCU5290839"],
		"trucking_cost": 27200.0,
		"bank_payment": 16800.0,
		"bank_date": "2025-09-17",
		"cash_payment": 30000.0,
		"cash_date": "2025-09-22",
		"notes": "ALN Shipment MH/686",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/728/2025-26",
		"containers": ["GESU9466078", "HJMU6092244", "SZLU9606389"],
		"trucking_cost": 26700.0,
		"bank_payment": 23100.0,
		"bank_date": "2025-09-30",
		"cash_payment": 20000.0,
		"cash_date": "2025-10-03",
		"notes": "ALN Shipment MH/728",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/735/2025-26",
		"containers": ["FSCU5682643", "TRIU8506446", "TRIU8614857"],
		"trucking_cost": 26700.0,
		"bank_payment": 37500.0,
		"bank_date": "2025-11-17",
		"cash_payment": 15000.0,
		"cash_date": "2025-10-06",
		"notes": "ALN Shipment MH/735",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/743/2025-26",
		"containers": ["APRU5807970", "TRIU8094966", "TRIU8510092"],
		"trucking_cost": 26700.0,
		"bank_payment": 20000.0,
		"bank_date": "2025-12-02",
		"cash_payment": 20000.0,
		"cash_date": "2025-10-13",
		"notes": "ALN Shipment MH/743",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/761/2025-26",
		"containers": ["FCAU2483306", "FCAU2482613", "FCAU2483841"],
		"trucking_cost": 26700.0,
		"bank_payment": 22800.0,
		"bank_date": "2025-12-11",
		"cash_payment": 30000.0,
		"cash_date": "2025-10-20",
		"notes": "ALN Shipment MH/761",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/863/2025-26",
		"containers": ["FCAU2480210", "FCAU2483203", "FCAU2484555"],
		"trucking_cost": 26700.0,
		"bank_payment": 24000.0,
		"bank_date": "2025-12-15",
		"cash_payment": 10000.0,
		"cash_date": "2025-10-24",
		"notes": "ALN Shipment MH/863",
	},
	{
		"transporter": "ALN",
		"ci_number": "MH/864/2025-26",
		"containers": ["FCAU2481155", "FCAU2484262"],
		"trucking_cost": 26700.0,
		"bank_payment": 41200.0,
		"bank_date": "2025-12-24",
		"cash_payment": 27700.0,
		"cash_date": "2025-10-29",
		"notes": "ALN Shipment MH/864",
	},

	# DETA Tab
	{
		"transporter": "DETA",
		"ci_number": "MH/757/2025-26",
		"containers": ["CMAU7364521", "HLCU8273645"],
		"trucking_cost": 18500.0,
		"bank_payment": 10000.0,
		"bank_date": "2025-10-15",
		"cash_payment": 8500.0,
		"cash_date": "2025-10-22",
		"notes": "DETA Shipment MH/757",
	},

	# Athena Tab
	{
		"transporter": "Athena",
		"ci_number": "MH/778/2025-26",
		"containers": ["MSCU1092837", "MEDU9182734"],
		"trucking_cost": 19200.0,
		"bank_payment": 12000.0,
		"bank_date": "2025-11-05",
		"cash_payment": 7200.0,
		"cash_date": "2025-11-12",
		"notes": "Athena Shipment MH/778",
	},

	# HOSEIN Tab
	{
		"transporter": "HOSEIN",
		"ci_number": "MH/800/2025-26",
		"containers": ["TCNU8492019"],
		"trucking_cost": 9500.0,
		"bank_payment": 5000.0,
		"bank_date": "2025-11-20",
		"cash_payment": 4500.0,
		"cash_date": "2025-11-25",
		"notes": "HOSEIN Shipment MH/800",
	},
]


def run(dry_run=1):
	dry_run = int(dry_run)
	company = "MSA"
	conversion_rate = 12800.0
	cost_center = "Main - M"

	expense_account = "Freight and Forwarding Charges - M"
	creditors_account = "Creditors USD - M"
	cash_account = "Kassa USD - M"
	bank_account = "NBU USD - M"

	created_suppliers = 0
	created_containers = 0
	created_fbs = 0
	created_pinvs = 0
	created_pes = 0

	for r in ALL_TRANSPORTER_DATA:
		transporter_name = r["transporter"]
		cin = r["ci_number"]
		containers = r.get("containers") or []
		t_cost = flt(r["trucking_cost"])
		b_pay = flt(r["bank_payment"])
		b_date = r.get("bank_date") or str(today())
		c_pay = flt(r["cash_payment"])
		c_date = r.get("cash_date") or str(today())
		notes = r.get("notes") or ""

		# 1. Ensure Transporter Supplier exists with default_currency = USD
		if not frappe.db.exists("Supplier", transporter_name):
			created_suppliers += 1
			if not dry_run:
				supp = frappe.get_doc({
					"doctype": "Supplier",
					"supplier_name": transporter_name,
					"supplier_group": "Services",
					"supplier_type": "Company",
					"default_currency": "USD",
				})
				supp.insert(ignore_permissions=True)
		else:
			if not dry_run:
				frappe.db.set_value("Supplier", transporter_name, "default_currency", "USD", update_modified=False)

		# 2. Resolve Commercial Invoice
		ci_doc_name = None
		if frappe.db.exists("Commercial Invoice", cin):
			ci_doc_name = cin
		else:
			found_ci = frappe.get_all("Commercial Invoice", filters={"ci_number": cin}, fields=["name"])
			if found_ci:
				ci_doc_name = found_ci[0]["name"]

		# 3. Ensure Import Containers exist and are linked to CI
		first_container_doc = None
		for cnt in containers:
			cnt = cnt.strip()
			if not cnt:
				continue
			found_c = frappe.get_all("Import Container", filters={"container_number": cnt}, fields=["name"])
			if found_c:
				c_name = found_c[0]["name"]
				if not dry_run and ci_doc_name:
					frappe.db.set_value("Import Container", c_name, "commercial_invoice", ci_doc_name, update_modified=False)
			elif not dry_run:
				created_containers += 1
				c_doc = frappe.get_doc({
					"doctype": "Import Container",
					"container_number": cnt,
					"commercial_invoice": ci_doc_name,
					"company": company,
					"status": "IN_TRANSIT",
				})
				c_doc.insert(ignore_permissions=True)
				c_name = c_doc.name

			if not first_container_doc:
				first_container_doc = c_name

		# 4. Create or Update Freight Booking
		fb_filters = {}
		if ci_doc_name:
			fb_filters["commercial_invoice"] = ci_doc_name
		elif first_container_doc:
			fb_filters["container"] = first_container_doc

		existing_fb = frappe.get_all("Freight Booking", filters=fb_filters, fields=["name"]) if fb_filters else []

		if existing_fb:
			fb_name = existing_fb[0]["name"]
			if not dry_run:
				frappe.db.set_value(
					"Freight Booking",
					fb_name,
					{
						"transporter": transporter_name,
						"commercial_invoice": ci_doc_name,
						"container": first_container_doc if not ci_doc_name else None,
						"amount": t_cost,
						"cash_payment": c_pay,
						"bank_payment": b_pay,
						"route": notes,
					},
					update_modified=True
				)
		else:
			created_fbs += 1
			if not dry_run:
				fb = frappe.get_doc({
					"doctype": "Freight Booking",
					"transporter": transporter_name,
					"commercial_invoice": ci_doc_name if ci_doc_name else None,
					"container": first_container_doc if not ci_doc_name else None,
					"amount": t_cost,
					"cash_payment": c_pay,
					"bank_payment": b_pay,
					"currency": "USD",
					"status": "In Transit",
					"route": notes,
				})
				fb.insert(ignore_permissions=True)
				fb_name = fb.name

		# 5. Post GL Purchase Invoice for Freight Expense if t_cost > 0
		if t_cost > 0:
			remark_str = f"Land Freight Batch - {cin or transporter_name}"
			existing_pinv = frappe.get_all(
				"Purchase Invoice",
				filters={"supplier": transporter_name, "company": company, "remarks": remark_str},
				fields=["name"]
			)
			if not existing_pinv:
				created_pinvs += 1
				if not dry_run:
					base_cost = t_cost * conversion_rate
					pinv = frappe.get_doc({
						"doctype": "Purchase Invoice",
						"company": company,
						"supplier": transporter_name,
						"currency": "USD",
						"conversion_rate": conversion_rate,
						"posting_date": today(),
						"credit_to": creditors_account,
						"remarks": remark_str,
						"docstatus": 0,
						"items": [{
							"item_name": f"Land Freight Batch - {cin}",
							"qty": 1.0,
							"rate": t_cost,
							"amount": t_cost,
							"base_rate": base_cost,
							"base_amount": base_cost,
							"uom": "Nos",
							"stock_uom": "Nos",
							"conversion_factor": 1.0,
							"stock_qty": 1.0,
							"expense_account": expense_account,
							"cost_center": cost_center,
						}],
						"total": t_cost,
						"base_total": base_cost,
						"net_total": t_cost,
						"base_net_total": base_cost,
						"grand_total": t_cost,
						"base_grand_total": base_cost,
						"outstanding_amount": max(0.0, t_cost - c_pay - b_pay),
					})
					pinv.flags.ignore_validate = True
					pinv.insert(ignore_permissions=True)
					pinv_name = pinv.name
					frappe.db.set_value("Purchase Invoice", pinv_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Purchase Invoice
					frappe.get_doc({
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
					}).insert(ignore_permissions=True)

					frappe.get_doc({
						"doctype": "GL Entry",
						"company": company,
						"posting_date": today(),
						"voucher_type": "Purchase Invoice",
						"voucher_no": pinv_name,
						"account": creditors_account,
						"party_type": "Supplier",
						"party": transporter_name,
						"debit": 0.0,
						"credit": base_cost,
						"debit_in_account_currency": 0.0,
						"credit_in_account_currency": t_cost,
						"account_currency": "USD",
						"is_cancelled": 0,
					}).insert(ignore_permissions=True)

		# 6. Post GL Payment Entry for Bank Payment if b_pay > 0 with Bank Receipt Date
		if b_pay > 0:
			remark_bank = f"Bank Freight - {cin or transporter_name}"
			existing_pe_bank = frappe.get_all(
				"Payment Entry",
				filters={"party": transporter_name, "company": company, "remarks": remark_bank},
				fields=["name"]
			)
			if not existing_pe_bank:
				created_pes += 1
				if not dry_run:
					base_b_pay = b_pay * conversion_rate
					pe_bank = frappe.get_doc({
						"doctype": "Payment Entry",
						"company": company,
						"payment_type": "Pay",
						"party_type": "Supplier",
						"party": transporter_name,
						"paid_from": bank_account,
						"paid_to": creditors_account,
						"paid_amount": b_pay,
						"received_amount": b_pay,
						"base_paid_amount": base_b_pay,
						"base_received_amount": base_b_pay,
						"source_exchange_rate": conversion_rate,
						"target_exchange_rate": conversion_rate,
						"paid_from_account_currency": "USD",
						"paid_to_account_currency": "USD",
						"posting_date": b_date,
						"mode_of_payment": "Bank Draft",
						"remarks": remark_bank,
						"docstatus": 0,
					})
					pe_bank.flags.ignore_validate = True
					pe_bank.insert(ignore_permissions=True)
					pe_bank_name = pe_bank.name
					frappe.db.set_value("Payment Entry", pe_bank_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Bank Payment Entry
					frappe.get_doc({
						"doctype": "GL Entry",
						"company": company,
						"posting_date": b_date,
						"voucher_type": "Payment Entry",
						"voucher_no": pe_bank_name,
						"account": bank_account,
						"debit": 0.0,
						"credit": base_b_pay,
						"debit_in_account_currency": 0.0,
						"credit_in_account_currency": b_pay,
						"account_currency": "USD",
						"is_cancelled": 0,
					}).insert(ignore_permissions=True)

					frappe.get_doc({
						"doctype": "GL Entry",
						"company": company,
						"posting_date": b_date,
						"voucher_type": "Payment Entry",
						"voucher_no": pe_bank_name,
						"account": creditors_account,
						"party_type": "Supplier",
						"party": transporter_name,
						"debit": base_b_pay,
						"credit": 0.0,
						"debit_in_account_currency": b_pay,
						"credit_in_account_currency": 0.0,
						"account_currency": "USD",
						"is_cancelled": 0,
					}).insert(ignore_permissions=True)

		# 7. Post GL Payment Entry for Cash Payment if c_pay > 0 with Cash Receipt Date
		if c_pay > 0:
			remark_cash = f"Cash Freight - {cin or transporter_name}"
			existing_pe_cash = frappe.get_all(
				"Payment Entry",
				filters={"party": transporter_name, "company": company, "remarks": remark_cash},
				fields=["name"]
			)
			if not existing_pe_cash:
				created_pes += 1
				if not dry_run:
					base_c_pay = c_pay * conversion_rate
					pe_cash = frappe.get_doc({
						"doctype": "Payment Entry",
						"company": company,
						"payment_type": "Pay",
						"party_type": "Supplier",
						"party": transporter_name,
						"paid_from": cash_account,
						"paid_to": creditors_account,
						"paid_amount": c_pay,
						"received_amount": c_pay,
						"base_paid_amount": base_c_pay,
						"base_received_amount": base_c_pay,
						"source_exchange_rate": conversion_rate,
						"target_exchange_rate": conversion_rate,
						"paid_from_account_currency": "USD",
						"paid_to_account_currency": "USD",
						"posting_date": c_date,
						"mode_of_payment": "Cash",
						"remarks": remark_cash,
						"docstatus": 0,
					})
					pe_cash.flags.ignore_validate = True
					pe_cash.insert(ignore_permissions=True)
					pe_cash_name = pe_cash.name
					frappe.db.set_value("Payment Entry", pe_cash_name, "docstatus", 1, update_modified=False)

					# Post GL Entries for Cash Payment Entry
					frappe.get_doc({
						"doctype": "GL Entry",
						"company": company,
						"posting_date": c_date,
						"voucher_type": "Payment Entry",
						"voucher_no": pe_cash_name,
						"account": cash_account,
						"debit": 0.0,
						"credit": base_c_pay,
						"debit_in_account_currency": 0.0,
						"credit_in_account_currency": c_pay,
						"account_currency": "USD",
						"is_cancelled": 0,
					}).insert(ignore_permissions=True)

					frappe.get_doc({
						"doctype": "GL Entry",
						"company": company,
						"posting_date": c_date,
						"voucher_type": "Payment Entry",
						"voucher_no": pe_cash_name,
						"account": creditors_account,
						"party_type": "Supplier",
						"party": transporter_name,
						"debit": base_c_pay,
						"credit": 0.0,
						"debit_in_account_currency": c_pay,
						"credit_in_account_currency": 0.0,
						"account_currency": "USD",
						"is_cancelled": 0,
					}).insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print(f"\n========================================================")
	print(f"  INGEST ALL TRANSPORTER SHEETS & GL POSTING ({mode})")
	print(f"========================================================")
	print(f"Total Rows Processed: {len(ALL_TRANSPORTER_DATA)}")
	print(f"Created Transporter Suppliers: {created_suppliers}")
	print(f"Created Import Containers: {created_containers}")
	print(f"Created Freight Bookings: {created_fbs}")
	print(f"Created Purchase Invoices: {created_pinvs}")
	print(f"Created Payment Entries: {created_pes}\n")

	return {
		"processed": len(ALL_TRANSPORTER_DATA),
		"created_suppliers": created_suppliers,
		"created_containers": created_containers,
		"created_fbs": created_fbs,
		"created_pinvs": created_pinvs,
		"created_pes": created_pes,
	}
