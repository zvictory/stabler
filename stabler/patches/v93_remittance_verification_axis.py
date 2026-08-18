"""Close the verification axis behind the `code_locked` Check that was removed.

`Remittance Transfer` carried the same fact twice. `_refuse_the_code` set
`code_locked = 1` in the same `db_set` as `verification_status = "Locked"`;
`unlock_pickup_code` cleared it in the same `db_set` as `"Active"`. Two columns
that can only ever be written together are one column that can drift apart, and
every reader had to pick which one it trusted — the action predicates read the
Check, the detail screen read the Select. The Check is gone.

What the Check bought, and this patch has to replace. It was a Frappe Check, so
MariaDB gave it `NOT NULL DEFAULT 0` and `_queue_shapes` could filter
`code_locked = 0` in one clause. `verification_status` is a Select: `reqd` with a
default going forward, but a row that predates the field — or one written before
`reqd` landed — can hold NULL or "". In SQL a NULL is not `!=` anything, so such
a row would silently DISAPPEAR from the Ready-for-payout queue rather than appear
in it: money owed to somebody, invisible to the desk that owes it. That is the
failure this patch exists to prevent, and it is quiet, which is worse.

The derivation, for rows with a blank axis. `code_locked = 1` is the only
unambiguous signal and it is taken first, while the column is still readable
(this patch runs post-model-sync, and Frappe does not drop removed columns — but
it is guarded either way). The rest is read off `operational_status`, which is
the axis that says what happened to the transfer:

    Draft                -> Not Issued   (no code was ever handed out)
    Registered           -> Active       (a code exists and nobody has used it)
    Paid Out             -> Consumed     (the code was presented and accepted)
    Refunded / Expired   -> Expired      (the code can never be used now)
    Exception / anything -> Not Issued   (claims the least)

This is a derivation, not a recovery: for a blank row there is no record of what
the verification axis *was*. It is chosen to be conservative — the only value
that unlocks money is Active, and it is only assigned to a transfer that is
Registered, which is the state in which a live pickup code is exactly what
should exist.

Idempotent: scoped to rows still holding NULL or "", so a second run matches
nothing.
"""

import frappe

TRANSFER = "Remittance Transfer"

#: `operational_status` -> the verification axis it implies. See the derivation
#: note above; the default for anything unlisted is the least-claiming value.
_BY_OPERATIONAL = {
	"Draft": "Not Issued",
	"Registered": "Active",
	"Paid Out": "Consumed",
	"Refunded": "Expired",
	"Expired": "Expired",
}
_LEAST_CLAIMING = "Not Issued"


def execute():
	# `has_column` raises TableMissingError rather than returning False when the
	# table is absent (.claude/rules/20-backend-migrations.md), so the table probe
	# has to come first or a tenant without the doctype aborts the whole migrate.
	if not frappe.db.table_exists(TRANSFER):
		return
	if not frappe.db.has_column(TRANSFER, "verification_status"):
		return

	fields = ["name", "operational_status"]
	had_check = frappe.db.has_column(TRANSFER, "code_locked")
	if had_check:
		fields.append("code_locked")

	rows = frappe.get_all(
		TRANSFER,
		filters={"verification_status": ("in", (None, ""))},
		fields=fields,
	)
	for row in rows:
		if had_check and row.get("code_locked"):
			value = "Locked"
		else:
			value = _BY_OPERATIONAL.get(row.operational_status, _LEAST_CLAIMING)
		frappe.db.set_value(TRANSFER, row.name, "verification_status", value, update_modified=False)
