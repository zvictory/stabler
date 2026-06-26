"""Payroll component generation and validation endpoints.

Bridges ``Stabler Payroll Attendance Summary`` rows → ERPNext
``Additional Salary`` rows via the ``Stabler Payroll Component Map``.

Endpoints (all reject Guest; check frappe.has_permission; anti-IDOR):

  preview_payroll_components(summary_name)
      Read-only preview: returns mapped component lines, totals, unmapped
      keys and the summary status.  Works on any summary status.

  generate_additional_salary(summary_name)
      Write: gated on status == "Locked" and a complete component mapping.
      Creates ERPNext Additional Salary rows (idempotent — deletes any
      previously Stabler-generated rows for the same employee+period first).
      Returns {created, lines}.

  validate_against_slip(summary_name, salary_slip)
      Read-only: compares the summary-derived net against a Salary Slip net.
      Returns slip_variance result plus the ±1000 UZS tolerance flag.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.api._common import _assert_can_read, _assert_can_write
from stabler.api.approvals import _assert_company_scope
from stabler.api._payroll_components import (
	summary_to_components,
	components_total,
	slip_variance,
	mapping_complete,
)

_SUMMARY = "Stabler Payroll Attendance Summary"
_COMPONENT_MAP = "Stabler Payroll Component Map"
_ADDITIONAL_SALARY = "Additional Salary"
_SALARY_SLIP = "Salary Slip"

# Marker stored in Additional Salary.remarks so we can delete on re-run.
_STABLER_MARKER = "stabler-payroll-generated"

# Doctype field → component_map quantity key (mirrors _payroll_components.QUANTITY_KEYS).
_MAP_FIELDS = [
	# (quantity_key, link_fieldname, type_fieldname)
	("late_deduction",  "late_deduction_component",   "late_deduction_type"),
	("overtime",        "overtime_component",          "overtime_type"),
	("night_premium",   "night_premium_component",     "night_premium_type"),
	("duty_supplement", "duty_supplement_component",   "duty_supplement_type"),
	("kpi",             "kpi_component",               "kpi_type"),
	("region_rate",     "region_rate_component",       "region_rate_type"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_auth() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)


def _component_map_for(company: str) -> dict:
	"""Load the enabled Stabler Payroll Component Map for *company*.

	Returns a dict in the shape ``summary_to_components`` expects::

		{
		    "late_deduction":  {"salary_component": str, "component_type": str},
		    "overtime":        {"salary_component": str, "component_type": str},
		    ...
		}

	Keys whose link field is blank (component not yet configured) are omitted so
	``mapping_complete`` can identify them as unmapped.

	Raises frappe.ValidationError if no enabled map exists for the company.
	"""
	maps = frappe.get_all(
		_COMPONENT_MAP,
		filters={"company": company, "enabled": 1},
		fields=["name"],
		limit_page_length=1,
	)
	if not maps:
		frappe.throw(
			_("No enabled Stabler Payroll Component Map found for company {0}. "
			  "Create and enable one before generating payroll components.").format(company),
			frappe.ValidationError,
		)

	map_name = maps[0]["name"]
	# Fetch all the component link + type fields in one call.
	field_list = ["name"]
	for (_key, link_field, type_field) in _MAP_FIELDS:
		field_list.append(link_field)
		field_list.append(type_field)

	map_doc = frappe.get_all(
		_COMPONENT_MAP,
		filters={"name": map_name},
		fields=field_list,
		limit_page_length=1,
	)
	if not map_doc:
		frappe.throw(
			_("Component map {0} not found.").format(map_name),
			frappe.DoesNotExistError,
		)

	row = map_doc[0]
	component_map: dict = {}
	for (key, link_field, type_field) in _MAP_FIELDS:
		salary_component = (row.get(link_field) or "").strip()
		component_type = (row.get(type_field) or "").strip()
		if salary_component:
			# Only include entries where a component is actually configured.
			component_map[key] = {
				"salary_component": salary_component,
				"component_type": component_type or "Earning",
			}
	return component_map


def _load_summary(summary_name: str) -> dict:
	"""Fetch all relevant fields from Stabler Payroll Attendance Summary."""
	rows = frappe.get_all(
		_SUMMARY,
		filters={"name": summary_name},
		fields=[
			"name",
			"employee",
			"employee_name",
			"payroll_period",
			"company",
			"status",
			"late_deduction_amount",
			"overtime_amount",
			"night_premium_amount",
			"duty_supplement",
			"kpi_adjustment",
			"region_rate",
		],
		limit_page_length=1,
	)
	if not rows:
		frappe.throw(
			_("Payroll Attendance Summary {0} not found.").format(summary_name),
			frappe.DoesNotExistError,
		)
	return rows[0]


def _payroll_date_from_period(payroll_period: str) -> str:
	"""Derive a payroll_date (last day of the period month) from a YYYY-MM string.

	Falls back to today if the period cannot be parsed, to avoid blocking the
	insert.  ERPNext Additional Salary requires payroll_date to be set.
	"""
	import calendar
	from frappe.utils import nowdate

	try:
		y, m = payroll_period.split("-")
		last_day = calendar.monthrange(int(y), int(m))[1]
		return f"{y}-{m}-{last_day:02d}"
	except Exception:
		return nowdate()


def _delete_stabler_additional_salaries(employee: str, payroll_period: str, company: str) -> int:
	"""Delete any previously Stabler-generated Additional Salary rows for this slot.

	Idempotency: marks rows that were created by this module via the ``remarks``
	field.  On re-run they are deleted before re-creating so amounts are not
	doubled.

	Returns the count of deleted rows.
	"""
	existing = frappe.get_all(
		_ADDITIONAL_SALARY,
		filters={
			"employee": employee,
			"company": company,
			"payroll_date": ["like", f"{payroll_period}%"],
			"remarks": _STABLER_MARKER,
			"docstatus": ["!=", 2],  # not already cancelled
		},
		fields=["name", "docstatus"],
	)
	deleted = 0
	for row in existing:
		doc = frappe.get_doc(_ADDITIONAL_SALARY, row["name"])
		if doc.docstatus == 1:
			# Submitted — cancel first, then delete.
			doc.cancel()
		doc.delete(ignore_permissions=False)
		deleted += 1
	return deleted


# ---------------------------------------------------------------------------
# preview_payroll_components
# ---------------------------------------------------------------------------

@frappe.whitelist()
def preview_payroll_components(summary_name: str) -> dict:
	"""Preview how a summary will translate to salary components.

	Permission: read on Stabler Payroll Attendance Summary.
	READ-ONLY.  Works regardless of summary.status.

	Args:
		summary_name: name (docname) of a Stabler Payroll Attendance Summary.

	Returns::

		{
		    "lines":          [<component line dicts from summary_to_components>],
		    "totals":         {"earnings": float, "deductions": float, "net": float},
		    "unmapped":       ["quantity_key", ...],   # empty = map is complete
		    "summary_status": "Draft" | "Ready" | "Locked",
		}
	"""
	_require_auth()
	_assert_can_read(_SUMMARY, summary_name)

	summary = _load_summary(summary_name)
	_assert_company_scope(summary["company"])

	component_map = _component_map_for(summary["company"])
	lines = summary_to_components(summary, component_map)
	totals = components_total(lines)
	unmapped = mapping_complete(summary, component_map)

	return {
		"lines": lines,
		"totals": totals,
		"unmapped": unmapped,
		"summary_status": summary["status"],
	}


# ---------------------------------------------------------------------------
# generate_additional_salary
# ---------------------------------------------------------------------------

@frappe.whitelist()
def generate_additional_salary(summary_name: str) -> dict:
	"""Generate ERPNext Additional Salary rows from a Locked payroll summary.

	Permission: write on Stabler Payroll Attendance Summary.

	Gates (raises frappe.ValidationError if not met):
		1. summary.status MUST be "Locked".
		2. Component mapping must be complete (mapping_complete returns []).

	Idempotent: deletes any previously Stabler-generated Additional Salary rows
	for the same employee + period before inserting fresh ones.  Re-running is
	safe and will not double-post amounts.

	NOTE: the frappe.get_doc(...).insert() calls below execute against a live
	ERPNext bench.  They are intentional real ledger writes — not mock stubs.

	Args:
		summary_name: name (docname) of a Stabler Payroll Attendance Summary.

	Returns::

		{
		    "created": int,    # number of Additional Salary rows created
		    "lines":   [...],  # the component lines that were created
		}
	"""
	_require_auth()
	_assert_can_write(_SUMMARY, summary_name)

	summary = _load_summary(summary_name)
	_assert_company_scope(summary["company"])

	# Gate 1: must be Locked.
	if summary["status"] != "Locked":
		frappe.throw(
			_("Lock the payroll period before generating salary components. "
			  "Summary {0} is currently '{1}'.").format(summary_name, summary["status"]),
			frappe.ValidationError,
		)

	component_map = _component_map_for(summary["company"])

	# Gate 2: mapping must be complete.
	unmapped = mapping_complete(summary, component_map)
	if unmapped:
		frappe.throw(
			_("Component mapping is incomplete. The following quantities have no salary "
			  "component assigned: {0}. Update the Stabler Payroll Component Map for "
			  "company {1} before generating.").format(
				", ".join(unmapped), summary["company"]
			),
			frappe.ValidationError,
		)

	lines = summary_to_components(summary, component_map)
	if not lines:
		return {"created": 0, "lines": []}

	employee = summary["employee"]
	company = summary["company"]
	payroll_period = summary["payroll_period"]
	payroll_date = _payroll_date_from_period(payroll_period)

	# Idempotency: remove any previously generated rows for this slot.
	_delete_stabler_additional_salaries(employee, payroll_period, company)

	# Create fresh Additional Salary rows.
	created = 0
	for line in lines:
		# Lines with no salary_component (unmapped) are already blocked above;
		# guard here as a belt-and-suspenders safety check.
		if not line.get("salary_component"):
			continue

		new_doc = frappe.get_doc({
			"doctype": _ADDITIONAL_SALARY,
			"employee": employee,
			"company": company,
			"salary_component": line["salary_component"],
			"type": line["component_type"],
			"amount": line["abs_amount"],
			"payroll_date": payroll_date,
			"overwrite_salary_structure_amount": 1,
			"remarks": _STABLER_MARKER,
		})
		new_doc.insert(ignore_permissions=False)
		created += 1

	if created:
		frappe.db.commit()

	return {"created": created, "lines": lines}


# ---------------------------------------------------------------------------- #
# Net-only emission — Stabler is the source of truth, ERPNext gets ONE number.
# ---------------------------------------------------------------------------- #

_NET_COMPONENT = "Stabler Net Pay"


def _ensure_net_component() -> str:
	"""Return the single Earning component used to carry the engine's net pay,
	creating it once if missing so there is zero manual setup."""
	if frappe.db.exists("Salary Component", _NET_COMPONENT):
		return _NET_COMPONENT
	frappe.get_doc(
		{
			"doctype": "Salary Component",
			"salary_component": _NET_COMPONENT,
			"type": "Earning",
			"description": "Net pay computed in Stabler and pushed as a single figure.",
		}
	).insert(ignore_permissions=True)
	return _NET_COMPONENT


def _engine_net(summary_name: str) -> float:
	"""Net pay from the Stabler payroll engine for this summary."""
	from frappe.utils import flt

	from stabler.api.hr_pay import preview_payroll_pay

	return flt(preview_payroll_pay(summary_name).get("net"))


@frappe.whitelist()
def emit_payroll_net(summary_name: str) -> dict:
	"""Push the engine's net pay to ERPNext as a SINGLE Additional Salary line.

	Stabler does all the calculation; ERPNext only records the final figure. The
	period must be Locked. Idempotent: replaces any previously Stabler-generated
	Additional Salary rows for this employee + period (itemized or net), so the
	slot always holds exactly one net line.
	"""
	_require_auth()
	_assert_can_write(_SUMMARY, summary_name)
	summary = _load_summary(summary_name)
	_assert_company_scope(summary["company"])
	if summary["status"] != "Locked":
		frappe.throw(
			_("Lock the payroll period before pushing net pay. Summary {0} is '{1}'.").format(
				summary_name, summary["status"]
			),
			frappe.ValidationError,
		)

	from frappe.utils import flt

	net = flt(_engine_net(summary_name))
	employee = summary["employee"]
	company = summary["company"]
	period = summary["payroll_period"]

	# Idempotency: clear any prior Stabler rows (itemized OR net) for this slot.
	_delete_stabler_additional_salaries(employee, period, company)
	if not net:
		return {"net": 0.0, "additional_salary": None, "salary_component": None}

	component = _ensure_net_component()
	doc = frappe.get_doc(
		{
			"doctype": _ADDITIONAL_SALARY,
			"employee": employee,
			"company": company,
			"salary_component": component,
			"type": "Earning" if net >= 0 else "Deduction",
			"amount": abs(net),
			"payroll_date": _payroll_date_from_period(period),
			"overwrite_salary_structure_amount": 1,
			"remarks": _STABLER_MARKER,
		}
	).insert(ignore_permissions=False)
	frappe.db.commit()
	return {"net": net, "additional_salary": doc.name, "salary_component": component}


@frappe.whitelist()
def emit_payroll_net_period(company: str, payroll_period: str) -> dict:
	"""Push net pay for EVERY locked summary in a period (bulk one-click)."""
	_require_auth()
	_assert_company_scope(company)
	names = frappe.get_all(
		_SUMMARY,
		filters={"company": company, "payroll_period": payroll_period, "status": "Locked"},
		pluck="name",
		limit=0,
	)
	pushed = 0
	total = 0.0
	errors = []
	for name in names:
		try:
			r = emit_payroll_net(name)
			pushed += 1
			total += float(r.get("net") or 0)
		except Exception as e:  # noqa: BLE001 — collect per-row failures, keep going
			errors.append({"summary": name, "error": str(e)})
	return {"pushed": pushed, "skipped_unlocked": 0, "net_total": round(total), "errors": errors}


# ---------------------------------------------------------------------------
# validate_against_slip
# ---------------------------------------------------------------------------

@frappe.whitelist()
def validate_against_slip(summary_name: str, salary_slip: str) -> dict:
	"""Compare a summary-derived net against a Salary Slip net.

	Permission: read on both Stabler Payroll Attendance Summary and Salary Slip.
	READ-ONLY.

	Used as a parallel-run gate: if ``within_tolerance`` is True the summary
	and slip agree within ±1000 UZS and the period may be accepted.

	Args:
		summary_name: name of a Stabler Payroll Attendance Summary.
		salary_slip:  name of an ERPNext Salary Slip for the same employee+period.

	Returns::

		{
		    "summary_net":      float,
		    "slip_net":         float,
		    "variance":         float,   # slip_net − summary_net
		    "within_tolerance": bool,    # abs(variance) <= 1000 UZS
		}
	"""
	_require_auth()
	_assert_can_read(_SUMMARY, summary_name)
	_assert_can_read(_SALARY_SLIP, salary_slip)

	summary = _load_summary(summary_name)
	_assert_company_scope(summary["company"])

	# Fetch the Salary Slip net_pay.
	slip_rows = frappe.get_all(
		_SALARY_SLIP,
		filters={"name": salary_slip},
		fields=["name", "net_pay", "employee", "company"],
		limit_page_length=1,
	)
	if not slip_rows:
		frappe.throw(
			_("Salary Slip {0} not found.").format(salary_slip),
			frappe.DoesNotExistError,
		)
	slip_row = slip_rows[0]

	# Company-scope guard on the slip as well.
	_assert_company_scope(slip_row["company"])

	component_map = _component_map_for(summary["company"])
	lines = summary_to_components(summary, component_map)
	totals = components_total(lines)
	summary_net = totals["net"]

	slip_net = float(slip_row.get("net_pay") or 0)
	variance_result = slip_variance(summary_net, slip_net)

	return {
		"summary_net": summary_net,
		"slip_net": slip_net,
		"variance": variance_result["variance"],
		"within_tolerance": variance_result["within_tolerance"],
	}
