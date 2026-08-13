"""Seed fixture for imports UAT tests."""

from __future__ import annotations

import json

import frappe
from frappe.utils import nowdate

DEMO_SUFFIX = " [UAT]"


def _guard():
	if getattr(frappe.local, "site", "") != "genesis-test.local":
		frappe.throw("UAT fixture must only run on genesis-test.local.")
	if not frappe.conf.get("developer_mode"):
		frappe.throw("UAT fixture requires developer_mode.")


def seed():
	_guard()
	if frappe.db.exists("Commercial Invoice", {"ci_number": f"UAT-CI{DEMO_SUFFIX}"}):
		print("Demo UAT data already seeded — skipping. Run unseed() first to recreate.")
		return

	company = "_Test Company"
	today = nowdate()

	# created_cxs = every rate the harness relies on, whether seeded or pre-existing.
	# inserted_cxs = only the documents this seed actually created. unseed() may delete
	# the second list and must never touch the difference — those belong to the site.
	created_cxs = []
	inserted_cxs = []

	def ensure_cx(from_cur, to_cur, rate):
		existing = frappe.db.get_value(
			"Currency Exchange", {"date": today, "from_currency": from_cur, "to_currency": to_cur}
		)
		if not existing:
			cx = frappe.new_doc("Currency Exchange")
			cx.date = today
			cx.from_currency = from_cur
			cx.to_currency = to_cur
			cx.exchange_rate = rate
			cx.for_buying = 1
			cx.for_selling = 1
			cx.insert(ignore_permissions=True)
			created_cxs.append(cx.name)
			inserted_cxs.append(cx.name)
		else:
			created_cxs.append(existing)

	ensure_cx("USD", "UZS", 12500)
	ensure_cx("EUR", "UZS", 13500)

	# Store old settings in Note
	old_lcv = frappe.db.get_single_value("Stabler Settings", "imports_lcv_expense_account")
	settings = frappe.get_doc("Stabler Settings")
	old_transport = ""
	old_ci = ""
	for row in settings.get("imports_settings") or []:
		if row.company == company:
			old_transport = row.imports_transport_supplier_groups or ""
			old_ci = row.ci_supplier_groups or ""
			break

	if not frappe.db.exists("Note", {"title": f"old_settings{DEMO_SUFFIX}"}):
		doc = frappe.new_doc("Note")
		doc.title = f"old_settings{DEMO_SUFFIX}"
		doc.content = json.dumps(
			{
				"old_lcv": old_lcv or "",
				"old_transport": old_transport,
				"old_ci": old_ci,
				"created_cxs": created_cxs,
				"inserted_cxs": inserted_cxs,
			}
		)
		doc.insert(ignore_permissions=True)

	# Create Landed Cost expense account
	account_name = f"UAT LCV Expense{DEMO_SUFFIX}"
	acc_full = f"{account_name} - _TC"
	if not frappe.db.exists("Account", acc_full):
		parent = frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 1})
		doc = frappe.new_doc("Account")
		doc.account_name = account_name
		doc.company = company
		doc.parent_account = parent
		doc.account_type = "Expenses Included In Valuation"
		doc.is_group = 0
		doc.insert(ignore_permissions=True)

	def ensure_payable(currency):
		acc = frappe.db.get_value(
			"Account",
			{
				"company": company,
				"root_type": "Liability",
				"account_type": "Payable",
				"account_currency": currency,
			},
		)
		if not acc:
			parent = frappe.db.get_value(
				"Account", {"company": company, "root_type": "Liability", "is_group": 1}
			)
			doc = frappe.new_doc("Account")
			doc.account_name = f"UAT Creditors {currency}{DEMO_SUFFIX}"
			doc.company = company
			doc.parent_account = parent
			doc.account_type = "Payable"
			doc.account_currency = currency
			doc.is_group = 0
			doc.insert(ignore_permissions=True)

	ensure_payable("USD")
	ensure_payable("EUR")

	# Setup suppliers
	carrier_name = f"UAT Carrier{DEMO_SUFFIX}"
	if not frappe.db.exists("Supplier", carrier_name):
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = carrier_name
		doc.supplier_group = "Services"
		doc.insert(ignore_permissions=True)

	vendor_name = f"UAT Vendor{DEMO_SUFFIX}"
	if not frappe.db.exists("Supplier", vendor_name):
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = vendor_name
		doc.supplier_group = "All Supplier Groups"
		doc.insert(ignore_permissions=True)

	# Setup item
	item_code = f"UAT Item{DEMO_SUFFIX}"
	if not frappe.db.exists("Item", item_code):
		group = frappe.db.get_value("Item Group", {"is_group": 0})
		doc = frappe.new_doc("Item")
		doc.item_code = item_code
		doc.item_name = item_code
		doc.item_group = group
		doc.is_stock_item = 1
		doc.stock_uom = "Nos"
		doc.insert(ignore_permissions=True)

	# Setup warehouse
	warehouse_name = f"UAT Warehouse{DEMO_SUFFIX}"
	warehouse_full = f"{warehouse_name} - _TC"
	if not frappe.db.exists("Warehouse", warehouse_full):
		doc = frappe.new_doc("Warehouse")
		doc.warehouse_name = warehouse_name
		doc.company = company
		doc.is_group = 0
		doc.insert(ignore_permissions=True)

	# Create second company for gating tests
	company2 = f"UAT Company 2{DEMO_SUFFIX}"
	company2_abbr = "UC2"
	if not frappe.db.exists("Company", company2):
		default_country = frappe.db.get_value("Company", company, "country") or "Uzbekistan"
		doc = frappe.new_doc("Company")
		doc.company_name = company2
		doc.abbr = company2_abbr
		doc.default_currency = "UZS"
		doc.country = default_country
		doc.flags.ignore_chart_of_accounts = True
		doc.insert(ignore_permissions=True)

	# Load Settings once, apply all modifications and save once
	settings = frappe.get_doc("Stabler Settings")
	settings.imports_lcv_expense_account = acc_full

	# Set transport/service supplier groups
	found_imports = False
	for row in settings.get("imports_settings") or []:
		if row.company == company:
			row.imports_transport_supplier_groups = "Services\nAll Supplier Groups"
			row.ci_supplier_groups = "Services\nAll Supplier Groups"
			found_imports = True
			break
	if not found_imports:
		settings.append(
			"imports_settings",
			{
				"company": company,
				"imports_transport_supplier_groups": "Services\nAll Supplier Groups",
				"ci_supplier_groups": "Services\nAll Supplier Groups",
			},
		)

	# Configure Stabler Settings for company2 with imports = 0
	found_module = None
	for row in settings.company_modules or []:
		if row.company == company2:
			row.enable_imports = 0
			found_module = row
			break
	if not found_module:
		settings.append("company_modules", {"company": company2, "enable_imports": 0})

	settings.save(ignore_permissions=True)

	# Setup Commercial Invoice for company1
	ci_number = f"UAT-CI{DEMO_SUFFIX}"
	ci = frappe.new_doc("Commercial Invoice")
	ci.company = company
	ci.supplier = vendor_name
	ci.currency = "USD"
	ci.conversion_rate = 12500
	ci.ci_date = today
	ci.ci_number = ci_number
	ci.status = "STUFFED"
	ci.total_boxes = 100
	ci.total_kg = 1000
	ci.agreed_total = 5000

	ci.append(
		"items",
		{"item": item_code, "boxes": 100, "box_weight_kg": 10, "qty": 1000, "rate": 5, "amount": 5000},
	)
	ci.insert(ignore_permissions=True)
	ci_name = ci.name

	# Setup Commercial Invoice for company2
	ci2_number = f"UAT-CI2{DEMO_SUFFIX}"
	ci2 = frappe.new_doc("Commercial Invoice")
	ci2.company = company2
	ci2.supplier = vendor_name
	ci2.currency = "USD"
	ci2.conversion_rate = 12500
	ci2.ci_date = today
	ci2.ci_number = ci2_number
	ci2.status = "STUFFED"
	ci2.insert(ignore_permissions=True)

	# Create Import Containers
	for c_letter in ["A", "B"]:
		c_num = f"UAT-CONT-{c_letter}{DEMO_SUFFIX}"
		cont = frappe.new_doc("Import Container")
		cont.container_number = c_num
		cont.commercial_invoice = ci_name
		cont.company = company
		cont.status = "STUFFED"
		cont.total_boxes = 50
		cont.total_kg = 500

		cont.append("items", {"item_code": item_code, "box_qty": 50, "total_kg": 500})

		if c_letter == "A":
			cont.append(
				"cost_lines",
				{"cost_component": "Freight", "currency": "USD", "amount": 100, "include_in_landed_cost": 1},
			)
			cont.append(
				"cost_lines",
				{"cost_component": "Other", "currency": "USD", "amount": 20, "include_in_landed_cost": 1},
			)
		elif c_letter == "B":
			cont.append(
				"cost_lines",
				{"cost_component": "Freight", "currency": "USD", "amount": 150, "include_in_landed_cost": 1},
			)
			cont.append(
				"cost_lines",
				{"cost_component": "Other", "currency": "EUR", "amount": 50, "include_in_landed_cost": 1},
			)
		cont.insert(ignore_permissions=True)

		if c_letter == "A":
			for row in cont.cost_lines:
				if row.amount == 20:
					frappe.db.set_value("Container Cost Line", row.name, "cost_component", "VAT")

	# Setup GRN Checklist (leave as Draft in seed)
	from stabler.stabler.imports_module.packing_service import create_or_get_grn

	grn_name = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci_name})
	if not grn_name:
		grn_name = create_or_get_grn(ci, ignore_permissions=True)

	grn = frappe.get_doc("GRN Checklist", grn_name)
	grn.completion_date = today
	grn.warehouse = warehouse_full
	grn.save(ignore_permissions=True)

	# Create Import Truck and Truck Receipt
	truck_num = f"UAT-TRUCK{DEMO_SUFFIX}"
	tr = frappe.new_doc("Import Truck")
	tr.truck_number = truck_num
	tr.commercial_invoice = ci_name
	tr.company = company
	tr.status = "ARRIVED"
	tr.insert(ignore_permissions=True)
	truck_name = tr.name

	trec = frappe.new_doc("Truck Receipt")
	trec.truck = truck_name
	trec.grn_checklist = grn_name
	trec.company = company
	trec.arrival_date = today
	trec.append(
		"items",
		{
			"grn_item_code": item_code,
			"received_boxes": 100,
			"received_kg": 1000,
			"condition": "Good",
		},
	)
	trec.insert(ignore_permissions=True)
	trec.submit()

	# Create Vet Certificate
	vet = frappe.new_doc("Vet Certificate")
	vet.commercial_invoice = ci.name
	vet.company = company
	vet.certificate_number = f"UAT-VET{DEMO_SUFFIX}"
	vet.status = "Approved"
	vet.expiry_date = frappe.utils.add_days(today, 30)
	vet.insert(ignore_permissions=True)
	vet.submit()

	# Create Purchase Invoice (to link via set_bill_import_refs in S4)
	pi_bill_no = f"UAT-PI{DEMO_SUFFIX}"
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = company
	pi.supplier = carrier_name
	pi.currency = "USD"
	pi.conversion_rate = 12500
	pi.bill_no = pi_bill_no
	pi.posting_date = today
	acc = frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0})
	pi.append(
		"items",
		{
			"expense_account": acc,
			"item_name": "Import Service",
			"uom": "Nos",
			"qty": 1,
			"rate": 150,
			"amount": 150,
		},
	)
	pi.insert(ignore_permissions=True)

	frappe.db.commit()
	print("Seed complete.")


