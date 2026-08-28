"""Seed the stop/loss reason catalogue.

Idempotent per row: an existing reason is left exactly as it is, including one a
site has switched off or reworded. This patch plants a first draft; it does not
own the list afterwards. Re-running it must not resurrect a reason somebody
deliberately deactivated, which is why the guard is `db.exists` on the name and
never an upsert.

Seeded on every site rather than only where the manufacturing module is on: it
is twenty rows, and the catalogue is unreachable except through that module's
screens. Gating it would mean a site that enables manufacturing later starts
with an empty dropdown and no way to know one was meant to be there.

Runs post-model-sync -- it inserts into a doctype this same migrate creates.
"""

import frappe

from stabler.api._downtime import SEED_REASONS


def execute():
	if not frappe.db.table_exists("Stabler Stop Reason"):
		# A site whose migrate has not created the table yet is not a failure to
		# report; see the has_column note in .claude/rules/20-backend-migrations.md.
		return

	for order, (reason, kind) in enumerate(SEED_REASONS, start=1):
		if frappe.db.exists("Stabler Stop Reason", reason):
			continue
		frappe.get_doc(
			{
				"doctype": "Stabler Stop Reason",
				"reason": reason,
				"kind": kind,
				"is_active": 1,
				# Ten apart, so a site can slot its own reasons between two seeded
				# ones without renumbering the list.
				"sort_order": order * 10,
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()
