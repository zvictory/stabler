import frappe
from frappe.model.document import Document


class StablerSettings(Document):
	pass


# Canonical opt-in module defaults for a brand-new company (and the no-row
# fallback). Lean ERP core — money+sales+purchasing+inventory — is ON; every
# specialized module is opt-in per owner-tenant. SINGLE SOURCE OF TRUTH: keep
# this in sync with the `Stabler Company Modules` doctype `default`s; both
# get_company_module_row and module_map_for derive from it, and
# organization.update_company_modules seeds new rows from _default_enable_row.
# Rationale: docs/plans/2026-07-18-multitenant-governance.md
DEFAULT_MODULE_ENABLED = {
	"money": True,
	"sales": True,
	"purchasing": True,
	"inventory": True,
	"manufacturing": False,
	"hr": False,
	"stock_reservation": False,
	"compliance": False,
	"field_sales": False,
	"marketing": False,
	"crm": False,
	"service": False,
	"bpm": False,
	"tender": False,
	"remittance": False,
	"installment": False,
	"imports": False,
	"agreements": False,
}


def desk_access_enabled() -> bool:
	"""True when this site lets non-admins into the classic Frappe Desk.

	Per-site switch, read by middleware/desk_gate.py and api/desk_write_guard.py.
	Tenant variance lives in config, never in code constants — see
	docs/plans/2026-07-18-multitenant-governance.md.
	"""
	try:
		return bool(frappe.db.get_single_value("Stabler Settings", "allow_desk_access"))
	except Exception:
		# Fresh install / mid-migrate: doctype or column not there yet — stay closed.
		return False


def _default_enable_row(company: str) -> dict:
	"""Child-row seed ({company, enable_*}) derived from DEFAULT_MODULE_ENABLED."""
	row = {"company": company}
	row.update({f"enable_{key}": int(val) for key, val in DEFAULT_MODULE_ENABLED.items()})
	return row


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
	row = settings.append("company_modules", _default_enable_row(company))
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return row


def module_map_for(company: str) -> dict:
	row = get_company_module_row(company) if company else None
	if not row:
		return dict(DEFAULT_MODULE_ENABLED)
	return {
		key: bool(getattr(row, f"enable_{key}", int(default)))
		for key, default in DEFAULT_MODULE_ENABLED.items()
	}
