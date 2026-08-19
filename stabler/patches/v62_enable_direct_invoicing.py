"""Seed enable_direct_invoicing from the company-name rule it replaces.

Direct Sales Invoicing used to be gated by a substring of the company name
(`"MSA" not in company.upper()`), which is the one capability in Stabler not
driven by a Stabler Company Modules flag. This patch creates the flag and
backfills it so the switchover changes no behaviour on any tenant: whoever the
old rule let through is exactly who the flag lets through.

Patches run PRE-sync, so the column may not exist yet — guard with has_column,
exactly as v14_add_enable_bpm does. Without the guard the first migrate after
this lands fails on a missing column.

Re-runnable: one pass, `WHERE ... IS NULL`. It used to be two statements — zero
everyone, then one for the MSA companies — and only the second was unconditional,
so a replay silently switched the feature back on for a tenant somebody had
deliberately switched off. Splitting the seed across two statements is what made
that invisible: each one reads as safe, and the hole is in the order.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_direct_invoicing"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# One pass, and only over rows that hold no decision yet. A NULL never reads
	# as permissive, and a 0 or a 1 is somebody's answer — including the operator
	# who turned this off after the patch first ran.
	#
	# UPPER(company) LIKE '%MSA%' reproduces `"MSA" in company.upper()`, so the
	# patch stays a faithful translation of the rule it replaces, not a new
	# decision about who should have the feature.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` "
		"SET enable_direct_invoicing = CASE WHEN UPPER(company) LIKE %(pattern)s THEN 1 ELSE 0 END "
		"WHERE enable_direct_invoicing IS NULL",
		{"pattern": "%MSA%"},
	)
	frappe.db.commit()