def unseed():
	_guard()

	unseed_errors = []

	def _cancel(doctype, name):
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		if getattr(doc, "docstatus", 0) == 1:
			try:
				doc.cancel()
			except Exception as e:
				unseed_errors.append(f"Could not cancel {doctype} {name}: {e}")

	def _delete(doctype, name):
		if not frappe.db.exists(doctype, name):
			return
		try:
			frappe.delete_doc(doctype, name, ignore_permissions=True)
		except Exception as e:
			unseed_errors.append(f"Could not delete {doctype} {name}: {e}")

	# Gather UAT documents using suffix or item links to make it robust against partial deletion
	ci_names = frappe.get_all(
		"Commercial Invoice", filters={"ci_number": ["like", f"%{DEMO_SUFFIX}%"]}, pluck="name"
	)
	company = None
	if ci_names:
		company = frappe.db.get_value("Commercial Invoice", ci_names[0], "company")
	if not company:
		company = frappe.db.get_value("Warehouse", f"UAT Warehouse{DEMO_SUFFIX} - _TC", "company")
	if not company:
		company = "_Test Company"

	pi_names = frappe.get_all(
		"Purchase Invoice", filters={"bill_no": ["like", f"%{DEMO_SUFFIX}%"]}, pluck="name"
	)

	# Find GRNs by warehouse
	grn_names = frappe.get_all(
		"GRN Checklist", filters={"warehouse": f"UAT Warehouse{DEMO_SUFFIX} - _TC"}, pluck="name"
	)

	# Find TRs by grn_checklist or by item
	tr_names = []
	if grn_names:
		tr_names = frappe.get_all("Truck Receipt", filters={"grn_checklist": ["in", grn_names]}, pluck="name")
	tr_items = frappe.get_all(
		"Truck Receipt Item", filters={"grn_item_code": f"UAT Item{DEMO_SUFFIX}"}, pluck="parent"
	)
	tr_names = list(set(tr_names + tr_items))

	pr_names = []
	for tr_name in tr_names:
		pr = frappe.db.get_value("Truck Receipt", tr_name, "purchase_receipt")
		if pr:
			pr_names.append(pr)
	pr_items = frappe.get_all(
		"Purchase Receipt Item", filters={"item_code": f"UAT Item{DEMO_SUFFIX}"}, pluck="parent"
	)
	pr_names = list(set(pr_names + pr_items))

	lcv_names = []
	if pr_names:
		lcv_names = frappe.get_all(
			"Landed Cost Purchase Receipt", filters={"receipt_document": ["in", pr_names]}, pluck="parent"
		)
		lcv_names = list(set(lcv_names))

	container_names = frappe.get_all(
		"Import Container", filters={"container_number": ["like", f"%{DEMO_SUFFIX}%"]}, pluck="name"
	)
	import_truck_names = frappe.get_all(
		"Import Truck", filters={"truck_number": ["like", f"%{DEMO_SUFFIX}%"]}, pluck="name"
	)
	vet_names = frappe.get_all(
		"Vet Certificate", filters={"certificate_number": ["like", f"%{DEMO_SUFFIX}%"]}, pluck="name"
	)
	gtd_names = frappe.get_all(
		"Customs Declaration", filters={"commercial_invoice": ["in", ci_names]}, pluck="name"
	)

	# Unlink Purchase Receipt from Truck Receipt to break circular dependency
	for tr in tr_names:
		try:
			frappe.db.set_value("Truck Receipt", tr, "purchase_receipt", None)
		except Exception as e:
			unseed_errors.append(f"Could not unlink PR from TR {tr}: {e}")

	# Delete LCVs first to avoid vouchered check during unlinking / cancellation
	for lcv in lcv_names:
		_delete("Landed Cost Voucher", lcv)

	# Break any links from Purchase Invoice / Purchase Invoice Item to Import Container
	for dt in ["Purchase Invoice", "Purchase Invoice Item"]:
		try:
			meta = frappe.get_meta(dt)
			link_fields = [
				f.fieldname for f in meta.fields if f.fieldtype == "Link" and f.options == "Import Container"
			]
			for field in link_fields:
				for pi in pi_names:
					try:
						if dt == "Purchase Invoice":
							frappe.db.set_value(dt, pi, field, None)
						else:
							rows = frappe.get_all(
								"Purchase Invoice Item", filters={"parent": pi}, pluck="name"
							)
							for row_name in rows:
								frappe.db.set_value("Purchase Invoice Item", row_name, field, None)
					except Exception as e:
						unseed_errors.append(f"Could not clear link {field} on {dt} for PI {pi}: {e}")
		except Exception as e:
			unseed_errors.append(f"Could not break links from {dt} to Import Container: {e}")

	# Break any links from Import Container / Container Cost Line to Purchase Invoice
	for dt in ["Import Container", "Container Cost Line"]:
		try:
			meta = frappe.get_meta(dt)
			link_fields = [
				f.fieldname for f in meta.fields if f.fieldtype == "Link" and f.options == "Purchase Invoice"
			]
			for field in link_fields:
				for container in container_names:
					try:
						if dt == "Import Container":
							frappe.db.set_value(dt, container, field, None)
						else:
							rows = frappe.get_all(
								"Container Cost Line", filters={"parent": container}, pluck="name"
							)
							for row_name in rows:
								frappe.db.set_value("Container Cost Line", row_name, field, None)
					except Exception as e:
						unseed_errors.append(
							f"Could not clear link {field} on {dt} for Container {container}: {e}"
						)
		except Exception as e:
			unseed_errors.append(f"Could not break links from {dt} to Purchase Invoice: {e}")

	# Unlink Purchase Invoices
	from stabler.api.imports import clear_bill_import_refs

	for pi in pi_names:
		try:
			clear_bill_import_refs(pi)
		except Exception as e:
			if "not linked" not in str(e).lower():
				unseed_errors.append(f"Could not unlink PI {pi}: {e}")

	# Unlink Landed Cost Vouchers from GRN Checklist
	for lcv in lcv_names:
		grns = frappe.get_all("GRN LCV Ref", filters={"lcv": lcv}, pluck="parent")
		for grn_name in set(grns):
			try:
				grn_doc = frappe.get_doc("GRN Checklist", grn_name)
				grn_doc.landed_cost_vouchers = [row for row in grn_doc.landed_cost_vouchers if row.lcv != lcv]
				grn_doc.flags.ignore_validate_update_after_submit = True
				grn_doc.save(ignore_permissions=True)
			except Exception as e:
				unseed_errors.append(f"Could not unlink LCV {lcv} from GRN {grn_name}: {e}")

	# Clear lcv_ref on Container Cost Lines
	for lcv in lcv_names:
		try:
			frappe.db.set_value("Container Cost Line", {"lcv_ref": lcv}, "lcv_ref", "")
		except Exception as e:
			unseed_errors.append(f"Could not clear lcv_ref for LCV {lcv}: {e}")

	# Cancel Purchase Invoices
	for pi in pi_names:
		_cancel("Purchase Invoice", pi)

	# Cancel Purchase Receipts (PRs must be cancelled before Truck Receipts)
	for pr in pr_names:
		_cancel("Purchase Receipt", pr)

	# Cancel Truck Receipts
	for tr in tr_names:
		_cancel("Truck Receipt", tr)

	# Cancel Vet Certificates
	for vet in vet_names:
		_cancel("Vet Certificate", vet)

	# Cancel GRN Checklists
	for grn in grn_names:
		_cancel("GRN Checklist", grn)

	# Cancel Commercial Invoices
	for ci in ci_names:
		_cancel("Commercial Invoice", ci)

	# Delete GL Entries and Stock Ledger Entries
	vouchers = list(set(pi_names + pr_names + tr_names + grn_names + ci_names))
	if vouchers:
		gle_names = frappe.get_all("GL Entry", filters={"voucher_no": ["in", vouchers]}, pluck="name")
		for gle in gle_names:
			_delete("GL Entry", gle)
		sle_names = frappe.get_all(
			"Stock Ledger Entry", filters={"voucher_no": ["in", vouchers]}, pluck="name"
		)
		for sle in sle_names:
			_delete("Stock Ledger Entry", sle)

	# Cancel and Delete Repost Item Valuation documents linking to UAT items
	reposts = frappe.get_all(
		"Repost Item Valuation", filters={"item_code": f"UAT Item{DEMO_SUFFIX}"}, pluck="name"
	)
	for r in reposts:
		try:
			frappe.db.set_value("Repost Item Valuation", r, "status", "Failed")
		except Exception:
			pass
		_cancel("Repost Item Valuation", r)
		_delete("Repost Item Valuation", r)

	# Delete LCVs again (in case any were missed or not UAT-linked initially)
	for lcv in lcv_names:
		_delete("Landed Cost Voucher", lcv)

	# Delete PIs
	for pi in pi_names:
		_delete("Purchase Invoice", pi)

	# Delete PRs
	for pr in pr_names:
		_delete("Purchase Receipt", pr)

	# Delete TRs
	for tr in tr_names:
		_delete("Truck Receipt", tr)

	# Delete Vet Certificates
	for vet in vet_names:
		_delete("Vet Certificate", vet)

	# Delete Customs Declarations
	for gtd in gtd_names:
		_delete("Customs Declaration", gtd)

	# Delete GRN Checklists
	for grn in grn_names:
		_delete("GRN Checklist", grn)

	# Delete Import Trucks
	for it in import_truck_names:
		_delete("Import Truck", it)

	# Delete Import Containers
	for ic in container_names:
		_delete("Import Container", ic)

	# Delete Commercial Invoices
	for ci in ci_names:
		_delete("Commercial Invoice", ci)

	# Delete Bin records to unlink Warehouses and Items
	bins = frappe.get_all("Bin", filters={"item_code": f"UAT Item{DEMO_SUFFIX}"}, pluck="name")
	for bin_name in bins:
		_delete("Bin", bin_name)

	# Delete Item, Warehouse, Suppliers
	_delete("Item", f"UAT Item{DEMO_SUFFIX}")
	_delete("Warehouse", f"UAT Warehouse{DEMO_SUFFIX} - _TC")
	_delete("Supplier", f"UAT Carrier{DEMO_SUFFIX}")
	_delete("Supplier", f"UAT Vendor{DEMO_SUFFIX}")

	# Remove Company 2 from Stabler Settings modules first before deleting Company
	company2 = f"UAT Company 2{DEMO_SUFFIX}"
	try:
		settings = frappe.get_doc("Stabler Settings")
		settings.company_modules = [row for row in settings.company_modules if row.company != company2]
		settings.save(ignore_permissions=True)
		frappe.clear_cache()
	except Exception as e:
		unseed_errors.append(f"Could not remove company2 from settings modules: {e}")

	# Delete UAT Company 2
	_delete("Company", company2)

	# Restore Settings
	# The Note is the only record of which Currency Exchanges this seed inserted, and it is
	# deleted below — so capture that list here, before the delete, for the cleanup further down.
	inserted_cxs = []
	notes = frappe.get_all("Note", filters={"title": f"old_settings{DEMO_SUFFIX}"})
	if notes:
		note = frappe.get_doc("Note", notes[0].name)
		try:
			data = json.loads(note.content)
			inserted_cxs = data.get("inserted_cxs") or []
			old_lcv = data.get("old_lcv")
			old_transport = data.get("old_transport")
			old_ci = data.get("old_ci")

			# If the old value was a UAT account itself (loop protection), clear it
			if old_lcv and DEMO_SUFFIX in old_lcv:
				old_lcv = None

			frappe.db.set_single_value("Stabler Settings", "imports_lcv_expense_account", old_lcv or None)

			settings = frappe.get_doc("Stabler Settings")
			for row in settings.get("imports_settings") or []:
				if row.company == company:
					row.imports_transport_supplier_groups = old_transport
					row.ci_supplier_groups = old_ci
					break
			settings.save(ignore_permissions=True)
			frappe.clear_cache()
		except Exception as e:
			unseed_errors.append(f"Could not restore settings: {e}")
		_delete("Note", note.name)

	# Explicitly clear Stabler Settings link if it points to UAT account before deleting
	if (
		frappe.db.get_single_value("Stabler Settings", "imports_lcv_expense_account")
		== f"UAT LCV Expense{DEMO_SUFFIX} - _TC"
	):
		frappe.db.set_single_value("Stabler Settings", "imports_lcv_expense_account", None)
		frappe.clear_cache()

	# Delete Accounts
	_delete("Account", f"UAT LCV Expense{DEMO_SUFFIX} - _TC")
	_delete("Account", f"UAT Creditors USD{DEMO_SUFFIX} - _TC")
	_delete("Account", f"UAT Creditors EUR{DEMO_SUFFIX} - _TC")

	# Delete only the Currency Exchanges this seed actually inserted, addressed by name.
	# Filtering on exchange_rate instead would match any document on the site carrying one
	# of those rates, including data the UAT never created.
	for cx in inserted_cxs:
		if frappe.db.exists("Currency Exchange", cx):
			_delete("Currency Exchange", cx)

	frappe.db.commit()

	if unseed_errors:
		raise Exception("Unseed failed with the following errors:\n" + "\n".join(unseed_errors))
	else:
		print("Unseed complete.")
