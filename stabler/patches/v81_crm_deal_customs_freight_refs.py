"""Add custom_crm_deal Link fields to Customs Declaration, Freight Booking, and Import Container."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute() -> None:
	if not frappe.db.exists("DocType", "CRM Deal"):
		return

	fieldname = "custom_crm_deal"
	doctypes_and_after = [
		("Customs Declaration", "supplier"),
		("Freight Booking", "purchase_order"),
		("Import Container", "commercial_invoice"),
	]

	for dt, insert_after in doctypes_and_after:
		if frappe.db.exists("DocType", dt) and not frappe.db.exists(
			"Custom Field", {"dt": dt, "fieldname": fieldname}
		):
			create_custom_field(
				dt,
				{
					"fieldname": fieldname,
					"label": "CRM Deal",
					"fieldtype": "Link",
					"options": "CRM Deal",
					"insert_after": insert_after,
					"read_only": 0,
					"description": "Tender traceability — the CRM Deal (Tender) this operational document belongs to.",
				},
				ignore_validate=True,
			)
			frappe.clear_cache(doctype=dt)

	# Backfill custom_crm_deal from Purchase Order when available
	if frappe.db.has_column("Purchase Order", fieldname):
		for dt in ("Customs Declaration", "Freight Booking"):
			if frappe.db.exists("DocType", dt) and frappe.db.has_column(dt, "purchase_order"):
				rows = frappe.db.sql(
					f"""
					SELECT cd.name, po.custom_crm_deal
					FROM `tab{dt}` cd
					JOIN `tabPurchase Order` po ON cd.purchase_order = po.name
					WHERE (cd.custom_crm_deal IS NULL OR cd.custom_crm_deal = '')
					  AND po.custom_crm_deal IS NOT NULL AND po.custom_crm_deal != ''
					""",
					as_dict=True,
				)
				for r in rows:
					frappe.db.set_value(dt, r["name"], fieldname, r["custom_crm_deal"], update_modified=False)

		# Backfill Import Container custom_crm_deal from Commercial Invoice -> Proforma Invoice -> Deal (if columns exist)
		if (
			frappe.db.exists("DocType", "Import Container")
			and frappe.db.has_column("Import Container", "commercial_invoice")
			and frappe.db.exists("DocType", "Commercial Invoice Item")
			and frappe.db.has_column("Commercial Invoice Item", "custom_proforma_invoice")
			and frappe.db.exists("DocType", "Proforma Invoice")
			and frappe.db.has_column("Proforma Invoice", "custom_crm_deal")
		):
			ic_rows = frappe.db.sql(
				"""
				SELECT ic.name, pi.custom_crm_deal
				FROM `tabImport Container` ic
				JOIN `tabCommercial Invoice Item` cii ON cii.parent = ic.commercial_invoice
				JOIN `tabProforma Invoice` pi ON pi.name = cii.custom_proforma_invoice
				WHERE (ic.custom_crm_deal IS NULL OR ic.custom_crm_deal = '')
				  AND pi.custom_crm_deal IS NOT NULL AND pi.custom_crm_deal != ''
				GROUP BY ic.name
				""",
				as_dict=True,
			)
			for r in ic_rows:
				frappe.db.set_value(
					"Import Container", r["name"], fieldname, r["custom_crm_deal"], update_modified=False
				)

	# Seed default tender sources in CRM Lead Source if missing
	if frappe.db.exists("DocType", "CRM Lead Source"):
		for src in ("UZEX", "Direct", "Portal", "Other"):
			if not frappe.db.exists("CRM Lead Source", {"source_name": src}) and not frappe.db.exists(
				"CRM Lead Source", src
			):
				try:
					doc = frappe.new_doc("CRM Lead Source")
					doc.source_name = src
					doc.insert(ignore_permissions=True)
				except Exception:
					pass

	frappe.db.commit()
