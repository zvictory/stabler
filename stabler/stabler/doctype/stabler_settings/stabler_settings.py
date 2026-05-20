import frappe
from frappe.model.document import Document


class StablerSettings(Document):
	pass


def get_company_module_row(company: str):
	"""Return the child row for `company`, creating defaults on demand.

	Defaults all modules to enabled when no explicit row exists yet.
	"""
	if not company:
		return None
	settings = frappe.get_single("Stabler Settings")
	for row in settings.company_modules or []:
		if row.company == company:
			return row
	row = settings.append(
		"company_modules",
		{
			"company": company,
			"enable_money": 1,
			"enable_sales": 1,
			"enable_purchasing": 1,
			"enable_inventory": 1,
			"enable_manufacturing": 1,
			"enable_hr": 1,
			"enable_stock_reservation": 1,
			"enable_compliance": 1,
		},
	)
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return row


def module_map_for(company: str) -> dict:
	row = get_company_module_row(company) if company else None
	if not row:
		return {
			"money": True,
			"sales": True,
			"purchasing": True,
			"inventory": True,
			"manufacturing": True,
			"hr": True,
			"stock_reservation": True,
			"compliance": True,
		}
	return {
		"money": bool(row.enable_money),
		"sales": bool(row.enable_sales),
		"purchasing": bool(row.enable_purchasing),
		"inventory": bool(row.enable_inventory),
		"manufacturing": bool(row.enable_manufacturing),
		"hr": bool(row.enable_hr),
		"stock_reservation": bool(getattr(row, "enable_stock_reservation", 1)),
		"compliance": bool(getattr(row, "enable_compliance", 1)),
	}
