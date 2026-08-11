"""Add a durable Proforma Invoice link to supplier advance Payment Entries."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute() -> None:
	fieldname = "custom_proforma_invoice"
	if not frappe.db.exists("Custom Field", f"Payment Entry-{fieldname}"):
		create_custom_field(
			"Payment Entry",
			{
				"fieldname": fieldname,
				"label": "Proforma Invoice",
				"fieldtype": "Link",
				"options": "Proforma Invoice",
				"insert_after": "custom_import_container",
				"read_only": 1,
				"description": "Import traceability — the PI whose supplier advance this payment funds.",
			},
		)
	frappe.clear_cache(doctype="Payment Entry")
	legacy_rows = frappe.get_all(
		"Payment Entry Reference",
		filters={"reference_doctype": "Proforma Invoice"},
		fields=["parent", "reference_name"],
	)
	proformas_by_payment: dict[str, set[str]] = {}
	for row in legacy_rows:
		proformas_by_payment.setdefault(row.parent, set()).add(row.reference_name)
	for payment_entry, proformas in proformas_by_payment.items():
		# The Stabler UI creates one PE per PI/stream. Do not guess when an old
		# manually-created entry references several PIs.
		if len(proformas) != 1:
			continue
		proforma = next(iter(proformas))
		frappe.db.set_value("Payment Entry", payment_entry, fieldname, proforma, update_modified=False)
		if frappe.db.get_value("Payment Entry", payment_entry, "docstatus") != 0:
			continue
		# Drafts have no ledger impact, so they can be converted in place to the
		# new unallocated-advance model. Submitted legacy entries keep their audit
		# trail and require Accounts to cancel/amend them deliberately.
		doc = frappe.get_doc("Payment Entry", payment_entry)
		doc.set(
			"references",
			[row for row in (doc.get("references") or []) if row.reference_doctype != "Proforma Invoice"],
		)
		doc.save(ignore_permissions=True)
	frappe.db.commit()
