"""Repair Custom DocPerm rows that shadow a doctype's whole standard permission set.

Incident: on 2026-08-03 (mikas, tender role setup) and 2026-08-04 (anjan, "Dokon
POS" role setup) ad-hoc scripts inserted a single ``Custom DocPerm`` row per
doctype. In Frappe that single row makes the entire standard ``DocPerm`` set for
the doctype inert, so every standard role silently lost its permissions — hence
403s on Customer/Item reads and "You don't have permission to get a report on:
GL Entry".

Targeting: a doctype is repaired only when **all** of its Custom DocPerm rows
were created at/after the incident window start, i.e. its custom set is entirely
a product of the incident. Older custom sets are deliberate admin restrictions
(several sites carry long-standing ones on Account, Company, Cost Center, …) and
are left untouched — this patch must never widen a restriction someone meant.

Idempotent: ``repair_shadowed_docperms`` only inserts ``(role, permlevel)`` pairs
that are missing, so re-running is a no-op.
"""

import frappe

from stabler.api.permissions import repair_shadowed_docperms

# Start of the incident window (Tashkent time, as stored in `creation`).
# Earliest observed bad row: mikas 2026-08-03 22:00.
INCIDENT_WINDOW_START = "2026-08-03 00:00:00"


def execute():
	if not frappe.db.table_exists("Custom DocPerm"):
		return

	result = repair_shadowed_docperms(only_created_after=INCIDENT_WINDOW_START)
	repaired = result["repaired"]
	if repaired:
		total = sum(repaired.values())
		frappe.logger("stabler.permissions").info(
			f"v75_repair_shadowed_docperms: restored {total} rows across {len(repaired)} doctypes: {repaired}"
		)
		frappe.clear_cache()
