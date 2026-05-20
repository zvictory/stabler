import frappe


def execute():
	if frappe.db.has_column("Stabler Company Modules", "enable_marketing"):
		frappe.db.sql(
			"""
			UPDATE `tabStabler Company Modules`
			SET enable_marketing = 1
			WHERE enable_marketing IS NULL
			"""
		)
	frappe.db.commit()
