"""Add a durable Proforma Invoice link to supplier advance Payment Entries.

Re-runnable. The backfill selects only payments whose link is still empty, so a
second run converts nothing it has already converted — the property that matters
because the second run is not hypothetical: `16328bf` records a site whose Patch
Log claimed all 94 patches while 206 Custom Fields were missing, and the repair
was to run modules by hand.

Without that bound the scan re-selected every payment it had ever converted, plus
every supplier advance created since — `imports_module/hooks.py:50-62` still
keeps `Proforma Invoice` a valid reference doctype for a supplier, so a
hand-built advance can be sitting in exactly the legacy shape today. For a draft
the patch then stripped its reference rows and saved it: an advance in progress
lost its Proforma relationship, `unallocated_amount` was recomputed, and if it
was submitted afterwards the money sat in the ledger with nothing pointing back.
"""

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
	# Only payments that have not been converted yet are work. A child-table
	# `get_all` cannot filter on a parent field, hence the join.
	legacy_rows = frappe.db.sql(
		"""
		SELECT per.parent AS parent, per.reference_name AS reference_name
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Proforma Invoice'
		  AND COALESCE(pe.custom_proforma_invoice, '') = ''
		""",
		as_dict=True,
	)
	proformas_by_payment: dict[str, set[str]] = {}
	for row in legacy_rows:
		proformas_by_payment.setdefault(row["parent"], set()).add(row["reference_name"])
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
