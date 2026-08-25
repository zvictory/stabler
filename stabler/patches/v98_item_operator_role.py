"""Record on the Item which operator role its material belongs to.

v97 split the Work Order operator into two people. It deliberately stopped short
of saying which of them a given material line belongs to, because nothing read
the answer yet. Now something does: each role posts its own
`Material Consumption for Manufacture` entry, containing only its own lines, and
that entry needs to know which lines those are.

The rule has to be stored, not computed. The React prototype this work came from
computed it — `ishlabChiqarish.js:55` answers "whose material is this" with
`uom === 'kg' ? raw : packaging` — while its own item catalogue carries a stored
`operatorTuri` that nothing reads. Across the 669 BOM lines in that prototype's
seed data the two rules disagree on 190, and 55 of the 112 materials actually in
use land on the wrong operator. The unit of measure cannot decide this: sugar is
in kg and belongs to pouring, packing film is in kg and belongs to packing. Item
group is a better proxy than UoM, and still a proxy — nobody has confirmed that
anjan's group tree is clean along this axis, so this patch seeds nothing.

Which is the second deliberate omission: **no default and no backfill.** Every
existing Item comes out of this patch with an empty role, and that is the honest
state — the answer is not in the database, it is in the heads of the people who
run the floor. An empty role puts the line on nobody's operator sheet and on the
shift lead's, where the kiosk counts it out loud. A default would have hidden the
same gap behind a value that looks answered.

`custom_` prefix: Item is the most-extended doctype here, and the convention on
it is already `custom_length`, `custom_width`, `custom_dimension_mode` (v23, v63).
The Work Order operator fields are unprefixed for the opposite reason — v15
created `operator` and renaming it now would be a data migration.

Ungated, following v53 and v97: one optional Select on Item is invisible on a
tenant that never fills it.

Idempotent: `create_custom_fields(update=True)` re-applies the same definition,
so a second run is a no-op.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DOCTYPE = "Item"


def execute() -> None:
	# `has_column` raises TableMissingError rather than returning False when the
	# doctype's table is absent (.claude/rules/20-backend-migrations.md), so the
	# probe starts from `table_exists`.
	if not frappe.db.table_exists(DOCTYPE):
		return

	create_custom_fields(
		{
			DOCTYPE: [
				{
					"fieldname": "custom_operator_role",
					"label": "Operator role",
					"fieldtype": "Select",
					# Blank first: an item whose role nobody has decided must read as
					# undecided, not as production-by-default.
					"options": "\nProduction\nPackaging",
					"insert_after": "stock_uom",
					"description": (
						"Which shop-floor role consumes this material — production (pouring) "
						"or packaging. Leave empty when undecided: the line then goes to the "
						"shift lead rather than silently to one of the two operators."
					),
				},
			],
		},
		update=True,
	)
