"""Seed enable_dimensional_lines from the data, not from a list of tenant names.

The flag decides whether the sales order form shows its measurement columns by
default. Rather than hardcoding which of the seven sites sell by size, this asks
the site itself: if any Item here carries a dimension mode, the tenant sells
dimensional goods and the columns should be up front.

That is deliberately the same shape as v62 — a patch should translate a fact
that already exists, not invent a new policy. The difference is where the fact
lives: v62 read it off the company NAME, this one reads it off the catalogue.

This patch is registered under [post_model_sync] in patches.txt (line 68), so
both columns already exist by the time it runs. Both are guarded anyway
(house style: it costs one `if` each and survives someone moving this entry
later); re-running the patch is harmless because it recomputes from the same
data.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_dimensional_lines"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	sells_by_size = False
	if frappe.db.has_column("Item", "custom_dimension_mode"):
		# Item is site-scoped (one site per tenant), so a dimensional item
		# anywhere in the catalogue means this tenant's sellers need the
		# columns. Companies inside the site share the catalogue. No column
		# means no catalogue evidence yet, which is not evidence of none —
		# it is no decision, and no decision closes.
		sells_by_size = bool(
			frappe.db.sql(
				"SELECT 1 FROM `tabItem` WHERE custom_dimension_mode IN ('Linear', 'Area', 'Volume') LIMIT 1"
			)
		)

	# NULL is the only state this patch may write. A row already holding 0 or 1
	# holds somebody's answer — and on the second run the catalogue still sells
	# by size, so an unqualified `SET = 1` would reopen a tenant an operator
	# closed on purpose and tell nobody. NULL must never read as permissive, so
	# the rows with no answer get one here, in a single pass.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_dimensional_lines = %s "
		"WHERE enable_dimensional_lines IS NULL",
		(1 if sells_by_size else 0,),
	)

	frappe.db.commit()
