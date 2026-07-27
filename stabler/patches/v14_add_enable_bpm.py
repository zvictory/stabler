"""Backfill enable_bpm = 1 for all existing Stabler Company Modules rows.

Patches run PRE-sync; the new column may not exist yet. Guard with has_column.
New rows created after this patch get enable_bpm=1 from the doctype field default.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_bpm"):
		return  # Column not yet created — DocType DDL sync hasn't run yet.
	frappe.db.sql("UPDATE `tabStabler Company Modules` SET enable_bpm = 1 WHERE enable_bpm IS NULL")
	frappe.db.commit()
