import frappe


def execute():
	if frappe.db.has_column("Stabler Company Modules", "enable_field_sales"):
		frappe.db.sql(
			"""
			UPDATE `tabStabler Company Modules`
			SET enable_field_sales = 1
			WHERE enable_field_sales IS NULL
			"""
		)
	frappe.db.commit()
