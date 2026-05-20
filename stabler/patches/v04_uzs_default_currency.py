"""Set UZS as the default currency for any Company that has none.

Idempotent: only touches Companies whose `default_currency` is NULL/empty.
Companies that already pin USD/EUR/etc. are left alone.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Company"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabCompany`
		SET default_currency = 'UZS'
		WHERE default_currency IS NULL OR default_currency = ''
		"""
	)
	frappe.db.commit()
