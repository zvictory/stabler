"""Record the landed cost distribution basis on the documents a voucher is built from.

Before this, every Landed Cost Voucher Stabler built was hardcoded to "Qty".
Stock UOM is Kg at conversion factor 1, so that spreads charges by weight —
correct for freight, wrong for the ad-valorem charges (customs duty, excise,
insurance, bank fees) that dominate this landed cost, where cheap-heavy items
absorb far more than they are worth.

The field records the operator's choice per document so a voucher's basis is a
decision on the record instead of a constant in the source.

Deliberately no backfill: existing documents stay empty. A historical voucher was
distributed on whatever basis it was submitted with, and that voucher — not a
value written onto the source document afterwards — is the record of it. The
review endpoint reads the frozen basis back off the submitted voucher itself.
"""

import frappe

FIELDNAME = "custom_landed_cost_distribution"

#: Both source doctypes a landed cost review runs on. Purchase Receipt is the
#: Tender / general purchasing flow; GRN Checklist is the imports flow.
DOCTYPES = ("GRN Checklist", "Purchase Receipt")


def execute():
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": FIELDNAME}):
			continue

		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": doctype,
				"fieldname": FIELDNAME,
				"label": "Landed Cost Distribution",
				"fieldtype": "Select",
				# Leading blank option on purpose: the field has no default, and
				# "nothing chosen yet" has to stay distinguishable from a chosen
				# "Qty". Without it, opening the document in the Desk and saving
				# would silently persist the first option.
				"options": "\nQty\nAmount",
				# ERPNext also accepts "Distribute Manually", which is not offered:
				# it refuses to submit such a voucher with more than one charge row
				# (``landed_cost_voucher.py`` ``on_submit``), and a build here
				# routinely carries several.
				"description": (
					"How the next Landed Cost Voucher spreads its charges. Qty is by weight "
					"(stock UOM is Kg), Amount is by item value. Set from the Landed Cost "
					"Review screen; frozen once a voucher is submitted."
				),
				# Written through the API after the document is submitted — a
				# voucher only ever exists for a submitted receipt.
				"allow_on_submit": 1,
				"read_only": 1,
				"no_copy": 1,
			}
		).insert(ignore_permissions=True)
