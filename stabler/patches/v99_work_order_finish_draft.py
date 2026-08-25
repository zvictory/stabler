"""Keep an unconfirmed finish on the Work Order, so it survives the operator.

The kiosk's finish dialog collects the numbers that close an order: produced
quantity, rejects, and the batch details behind them. Until now it held those in
component state, which means the tablet locking, the shift ending, or the operator
badging out threw the count away — after they had already walked the pallet and
counted it. That is not a rare path on a shop floor; it is what happens at every
handover.

**On the order, not in the browser.** localStorage would have been fewer moving
parts and would have been wrong twice over: one order is run by two people, so a
draft the pourer saved has to be there when the packer opens the same order on a
different tablet, and a shift lead asking "what is sitting unconfirmed right now"
has to be able to see it at all.

Three fields rather than seven. The questions anyone actually asks of a draft —
is there one, how old is it, whose is it — are the ones worth querying, so they
are real columns. The numbers inside are only ever read back into the same dialog
that wrote them, and spreading them across five more Custom Fields would put five
more permanent columns on every tenant's Work Order table to serve a value that
lives for twenty minutes.

`custom_` prefix following v53 and v98. The v97 operator fields are unprefixed for
the opposite reason: v15 created `operator` and renaming it now would be a data
migration.

Ungated: three optional fields are invisible on a tenant whose operators never
open the kiosk.

Idempotent: `create_custom_fields(update=True)` re-applies the same definition, so
a second run is a no-op.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DOCTYPE = "Work Order"


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
					"fieldname": "custom_finish_draft",
					"label": "Unconfirmed finish",
					"fieldtype": "Small Text",
					"read_only": 1,
					"insert_after": "produced_qty",
					"description": (
						"What the operator entered in the finish dialog but has not confirmed. "
						"Written and read by the kiosk; cleared the moment the Manufacture entry posts."
					),
				},
				{
					"fieldname": "custom_finish_draft_at",
					"label": "Unconfirmed finish saved at",
					"fieldtype": "Datetime",
					"read_only": 1,
					"insert_after": "custom_finish_draft",
				},
				{
					"fieldname": "custom_finish_draft_by",
					"label": "Unconfirmed finish saved by",
					"fieldtype": "Link",
					"options": "User",
					"read_only": 1,
					"insert_after": "custom_finish_draft_at",
					"description": (
						"One order is run by two operators, so a draft has an author: the person "
						"who opens it next needs to know whose count they are about to confirm."
					),
				},
			],
		},
		update=True,
	)
