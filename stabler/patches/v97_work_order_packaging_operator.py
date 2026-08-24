"""Split the Work Order operator into two roles: production and packaging.

v15 gave Work Order a single `operator` field, on the assumption that one order
belongs to one person. anjan's shop floor does not work that way: an order is
poured by one operator and packed by another — 11 pouring operators and 10
packaging operators across 5 departments and 9 lines, on the same order, in the
same shift. With one field, whoever is not named cannot open the order at all,
because `operator` is also the access gate every kiosk endpoint reads.

So `operator` keeps its fieldname and becomes the production role, and
`packaging_operator` joins it. The fieldname is deliberately NOT renamed:
`operator` is read by nine call sites and is what the running site already has
data in. Renaming it would be a data migration plus a rewrite of the IDOR guard,
to buy a better label. The label change buys the same clarity for free.

Both fields are optional and carry no `default`. That matters twice over: an
order created before this patch keeps working with a production operator and no
packaging operator, and a tenant that carries the Work Order doctype without
running a packaging step is unaffected — which is why this follows v53's
ungated shape rather than v94's `enable_manufacturing` gate. The gate in v94
exists because that patch puts columns in a *list view* grid on a doctype six of
seven tenants use for something else; two optional Link fields on Work Order are
invisible where nobody fills them.

Attribution is NOT part of this patch. Whether a given material line is the
pouring operator's or the packer's is a separate question, and it gets its
field when the code that reads it exists — not before. The prototype this work
came from added exactly that field early (`operatorTuri` in its material
catalogue), never wired it up, and derived the answer from the unit of measure
instead; the two disagree on 28% of its BOM lines. An unread field is not a
head start, it is a second source of truth waiting to be believed.

Idempotent: `create_custom_fields(update=True)` re-applies the same definition,
so a second run is a no-op on the column and a no-write on the label.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DOCTYPE = "Work Order"


def execute() -> None:
	# `has_column` raises TableMissingError rather than returning False when the
	# doctype's table is absent (.claude/rules/20-backend-migrations.md), so the
	# probe starts from `table_exists`. No erpnext, no Work Order, nothing to do.
	if not frappe.db.table_exists(DOCTYPE):
		return

	create_custom_fields(
		{
			DOCTYPE: [
				{
					"fieldname": "operator",
					"label": "Production operator",
					"fieldtype": "Link",
					"options": "User",
					"insert_after": "wip_warehouse",
					"allow_on_submit": 1,
					"description": "Shop-floor operator responsible for producing this Work Order",
				},
				{
					"fieldname": "packaging_operator",
					"label": "Packaging operator",
					"fieldtype": "Link",
					"options": "User",
					"insert_after": "operator",
					"allow_on_submit": 1,
					"description": "Shop-floor operator responsible for packaging this Work Order",
				},
			],
		},
		update=True,
	)
