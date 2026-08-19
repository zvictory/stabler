"""Seed enable_modern_sales_order to 0 for every tenant — everyone back on the
classic Sales Order form.

`a0c9457` replaced the classic two-column Sales Order form with a single-column
redesign for all seven tenants at once, without asking any of them. The two
forms now live side by side and this flag picks between them; OFF means the
classic form, which is what every tenant used before the redesign and what the
owner asked to get back. A tenant that wants the new design turns it on from
Companies after deploy.

The column default is "0" too — the default is what decides a *new* company,
this patch is what decides the *existing* rows (and NULL, which must never read
as permissive).

Idempotent, and the reason is the WHERE clause, not the value: only a row with
no answer yet (NULL) is written. "Re-running only ever sets rows to 0, so it is
always safe" was the old claim and it was backwards — setting a row to 0 is the
damage, and the only row the old `OR <flag> != 0` clause could match was one a
human had deliberately set to 1.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_modern_sales_order"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# NULL must never read as permissive: close the rows that hold no answer.
	# Only those. `OR enable_modern_sales_order != 0` used to be here, and the
	# only row it could ever match was one a human had set to 1 — so a replay,
	# which in this repo means a site repair, silently switched the feature back
	# off for whoever had asked for it.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_modern_sales_order = 0 "
		"WHERE enable_modern_sales_order IS NULL"
	)

	frappe.db.commit()
