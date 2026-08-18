"""Copy each Remittance Event's company down from the transfer it belongs to.

`Remittance Event` had no `company` column until this branch. It is readable by
Remittance Viewer, Auditor, Cashier and Finance Manager — non-admins, who ARE
subject to company isolation — so it still had to be scoped, and it was: through
a subquery against the parent transfer (`_parent_company_condition`), plus a
bespoke `has_permission` that resolved the link by hand because the shared
helper reads `doc.company` and would have found None on every event, taken its
blank-is-allowed branch, and returned True for every row.

Two scoping idioms for one concept is one more than can be kept correct. The
column replaces both with the same one-liner the transfer already used, and this
patch is what makes the column true for rows that predate it.

Why the backfill is not optional. The shared condition lets a NULL company
through on purpose — a record that never had one must not become invisible to
everybody. That convention is safe when a blank company means "not scoped"; on
an event it would mean "not backfilled", and every unbackfilled event would be
readable by every viewer of every company. So the column is `reqd` going
forward and this patch closes the rows behind it. An event whose transfer is
missing is left alone and reported: inventing a company for it would be a guess
about who may read it.

Why `db.set_value` and not `doc.save()`: an event is append-only, `save()` would
re-run validation on a document nobody edited, and `occurred_at`/`event_type`
are `reqd` on rows written before those fields existed in their current shape.
`update_modified=False` for the same reason as v90 — the schema grew a column,
nobody edited the row, and a false edit stamp on an audit trail is worse than no
stamp at all.

Idempotent: scoped to rows still holding NULL or "", so a second run matches
nothing.
"""

import frappe

EVENT = "Remittance Event"
TRANSFER = "Remittance Transfer"


def execute():
	# `has_column` raises TableMissingError rather than returning False when the
	# table is absent (.claude/rules/20-backend-migrations.md), so the table probe
	# has to come first or a tenant without the doctype aborts the whole migrate.
	if not frappe.db.table_exists(EVENT) or not frappe.db.table_exists(TRANSFER):
		return
	if not frappe.db.has_column(EVENT, "company"):
		return

	rows = frappe.get_all(
		EVENT,
		filters={"company": ("in", (None, ""))},
		fields=["name", "transfer"],
	)
	if not rows:
		return

	companies = dict(
		frappe.get_all(
			TRANSFER,
			filters={"name": ("in", sorted({r.transfer for r in rows if r.transfer}))},
			fields=["name", "company"],
			as_list=True,
		)
	)

	orphans = []
	for row in rows:
		company = companies.get(row.transfer)
		if not company:
			orphans.append(row.name)
			continue
		frappe.db.set_value(EVENT, row.name, "company", company, update_modified=False)

	if orphans:
		# Loud on purpose. These rows stay readable by every viewer until somebody
		# decides which company they belong to, and a silent skip is how that gets
		# discovered by the wrong person.
		frappe.log_error(
			title="v92: Remittance Events with no resolvable company",
			message=(
				f"{len(orphans)} event(s) have a missing or dangling transfer link and "
				f"were left with a blank company, which the read condition treats as "
				f"unscoped: {', '.join(orphans[:50])}"
			),
		)
