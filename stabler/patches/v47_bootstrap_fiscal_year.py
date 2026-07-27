import frappe


def execute():
	"""Bootstrap Fiscal Years for 2024, 2025, 2026, and 2027 if missing."""
	years = [2024, 2025, 2026, 2027]
	for year in years:
		name = f"{year}"
		if not frappe.db.exists("Fiscal Year", name):
			try:
				fy = frappe.new_doc("Fiscal Year")
				fy.year = name
				fy.year_start_date = f"{year}-01-01"
				fy.year_end_date = f"{year}-12-31"
				fy.insert(ignore_permissions=True)
			except Exception:
				pass
