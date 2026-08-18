"""Create the two Sales Invoice Item box fields this app writes but never created.

`create_direct_sales_invoice` and `update_sales_invoice` both write
`custom_boxes` and `custom_box_kg` onto every invoice row
(`stabler/api/sales.py`, `_direct_invoice_item_rows`). Nothing in this repo has
ever created those Custom Fields. On MSA production they exist only because a
separate Django app makes them — `MSAERP/erpnext_integration/push.py`,
`ErpNextPusher.ensure_custom_fields`.

That went unnoticed because the live site has them: 21,129 of 21,141 Sales
Invoice Item rows on MSA already carry box data, so every test and every manual
check saw a working column. It works there *despite* this app, not because of
it. Anywhere else — a fresh install, another tenant, a rebuilt site, and MSA
itself the day the Django app is retired — the column does not exist, Frappe
drops an unknown key before it reaches `get_valid_dict()`, and the box count
disappears with no error at all. That is precisely the three-week silent loss
this branch was opened to fix, waiting to happen again one site over.

DEFINITIONS ARE COPIED FROM THE DJANGO APP, FIELD FOR FIELD, and must stay that
way. Where the fields already exist this patch skips them, so a divergence here
would not surface on MSA at all — it would surface on the first site where these
fields are created from scratch and the two systems then read each other's data
through differently-typed columns. `Float` and not `Int` is part of that: a
half-box is a real thing in the source system.

Gated on the tenant flag, per the multi-tenant rule. `in_list_view` puts these
two columns in the Sales Invoice Item grid, and six of the seven tenants have
direct invoicing deliberately switched off; adding columns to their invoice
lines for a capability they do not have is exactly what that rule forbids. A
site where no company enables the flag gets nothing.

The consequence, stated rather than engineered around: a tenant that switches
`direct_invoicing` ON *after* this patch has run gets no fields, because patches
run once. There is no backfill hook for a flag flip, and inventing one here
would be building machinery for an event that has not happened. What makes that
survivable is the other half of the fix, which is NOT in this patch — the write
path in `sales.py` is still unguarded, so on such a site the loss would again be
silent. Guarding it so the write fails loudly instead is the durable fix; this
patch is what makes the guard unnecessary on every site that exists today.

Idempotent: each field is created only when no Custom Field by that name exists
on the doctype, so a second run matches nothing and — importantly — never
rewrites the definition production is already using.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DOCTYPE = "Sales Invoice Item"
MODULES = "Stabler Company Modules"

#: Byte-for-byte the Django app's definitions. See the module docstring for why
#: this is a copy and not a re-design.
FIELDS = [
	{
		"fieldname": "custom_boxes",
		"fieldtype": "Float",
		"label": "Boxes",
		"insert_after": "item_name",
		"in_list_view": 1,
		"columns": 1,
		"read_only": 0,
	},
	{
		"fieldname": "custom_box_kg",
		"fieldtype": "Float",
		"label": "Box Weight (kg)",
		"insert_after": "custom_boxes",
		"in_list_view": 1,
		"columns": 1,
		"read_only": 0,
	},
]


def execute():
	# `has_column` raises TableMissingError rather than returning False when the
	# table is absent (.claude/rules/20-backend-migrations.md), so every probe here
	# starts from `table_exists` or a doctype existence check.
	if not frappe.db.table_exists(DOCTYPE) or not frappe.db.table_exists(MODULES):
		return

	# The tenant gate. `Stabler Company Modules` is a child table, so this asks
	# "does any company on this site have direct invoicing on", which is the same
	# question `module_map_for` answers per company.
	enabled = frappe.get_all(
		MODULES,
		filters={"enable_direct_invoicing": 1},
		fields=["name"],
		limit=1,
	)
	if not enabled:
		return

	missing = [
		field
		for field in FIELDS
		if not frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": field["fieldname"]})
	]
	if not missing:
		return

	create_custom_fields({DOCTYPE: missing}, ignore_validate=True)
