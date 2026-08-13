"""UAT Harness script to execute scenarios and collect evidence."""

from __future__ import annotations

import datetime
import json
import traceback

import frappe
from frappe.utils import add_days, nowdate

DEMO_SUFFIX = " [UAT]"


def _get_ci():
	cis = frappe.get_all("Commercial Invoice", filters={"ci_number": f"UAT-CI{DEMO_SUFFIX}"}, pluck="name")
	if not cis:
		frappe.throw("UAT CI not found. Run seed() first.")
	return cis[0]


def run():
	ci_name = _get_ci()
	ci = frappe.get_doc("Commercial Invoice", ci_name)
	company = ci.company
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"

	grn_name = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci_name})
	containers = frappe.get_all("Import Container", filters={"commercial_invoice": ci_name}, pluck="name")

	timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
	evidence_filename = f"imports-uat-{timestamp}.json"
	# Determine private files folder
	private_files_dir = frappe.get_site_path("private", "files")
	import os

	if not os.path.exists(private_files_dir):
		os.makedirs(private_files_dir)
	evidence_path = os.path.join(private_files_dir, evidence_filename)

	evidence = {
		"site": getattr(frappe.local, "site", "genesis-test.local"),
		"company": company,
		"company_currency": company_currency,
		"seeded": {"commercial_invoice": ci_name, "grn": grn_name, "containers": containers},
		"scenarios": [],
	}

	note_name = frappe.db.get_value("Note", {"title": f"old_settings{DEMO_SUFFIX}"})
	created_cxs = []
	if note_name:
		note = frappe.get_doc("Note", note_name)
		try:
			data = json.loads(note.content)
			created_cxs = data.get("created_cxs") or []
		except Exception:
			pass

	# Helper to find container A & B names
	container_a_name = None
	container_b_name = None
	for c in containers:
		num = frappe.db.get_value("Import Container", c, "container_number")
		if "CONT-A" in num:
			container_a_name = c
		elif "CONT-B" in num:
			container_b_name = c

	# Scenario S1
	s1_dict = {
		"id": "S1",
		"observed": {},
		"documents": [ci_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	try:
		# Locate the USD Currency Exchange from created_cxs
		usd_cx_name = None
		for cx_name in created_cxs:
			exists = frappe.db.exists("Currency Exchange", cx_name)
			if exists:
				from_cur, to_cur = frappe.db.get_value(
					"Currency Exchange", cx_name, ["from_currency", "to_currency"]
				) or (None, None)
				if from_cur == "USD" and to_cur == "UZS":
					usd_cx_name = cx_name
					break
		if not usd_cx_name:
			usd_cx_name = frappe.db.get_value(
				"Currency Exchange", {"from_currency": "USD", "to_currency": "UZS", "exchange_rate": 12500}
			)

		rate_before = (
			frappe.db.get_value("Currency Exchange", usd_cx_name, "exchange_rate") if usd_cx_name else None
		)
		s1_dict["amounts"].append(
			{
				"doctype": "Currency Exchange",
				"name": usd_cx_name or "None",
				"fieldname": "exchange_rate_before",
				"value": rate_before,
			}
		)

		cx_data = None
		if usd_cx_name:
			usd_cx_doc = frappe.get_doc("Currency Exchange", usd_cx_name)
			cx_data = usd_cx_doc.as_dict()
			frappe.delete_doc("Currency Exchange", usd_cx_name, ignore_permissions=True)
			frappe.clear_cache()

		try:
			from stabler.api.imports import calculate_ci_landed_cost_uzs

			res = calculate_ci_landed_cost_uzs(ci_name)

			s1_dict["observed"] = {
				"rate_source": res.get("rate_source"),
				"items_count": len(res.get("items") or []),
			}
			s1_dict["amounts"].append(
				{
					"doctype": "Commercial Invoice",
					"name": ci_name,
					"fieldname": "total_landed_uzs_during_missing",
					"value": res.get("total_landed_uzs"),
				}
			)
		finally:
			if usd_cx_name and cx_data:
				if not frappe.db.exists("Currency Exchange", usd_cx_name):
					new_cx = frappe.new_doc("Currency Exchange")
					new_cx.update(cx_data)
					new_cx.name = usd_cx_name
					new_cx.insert(ignore_permissions=True)
					frappe.clear_cache()

		rate_after = (
			frappe.db.get_value("Currency Exchange", usd_cx_name, "exchange_rate") if usd_cx_name else None
		)
		s1_dict["amounts"].append(
			{
				"doctype": "Currency Exchange",
				"name": usd_cx_name or "None",
				"fieldname": "exchange_rate_after",
				"value": rate_after,
			}
		)

	except Exception:
		s1_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s1_dict)

	# Scenario S2
	s2_dict = {
		"id": "S2",
		"observed": {},
		"documents": [ci_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	try:
		# Add Currency Exchange USD->UZS (ensure we delete any existing UAT USD CX to avoid name duplicates)
		existing_cx = frappe.db.get_value(
			"Currency Exchange", {"date": ci.ci_date, "from_currency": "USD", "to_currency": "UZS"}
		)
		if existing_cx:
			frappe.delete_doc("Currency Exchange", existing_cx, ignore_permissions=True)
			frappe.clear_cache()

		cx = frappe.new_doc("Currency Exchange")
		cx.date = ci.ci_date
		cx.from_currency = "USD"
		cx.to_currency = "UZS"
		cx.exchange_rate = 12500
		cx.for_buying = 1
		cx.for_selling = 1
		cx.insert(ignore_permissions=True)
		cx_name = cx.name
		s2_dict["documents"].append(cx_name)

		from stabler.api.imports import calculate_ci_landed_cost_uzs

		res = calculate_ci_landed_cost_uzs(ci_name)

		s2_dict["observed"] = {"rate_source": res.get("rate_source"), "rate_date": str(res.get("rate_date"))}
		s2_dict["amounts"].append(
			{"doctype": "Currency Exchange", "name": cx_name, "fieldname": "exchange_rate", "value": 12500.0}
		)
		s2_dict["amounts"].append(
			{
				"doctype": "Commercial Invoice",
				"name": ci_name,
				"fieldname": "total_landed_uzs",
				"value": res.get("total_landed_uzs"),
			}
		)
	except Exception:
		s2_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s2_dict)

	# Scenario S3
	s3_dict = {
		"id": "S3",
		"observed": {},
		"documents": [grn_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	lcv_name = None
	try:
		# S6 proves that a cost line whose currency has no rate stays out of the first LCV and is
		# capitalized later, once the rate exists. That premise requires the EUR rate to be absent
		# while this first LCV is built, so remove the one seed() inserted — by document lifecycle
		# and addressed by its own currencies/date, never by a rate-value sweep. S6 re-inserts it;
		# Currency Exchange autonames deterministically, so the replacement carries the same name
		# and unseed()'s by-name cleanup still finds it.
		seeded_cx_eur = frappe.db.get_value(
			"Currency Exchange", {"date": ci.ci_date, "from_currency": "EUR", "to_currency": "UZS"}
		)
		if seeded_cx_eur:
			frappe.delete_doc("Currency Exchange", seeded_cx_eur, ignore_permissions=True)
			frappe.clear_cache()

		# Mock enqueue to prevent background LCV creation during GRN submit
		original_enqueue = frappe.enqueue
		frappe.enqueue = lambda *a, **kw: None
		try:
			grn = frappe.get_doc("GRN Checklist", grn_name)
			if grn.docstatus == 0:
				grn.submit()
		finally:
			frappe.enqueue = original_enqueue

		# Call create_additional_lcv manually
		from stabler.api.imports import create_additional_lcv

		lcv_res = create_additional_lcv(grn_name)
		lcv_name = lcv_res["lcv"]
		s3_dict["documents"].append(lcv_name)

		lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)

		# Collect taxes row info
		taxes_list = []
		for tax in lcv.taxes:
			taxes_list.append({"description": tax.description, "expense_account": tax.expense_account})
			s3_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": tax.name,
					"fieldname": "amount",
					"value": tax.amount,
				}
			)

		# Collect Container Cost Lines lcv_ref
		ccl_refs = []
		if container_a_name:
			cont_a = frappe.get_doc("Import Container", container_a_name)
			for row in cont_a.cost_lines:
				ccl_refs.append(
					{"name": row.name, "cost_component": row.cost_component, "lcv_ref": row.lcv_ref}
				)
				s3_dict["amounts"].append(
					{
						"doctype": "Container Cost Line",
						"name": row.name,
						"fieldname": "amount",
						"value": row.amount,
					}
				)

		s3_dict["observed"] = {
			"lcv_name": lcv_name,
			"taxes": taxes_list,
			"lcv_currency": company_currency,
			"container_a_cost_lines": ccl_refs,
		}
		s3_dict["amounts"].append(
			{
				"doctype": "Landed Cost Voucher",
				"name": lcv_name,
				"fieldname": "total_taxes_and_charges",
				"value": lcv.total_taxes_and_charges,
			}
		)
	except Exception:
		s3_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s3_dict)

	# Scenario S4 (Exactly-Once Proof)
	lcv2_name = None
	s4_dict = {"id": "S4", "observed": {}, "documents": [], "amounts": [], "warnings": [], "error": None}
	try:
		pi_bill_no = f"UAT-PI{DEMO_SUFFIX}"
		pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": pi_bill_no})
		s4_dict["documents"].append(pi_name)

		# Link PI to Container B
		from stabler.api.imports import set_bill_import_refs

		set_bill_import_refs(purchase_invoice=pi_name, import_container=container_b_name)

		# Retrieve warnings from supersede_billed call indirectly by checking LCV logs or re-running logic
		# Actually, we can run create_additional_lcv, which calls supersede_billed and writes warnings to logs.
		# To capture the warnings dynamically, we can inspect cost lines and run the check
		from stabler.api.imports import create_additional_lcv

		lcv2_res = create_additional_lcv(grn_name)
		lcv2_name = lcv2_res["lcv"]
		s4_dict["documents"].append(lcv2_name)

		# Load billed cost line by querying purchase_invoice across all containers
		billed_ccl_names = frappe.get_all(
			"Container Cost Line", filters={"purchase_invoice": pi_name}, pluck="name"
		)
		billed_ccl = frappe.get_doc("Container Cost Line", billed_ccl_names[0]) if billed_ccl_names else None

		# Load hand-entered cost line on Container B (Freight)
		hand_entered_ccl_names = frappe.get_all(
			"Container Cost Line",
			filters={
				"parent": container_b_name,
				"cost_component": "Freight",
				"purchase_invoice": ["is", "not set"],
			},
			pluck="name",
		)
		hand_entered_ccl = (
			frappe.get_doc("Container Cost Line", hand_entered_ccl_names[0])
			if hand_entered_ccl_names
			else None
		)

		# Re-run supersede_billed to collect the exact warning message
		from stabler.stabler.imports_module import lcv_math
		from stabler.stabler.imports_module.hooks import _collect_cost_lines

		cost_lines = _collect_cost_lines(ci_name)
		_, bill_warnings = lcv_math.supersede_billed(cost_lines)
		s4_dict["warnings"] = bill_warnings

		# The LCV tax row description is written from the cost line's own cost_component
		# (see build_lcv_payload in stabler/stabler/imports_module/lcv_math.py), which is
		# derived for a billed line and is NOT necessarily the component a human typed on
		# the hand-entered line. Look the row up by that component, never by a literal.
		billed_component = billed_ccl.cost_component if billed_ccl else None

		# Find the target LCV where the cost line is vouchered
		target_lcv_name = billed_ccl.lcv_ref if (billed_ccl and billed_ccl.lcv_ref) else None
		target_lcv_source = "billed_cost_line.lcv_ref" if target_lcv_name else "create_additional_lcv"
		if not target_lcv_name:
			target_lcv_name = lcv2_name

		# Find the tax row carrying the billed line's own cost component in that LCV
		billed_tax_row = None
		if target_lcv_name and billed_component:
			target_lcv_doc = frappe.get_doc("Landed Cost Voucher", target_lcv_name)
			for tax in target_lcv_doc.taxes:
				if tax.description == billed_component:
					billed_tax_row = tax
					break

		# Counts for the exactly-once proof
		count_ccl = len(frappe.get_all("Container Cost Line", filters={"purchase_invoice": pi_name}))

		# Count tax rows across every LCV linked to this GRN that carry the billed
		# line's component and amount — more than one means the money was capitalized twice.
		all_lcv_names = frappe.get_all(
			"Landed Cost Purchase Receipt",
			filters={
				"receipt_document": [
					"in",
					frappe.get_all(
						"Truck Receipt", filters={"grn_checklist": grn_name}, pluck="purchase_receipt"
					),
				]
			},
			pluck="parent",
		)
		all_lcv_names = list(set(all_lcv_names))

		count_lcv_tax = None
		if billed_tax_row:
			if all_lcv_names:
				count_lcv_tax = len(
					frappe.get_all(
						"Landed Cost Taxes and Charges",
						filters={
							"parent": ["in", all_lcv_names],
							"description": billed_component,
							"amount": billed_tax_row.amount,
						},
					)
				)
		elif not billed_ccl:
			# Explicitly record the lookup failure — never substitute a placeholder
			s4_dict["observed"]["tax_row_lookup_failure"] = (
				f"No Container Cost Line carries purchase_invoice '{pi_name}', so no cost component was available to look up."
			)
		else:
			s4_dict["observed"]["tax_row_lookup_failure"] = (
				f"No Landed Cost Taxes and Charges row with description '{billed_component}' "
				f"(the billed cost line's own cost_component) in target LCV '{target_lcv_name}'."
			)

		s4_dict["observed"].update(
			{
				"lcv2_name": lcv2_name,
				"target_lcv_name": target_lcv_name,
				"target_lcv_source": target_lcv_source,
				"billed_cost_component": billed_component,
				"billed_ccl_lcv_ref": billed_ccl.lcv_ref if billed_ccl else None,
				"hand_entered_b_freight_component": hand_entered_ccl.cost_component
				if hand_entered_ccl
				else None,
				"hand_entered_b_freight_lcv_ref": hand_entered_ccl.lcv_ref if hand_entered_ccl else None,
			}
		)

		pi_net_total = frappe.db.get_value("Purchase Invoice", pi_name, "net_total")
		s4_dict["amounts"].append(
			{"doctype": "Purchase Invoice", "name": pi_name, "fieldname": "net_total", "value": pi_net_total}
		)
		if billed_tax_row:
			s4_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": billed_tax_row.name,
					"fieldname": "amount",
					"value": billed_tax_row.amount,
				}
			)
		if hand_entered_ccl:
			s4_dict["amounts"].append(
				{
					"doctype": "Container Cost Line",
					"name": hand_entered_ccl.name,
					"fieldname": "amount",
					"value": hand_entered_ccl.amount,
				}
			)
		if billed_ccl:
			s4_dict["amounts"].append(
				{
					"doctype": "Container Cost Line",
					"name": billed_ccl.name,
					"fieldname": "amount",
					"value": billed_ccl.amount,
				}
			)
		s4_dict["amounts"].append(
			{"doctype": "Container Cost Line", "name": "query", "fieldname": "count", "value": count_ccl}
		)
		if count_lcv_tax is not None:
			s4_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": "query",
					"fieldname": "count",
					"value": count_lcv_tax,
				}
			)
	except Exception:
		s4_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s4_dict)

	# Scenario S5
	s5_dict = {
		"id": "S5",
		"observed": {},
		"documents": [grn_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	try:
		from stabler.api.imports import create_additional_lcv

		# This should raise ValidationError: No unconsumed landed-cost lines to voucher.
		try:
			create_additional_lcv(grn_name)
			s5_dict["observed"]["returned_val"] = "success"
		except frappe.exceptions.ValidationError as ve:
			s5_dict["observed"]["returned_val"] = "ValidationError"
			s5_dict["observed"]["exception_msg"] = str(ve)

		# Get LCV draft count and grn.landed_cost_vouchers count
		grn_prs = frappe.get_all(
			"Truck Receipt", filters={"grn_checklist": grn_name}, pluck="purchase_receipt"
		)
		lcvs = []
		if grn_prs:
			lcvs = frappe.get_all(
				"Landed Cost Purchase Receipt", filters={"receipt_document": ["in", grn_prs]}, pluck="parent"
			)
			lcvs = list(set(lcvs))

		drafts = frappe.get_all("Landed Cost Voucher", filters={"name": ["in", lcvs], "docstatus": 0})
		grn_doc = frappe.get_doc("GRN Checklist", grn_name)

		s5_dict["observed"]["lcv_drafts_count"] = len(drafts)
		s5_dict["amounts"].append(
			{
				"doctype": "GRN Checklist",
				"name": grn_name,
				"fieldname": "landed_cost_vouchers_count",
				"value": len(grn_doc.landed_cost_vouchers),
			}
		)
	except Exception:
		s5_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s5_dict)

	# Scenario S6
	s6_dict = {
		"id": "S6",
		"observed": {},
		"documents": [grn_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	try:
		# Check if first LCV has EUR component (it shouldn't)
		first_lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		has_eur_in_first = any(
			tax.description == "Other" and tax.amount == 675000.0 for tax in first_lcv.taxes
		)

		# Find EUR Container Cost Line on Container B
		cont_b = frappe.get_doc("Import Container", container_b_name)
		eur_line = None
		for row in cont_b.cost_lines:
			if row.currency == "EUR":
				eur_line = row
				break

		s6_dict["observed"] = {
			"has_eur_in_first": has_eur_in_first,
			"eur_line_lcv_ref_before": eur_line.lcv_ref if eur_line else None,
		}

		# Add Currency Exchange EUR->UZS. Currency Exchange autonames deterministically from
		# date + currencies + purpose, and seed() already inserted an EUR->UZS rate on the same
		# date, so an unguarded insert collides. Delete first, exactly as S2 does for USD; the
		# replacement carries the identical name, so unseed()'s by-name cleanup still finds it.
		existing_cx_eur = frappe.db.get_value(
			"Currency Exchange", {"date": ci.ci_date, "from_currency": "EUR", "to_currency": "UZS"}
		)
		if existing_cx_eur:
			frappe.delete_doc("Currency Exchange", existing_cx_eur, ignore_permissions=True)
			frappe.clear_cache()

		cx_eur = frappe.new_doc("Currency Exchange")
		cx_eur.date = ci.ci_date
		cx_eur.from_currency = "EUR"
		cx_eur.to_currency = "UZS"
		cx_eur.exchange_rate = 13500
		cx_eur.for_buying = 1
		cx_eur.for_selling = 1
		cx_eur.insert(ignore_permissions=True)
		s6_dict["documents"].append(cx_eur.name)

		# Create LCV 3
		from stabler.api.imports import create_additional_lcv

		lcv3_res = create_additional_lcv(grn_name)
		lcv3_name = lcv3_res["lcv"]
		s6_dict["documents"].append(lcv3_name)

		lcv3 = frappe.get_doc("Landed Cost Voucher", lcv3_name)
		eur_tax_row = None
		for tax in lcv3.taxes:
			if tax.description == "Other":
				eur_tax_row = tax
				break

		s6_dict["observed"]["lcv3_name"] = lcv3_name

		s6_dict["amounts"].append(
			{
				"doctype": "Currency Exchange",
				"name": cx_eur.name,
				"fieldname": "exchange_rate",
				"value": 13500.0,
			}
		)
		if eur_line:
			s6_dict["amounts"].append(
				{
					"doctype": "Container Cost Line",
					"name": eur_line.name,
					"fieldname": "amount",
					"value": eur_line.amount,
				}
			)
		if eur_tax_row:
			s6_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": eur_tax_row.name,
					"fieldname": "amount",
					"value": eur_tax_row.amount,
				}
			)
	except Exception:
		s6_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s6_dict)

	# Scenario S7
	s7_dict = {
		"id": "S7",
		"observed": {},
		"documents": [lcv_name],
		"amounts": [],
		"warnings": [],
		"error": None,
	}
	try:
		# Check if VAT component is present in LCV 1
		first_lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		has_vat = any("vat" in str(tax.description or "").lower() for tax in first_lcv.taxes)

		# Find VAT cost line on Container A
		cont_a = frappe.get_doc("Import Container", container_a_name)
		vat_line = None
		for row in cont_a.cost_lines:
			if row.cost_component == "VAT":
				vat_line = row
				break

		s7_dict["observed"] = {
			"has_vat_in_lcv": has_vat,
			"vat_line_lcv_ref": vat_line.lcv_ref if vat_line else None,
		}
		if vat_line:
			s7_dict["amounts"].append(
				{
					"doctype": "Container Cost Line",
					"name": vat_line.name,
					"fieldname": "amount",
					"value": vat_line.amount,
				}
			)
	except Exception:
		s7_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s7_dict)

	# Scenario S8
	s8_dict = {"id": "S8", "observed": {}, "documents": [], "amounts": [], "warnings": [], "error": None}
	try:
		# Add a hand-entered customs duty cost line to Container A
		ccl = frappe.new_doc("Container Cost Line")
		ccl.parent = container_a_name
		ccl.parenttype = "Import Container"
		ccl.parentfield = "cost_lines"
		ccl.cost_component = "Uzbekistan Customs Duty"
		ccl.currency = "USD"
		ccl.amount = 10
		ccl.include_in_landed_cost = 1
		ccl.insert(ignore_permissions=True)
		gtd_ccl_name = ccl.name
		s8_dict["documents"].append(gtd_ccl_name)

		# Create Customs Declaration (cleared GTD)
		gtd = frappe.new_doc("Customs Declaration")
		gtd.commercial_invoice = ci_name
		gtd.company = company
		gtd.gtd_number = "26010/110726/1234567"
		gtd.status = "Draft"
		gtd.insert(ignore_permissions=True)
		gtd.status = "Submitted"
		gtd.save(ignore_permissions=True)
		gtd.status = "Approved"
		gtd.cleared_date = nowdate()
		gtd.duty_amount = 500000
		gtd.excise_amount = 200000
		gtd.vat_amount = 100000
		gtd.save(ignore_permissions=True)
		gtd_name = gtd.name
		s8_dict["documents"].append(gtd_name)

		# Create LCV 4
		from stabler.api.imports import create_additional_lcv

		lcv4_res = create_additional_lcv(grn_name)
		lcv4_name = lcv4_res["lcv"]
		s8_dict["documents"].append(lcv4_name)

		lcv4 = frappe.get_doc("Landed Cost Voucher", lcv4_name)

		# Find the LCV taxes rows for Uzbekistan Customs Duty and Excise
		duty_tax_row = None
		excise_tax_row = None
		for tax in lcv4.taxes:
			if tax.description == "Uzbekistan Customs Duty":
				duty_tax_row = tax
			elif tax.description == "Uzbekistan Excise":
				excise_tax_row = tax

		# Get hand-entered cost line after LCV4
		gtd_ccl = frappe.get_doc("Container Cost Line", gtd_ccl_name)

		s8_dict["observed"] = {"lcv4_name": lcv4_name, "gtd_ccl_lcv_ref": gtd_ccl.lcv_ref}
		s8_dict["amounts"].append(
			{
				"doctype": "Customs Declaration",
				"name": gtd_name,
				"fieldname": "duty_amount",
				"value": 500000.0,
			}
		)
		s8_dict["amounts"].append(
			{
				"doctype": "Customs Declaration",
				"name": gtd_name,
				"fieldname": "excise_amount",
				"value": 200000.0,
			}
		)
		if duty_tax_row:
			s8_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": duty_tax_row.name,
					"fieldname": "amount",
					"value": duty_tax_row.amount,
				}
			)
		if excise_tax_row:
			s8_dict["amounts"].append(
				{
					"doctype": "Landed Cost Taxes and Charges",
					"name": excise_tax_row.name,
					"fieldname": "amount",
					"value": excise_tax_row.amount,
				}
			)
	except Exception:
		s8_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s8_dict)

	# Scenario S9
	s9_dict = {"id": "S9", "observed": {}, "documents": [], "amounts": [], "warnings": [], "error": None}
	try:
		# Check review before unlinking
		from stabler.api.lcv import get_landed_cost_review

		review_before = get_landed_cost_review(document_type="GRN Checklist", document_name=grn_name)

		# Unlink PI
		pi_bill_no = f"UAT-PI{DEMO_SUFFIX}"
		pi_name = frappe.db.get_value(
			"Purchase Invoice",
			{"copy_bill_no": pi_bill_no}
			if hasattr(frappe.get_meta("Purchase Invoice"), "copy_bill_no")
			else {"bill_no": pi_bill_no},
		)
		if not pi_name:
			pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": pi_bill_no})
		s9_dict["documents"].append(pi_name)

		# To unlink, we must first delete the draft Landed Cost Voucher that consumed it
		if lcv2_name:
			# Unlink LCV from GRN Checklist child table first
			grns = frappe.get_all("GRN LCV Ref", filters={"lcv": lcv2_name}, pluck="parent")
			for gname in grns:
				gdoc = frappe.get_doc("GRN Checklist", gname)
				gdoc.landed_cost_vouchers = [row for row in gdoc.landed_cost_vouchers if row.lcv != lcv2_name]
				gdoc.flags.ignore_validate_update_after_submit = True
				gdoc.save(ignore_permissions=True)
			# Clear lcv_ref in container cost lines
			frappe.db.set_value("Container Cost Line", {"lcv_ref": lcv2_name}, "lcv_ref", "")
			# Delete Landed Cost Voucher
			frappe.delete_doc("Landed Cost Voucher", lcv2_name, ignore_permissions=True)

		from stabler.api.imports import clear_bill_import_refs

		clear_bill_import_refs(pi_name)

		review_after = get_landed_cost_review(document_type="GRN Checklist", document_name=grn_name)

		s9_dict["observed"] = {
			"before_components": review_before.get("preview", {}).get("components"),
			"before_warnings": review_before.get("preview", {}).get("warnings"),
			"after_components": review_after.get("preview", {}).get("components"),
			"after_warnings": review_after.get("preview", {}).get("warnings"),
		}
	except Exception:
		s9_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s9_dict)

	# Scenario S10
	s10_dict = {"id": "S10", "observed": {}, "documents": [], "amounts": [], "warnings": [], "error": None}
	try:
		# First call: Commercial Invoice for company2 (imports is disabled)
		ci2_number = f"UAT-CI2{DEMO_SUFFIX}"
		ci2_name = frappe.db.get_value("Commercial Invoice", {"ci_number": ci2_number})
		s10_dict["documents"].append(ci2_name)

		from stabler.api.imports import calculate_ci_landed_cost_uzs

		call1_error_type = ""
		call1_error_msg = ""
		try:
			calculate_ci_landed_cost_uzs(ci2_name)
		except Exception as e:
			call1_error_type = type(e).__name__
			call1_error_msg = str(e)

		# Second call: User has no permission (Guest / no Imports role)
		original_get_roles = frappe.get_roles
		frappe.get_roles = lambda *a, **kw: ["Guest"]

		call2_error_type = ""
		call2_error_msg = ""
		try:
			# CI1 belongs to _Test Company, which has imports = 1
			calculate_ci_landed_cost_uzs(ci_name)
		except Exception as e:
			call2_error_type = type(e).__name__
			call2_error_msg = str(e)
		finally:
			frappe.get_roles = original_get_roles

		s10_dict["observed"] = {
			"call1_error_type": call1_error_type,
			"call1_error_msg": call1_error_msg,
			"call2_error_type": call2_error_type,
			"call2_error_msg": call2_error_msg,
		}
	except Exception:
		s10_dict["error"] = traceback.format_exc()
	evidence["scenarios"].append(s10_dict)

	with open(evidence_path, "w") as f:
		json.dump(evidence, f, indent=2)

	print(f"Evidence written to {evidence_path}")
