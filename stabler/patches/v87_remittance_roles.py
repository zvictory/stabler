"""Create the Remittance Center Frappe Roles, and drop the delete right on Remittance Transfer.

Four desk-less roles used purely as the SPA capability layer for the remittance
module (module key `remittance`): Viewer, Cashier, Finance Manager, Auditor.
They are the four the plan names
(docs/plans/2026-08-16-remittance-operations-center.md:456-460); before this
patch, grepping the tree for a role name containing "Remittance" returned
nothing, so every remittance doctype shipped System-Manager-only.

Same shape as v84_vehicle_finance_roles: each Role is inserted only if missing,
and Role is a core doctype that always exists, so this half needs no table probe.
Role creation is deliberately NOT gated on the remittance tables existing — the
DocPerm rows that name these roles ship inside the app's own doctype JSON, so any
site with the app has the rows. Gating would leave DocPerms pointing at a Role
that was never created; the cost of not gating is four inert Role records.

The second half is gated, and that is why it uses ``table_exists`` and not
``has_column``: ``frappe.db.has_column`` raises ``TableMissingError`` rather than
returning False when the table does not exist
(.claude/rules/20-backend-migrations.md), so a tenant without the doctype would
abort the migrate instead of skipping.

Why the delete right goes: Remittance Transfer is the aggregate root of a money
trail — three Journal Entry links (register / payout / refund) and an append-only
Remittance Event trail whose controller throws on both edit and delete. Deleting
the master leaves the Journal Entries posted in the GL with nothing tying them
together, and ``track_changes`` does not rescue it because Frappe deletes the
Version rows along with the document. The right was also already unusable in
practice: Remittance Event links back to the transfer, so Frappe's link-integrity
check blocks the delete for any transfer that was ever registered, and
``register_remittance`` writes transfer and event in the same transaction. A
wrong transfer is undone by a domain reversal, not by erasing the row.

Idempotent: the role loop skips roles that exist, and the DocPerm UPDATE is
scoped to rows that still carry the flag, so a second run touches nothing.
"""

import frappe

TRANSFER = "Remittance Transfer"

_ROLES = (
	"Remittance Viewer",
	"Remittance Cashier",
	"Remittance Finance Manager",
	"Remittance Auditor",
)


def execute():
	for role in _ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)

	_revoke_transfer_delete()


def _revoke_transfer_delete():
	"""Clear any DocPerm row that still grants delete on Remittance Transfer.

	The doctype JSON no longer carries the flag, and a normal `bench migrate`
	resyncs the permission set from it. This is the belt to that braces: v75
	exists in this same patch directory because DocPerm rows have survived a
	sync before, and a stale delete right on a ledger-linked record is not a
	failure worth discovering later.
	"""
	if not frappe.db.table_exists("DocPerm"):
		return
	if not frappe.db.table_exists(TRANSFER):
		# Tenant does not carry the remittance doctype at all — nothing to repair.
		return

	frappe.db.sql(
		"""
		update `tabDocPerm`
		set `delete` = 0
		where parent = %s and parenttype = 'DocType' and `delete` = 1
		""",
		(TRANSFER,),
	)
