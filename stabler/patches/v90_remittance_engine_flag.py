"""Write the Legacy engine onto Remittance Settings rows that predate the field.

`remittance_engine` gates the whole Transfer V1 surface: the operations centre,
the payout desk, the refund chain, reconciliation and the settings screen exist
only while a company reads "V1". The field ships with `default: "Legacy"`, and a
doctype default applies to documents created after it — a row that already exists
gets the column added by DDL sync with NULL in it.

NULL and "Legacy" read the same way through `get_engine()` (it coalesces), so this
patch does not change any behaviour. It exists so the value a System Manager sees
in the Desk is the value the gate is acting on. A blank Select next to a field
labelled "Remittance Engine" invites exactly one guess — that nothing is decided
yet — on the screen where somebody is about to decide whether a company can move
money through a new engine.

Why `db.set_value` and not `doc.save()`: the doctype carries three `reqd: 1`
account fields (receiver obligation, deferred commission, commission income) and
no patch or fixture has ever populated them, so `save()` would raise
MandatoryError on precisely the rows that need the backfill — a company that was
never finished configuring. `validate()` would also re-run the desk/currency
dedupe over child rows this patch has no business re-litigating. The write here is
one column on rows that are already wrong to load as documents.

`update_modified=False` on purpose: nobody edited these rows. The schema grew a
column and it was filled with its own default. Bumping `modified` would put a
false edit stamp on a tracked doctype and hand `track_changes` a Version row
describing a change of intent that did not happen.

Deliberately no row creation. A company with no Remittance Settings row has never
been configured, and that is not the same thing as a company configured to run
Legacy. `get_engine()` already answers Legacy for both, so a seeded row would buy
nothing and would claim a decision nobody made — and it could not be inserted
anyway without inventing the three mandatory accounts.

Idempotent: the update is scoped to rows still holding NULL or "", so a second run
matches nothing.
"""

import frappe

DOCTYPE = "Remittance Settings"
FIELDNAME = "remittance_engine"
LEGACY = "Legacy"


def execute():
	# `has_column` raises TableMissingError rather than returning False when the
	# table is absent (.claude/rules/20-backend-migrations.md), so the table probe
	# has to come first or a tenant without the doctype aborts the whole migrate.
	if not frappe.db.table_exists(DOCTYPE):
		return
	if not frappe.db.has_column(DOCTYPE, FIELDNAME):
		return

	names = frappe.get_all(
		DOCTYPE,
		filters={FIELDNAME: ("in", (None, ""))},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(DOCTYPE, name, FIELDNAME, LEGACY, update_modified=False)
