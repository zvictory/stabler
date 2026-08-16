"""Rename the collectible agreement status `Restructured` -> `Rescheduled`.

`Restructured` used to label a RESCHEDULE: `approve_reschedule()` cut a new
Vehicle Finance Schedule Version at the same total and stamped the agreement
`Restructured`, which `_COLLECTIBLE_STATUSES` then treated as an ACTIVE state.
Per docs/decisions/2026-08-16-restructure-closes-and-reopens.md a restructure
CLOSES the original agreement and OPENS a successor, so `Restructured` is now
reserved as a TERMINAL status and the collectible state is `Rescheduled`.

The rewrite is lossless and mechanical, not a judgement call: `approve_reschedule()`
was the only writer of `Restructured` anywhere in the app, so every existing row
carrying it is a reschedule. Nothing has to be classified by hand.

Idempotent: the UPDATE matches nothing on a second run. Pre-sync safe: it touches
an existing column only, and Select options are not enforced at the DB level, so
it does not depend on the new enum option having synced yet.
"""

import frappe


def execute():
	# A site that does not carry the doctype has nothing to rewrite. Probe the
	# table first — has_column raises TableMissingError rather than returning
	# False when the table is absent.
	if not frappe.db.table_exists("Vehicle Agreement"):
		return
	if not frappe.db.has_column("Vehicle Agreement", "agreement_status"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabVehicle Agreement`
		SET agreement_status = 'Rescheduled'
		WHERE agreement_status = 'Restructured'
		"""
	)
