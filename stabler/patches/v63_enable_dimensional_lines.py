"""Seed enable_dimensional_lines from the data, not from a list of tenant names.

The flag decides whether the sales order form shows its measurement columns by
default. Rather than hardcoding which of the seven sites sell by size, this asks
the site itself: if any Item here carries a dimension mode, the tenant sells
dimensional goods and the columns should be up front.

That is deliberately the same shape as v62 — a patch should translate a fact
that already exists, not invent a new policy. The difference is where the fact
lives: v62 read it off the company NAME, this one reads it off the catalogue.

Patches run PRE-sync, so neither column is guaranteed to exist yet. Both are
guarded; a site that has not synced yet simply gets the default (0) later, and
re-running the patch is harmless because it recomputes from the same data.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_dimensional_lines"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# NULL must never read as permissive: close everyone first, then open.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_dimensional_lines = 0 "
		"WHERE enable_dimensional_lines IS NULL"
	)

	if not frappe.db.has_column("Item", "custom_dimension_mode"):
		# No dimensional catalogue possible on this site yet — leaving every
		# tenant at 0 is correct, and the admin toggle stays available.
		frappe.db.commit()
		return

	sells_by_size = frappe.db.sql(
		"SELECT 1 FROM `tabItem` "
		"WHERE custom_dimension_mode IN ('Linear', 'Area', 'Volume') LIMIT 1"
	)
	if sells_by_size:
		# Item is site-scoped (one site per tenant), so a dimensional item
		# anywhere in the catalogue means this tenant's sellers need the
		# columns. Companies inside the site share the catalogue.
		frappe.db.sql("UPDATE `tabStabler Company Modules` SET enable_dimensional_lines = 1")

	frappe.db.commit()
