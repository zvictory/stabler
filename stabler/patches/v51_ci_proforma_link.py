"""Reverse link Commercial Invoice → Proforma Invoice (WP-I2).

Proforma Invoice already carries ``commercial_invoice`` (native). This adds the
reverse ``custom_proforma_invoice`` on Commercial Invoice so the supersede flow
(PI CONFIRMED → CI issued → PI SUPERSEDED_BY_CI) is traceable both ways. Set by
automation (api.imports.link_proforma_to_ci), so read_only.

Guarded so it works even before the Proforma Invoice doctype exists on a site.
Listed under [post_model_sync]. Idempotent: sentinel Custom Field guard.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Commercial Invoice"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Commercial Invoice", "fieldname": "custom_proforma_invoice"}):
		return

	options = "Proforma Invoice" if frappe.db.exists("DocType", "Proforma Invoice") else "Data"
	fieldtype = "Link" if options == "Proforma Invoice" else "Data"
	after = "supplier" if frappe.db.has_column("Commercial Invoice", "supplier") else "company"

	create_custom_fields(
		{
			"Commercial Invoice": [
				{
					"fieldname": "custom_proforma_invoice",
					"label": "Proforma Invoice",
					"fieldtype": fieldtype,
					"options": options if fieldtype == "Link" else "",
					"insert_after": after,
					"read_only": 1,
					"description": "The proforma this CI superseded (set on link).",
				}
			]
		},
		ignore_validate=True,
	)
