"""Seed enable_direct_invoicing from the company-name rule it replaces.

Direct Sales Invoicing used to be gated by a substring of the company name
(`"MSA" not in company.upper()`), which is the one capability in Stabler not
driven by a Stabler Company Modules flag. This patch creates the flag and
backfills it so the switchover changes no behaviour on any tenant: whoever the
old rule let through is exactly who the flag lets through.

Patches run PRE-sync, so the column may not exist yet — guard with has_column,
exactly as v14_add_enable_bpm does. Without the guard the first migrate after
this lands fails on a missing column.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_direct_invoicing"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# Default everyone to off first, so a NULL never reads as permissive.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_direct_invoicing = 0 "
		"WHERE enable_direct_invoicing IS NULL"
	)

	# Then turn it on for exactly the companies the old name rule matched.
	# UPPER(company) LIKE '%MSA%' reproduces `"MSA" in company.upper()` so the
	# patch is a faithful translation of the rule, not a new decision about
	# who should have it.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_direct_invoicing = 1 "
		"WHERE UPPER(company) LIKE %(pattern)s",
		{"pattern": "%MSA%"},
	)
	frappe.db.commit()
