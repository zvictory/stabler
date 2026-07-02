"""Whitelisted HR attendance API (Phase 3 surface).

Thin Frappe layer over the pure engine in `_attendance_rules` /
`_attendance_processor`. Lets the SPA list/read attendance rule sets and run a
"simulate this day" preview so HR can see exactly how the rules score a punch
pattern before any of it touches payroll.

The heavy logic is pure and unit-tested; this module only does auth, fetch,
validate, and delegate.
"""

from __future__ import annotations

import json

import frappe
from stabler.api.approvals import _assert_company_scope
from frappe import _

from stabler.api._attendance_processor import summarize_day
from stabler.api._attendance_rules import policies_from_ruleset
from stabler.api._common import _assert_can_write

_RULESET = "Stabler Attendance Rule Set"

# Whitelist of fields the SPA is allowed to write on a rule set.
# Section breaks, column breaks, and read-only metadata are excluded.
_RULESET_WRITABLE_FIELDS = {
	"rule_set_name",
	"company",
	"enabled",
	"is_default",
	"min_worked_for_present_min",
	"grace_min",
	"step_min",
	"flat_fee_uzs",
	"step_fee_uzs",
	"daily_cap_uzs",
	"night_start_hour",
	"night_end_hour",
	"night_premium_pct",
	"ot_method",
	"ot_threshold_min",
	"half_day_min_worked_min",
	"anchor_day_h",
	"anchor_night_h",
	"anchor_office_h",
	"anchor_light_h",
	"weekly_off_days",
	"holiday_ot_premium_pct",
	"break_minutes",
	"clock_drift_tolerance_min",
	"early_leave_deduction_enabled",
	# Compensation policy (Phase 3 — feeds the payroll engine)
	"ot_multiplier",
	"kpi_share_pct",
	"region_city_rate",
	"region_district_rate",
	"region_far_district_rate",
}


def _guard(ptype: str = "read") -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)
	if not frappe.has_permission(_RULESET, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def list_rule_sets(company: str | None = None) -> list[dict]:
	"""Rule sets, optionally filtered by company."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_guard("read")
	filters: dict = {}
	if company:
		filters["company"] = company
	return frappe.get_all(
		_RULESET,
		filters=filters,
		fields=["name", "rule_set_name", "company", "enabled", "is_default"],
		order_by="is_default desc, modified desc",
	)


@frappe.whitelist()
def get_rule_set(name: str) -> dict:
	"""Full rule set (for the editor)."""
	_guard("read")
	if not name:
		frappe.throw(_("Rule set name is required."))
	if not frappe.has_permission(_RULESET, "read", doc=name):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return frappe.get_doc(_RULESET, name).as_dict()


@frappe.whitelist()
def save_rule_set(payload) -> dict:
	"""Create or update a Stabler Attendance Rule Set.

	`payload` may be a JSON string or a dict. If `name` is present and the doc
	exists the endpoint updates it (write-permission checked per-doc to prevent
	IDOR). Otherwise a new doc is created (create-permission checked globally).

	Only fields in ``_RULESET_WRITABLE_FIELDS`` are applied; all other keys in
	`payload` are silently ignored so the SPA cannot overwrite internal fields.

	Returns ``{"name": "<docname>"}``.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)

	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("Invalid payload — expected JSON object."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	rule_set_name = (payload.get("rule_set_name") or "").strip()
	if not rule_set_name:
		frappe.throw(_("rule_set_name is required."))

	existing_name = payload.get("name", "").strip()
	is_update = bool(existing_name and frappe.db.exists(_RULESET, existing_name))

	if is_update:
		_assert_can_write(_RULESET, existing_name, "write")
		doc = frappe.get_doc(_RULESET, existing_name)
	else:
		if not frappe.has_permission(_RULESET, "create"):
			frappe.throw(_("Not permitted to create Attendance Rule Sets."), frappe.PermissionError)
		doc = frappe.new_doc(_RULESET)

	for field in _RULESET_WRITABLE_FIELDS:
		if field in payload:
			doc.set(field, payload[field])

	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name}


def _resolve_ruleset(rule_set: str | None, company: str | None) -> dict:
	"""Pick a rule set: the named one, else the company default, else built-in
	defaults (empty dict -> policies_from_ruleset falls back)."""
	if rule_set and frappe.db.exists(_RULESET, rule_set):
		return frappe.get_doc(_RULESET, rule_set).as_dict()
	if company:
		default = frappe.get_all(_RULESET, filters={"company": company, "is_default": 1},
			fields=["name"], limit=1)
		if default:
			return frappe.get_doc(_RULESET, default[0]["name"]).as_dict()
	return {}


@frappe.whitelist()
def simulate_day(
	punches,
	date_str: str,
	hire_date: str,
	shift: str = "DAY",
	shift_start_hm: str = "09:00",
	is_holiday: int | str = 0,
	termination_date: str | None = None,
	device_late_min=None,
	rule_set: str | None = None,
	company: str | None = None,
) -> dict:
	"""Preview how the rule engine classifies one day. `punches` is a list (or
	JSON string) of {timestamp, direction}. Read-only — computes nothing on the
	ledger."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_guard("read")
	if isinstance(punches, str):
		try:
			punches = json.loads(punches)
		except Exception:
			frappe.throw(_("Invalid punches payload."))
	if not isinstance(punches, list):
		frappe.throw(_("punches must be a list of {timestamp, direction}."))
	if not date_str or not hire_date:
		frappe.throw(_("date_str and hire_date are required."))

	rs = _resolve_ruleset(rule_set, company)
	late, night, half, mwp = policies_from_ruleset(rs)
	dlm = None
	if device_late_min not in (None, ""):
		try:
			dlm = int(device_late_min)
		except (TypeError, ValueError):
			dlm = None

	return summarize_day(
		punches,
		shift=shift,
		shift_start_hm=shift_start_hm or "09:00",
		is_holiday=bool(int(is_holiday or 0)),
		date_str=date_str,
		hire_date=hire_date,
		termination_date=termination_date or None,
		late=late, half=half, night=night,
		min_worked_present=mwp,
		device_late_min=dlm,
	)
