"""Payroll-readiness dashboard and period-lock endpoints.

Endpoints (all reject Guest; check frappe.has_permission; consistent dict
envelopes; frappe.get_all with explicit fields):

  attendance_dashboard(company, date=None)   — daily attendance counts + open
                                               exceptions/corrections. READ-ONLY.
  list_payroll_summaries(company, ...)       — list Stabler Payroll Attendance
                                               Summary rows, newest period first.
  period_readiness(company, payroll_period)  — thin wrapper → can_lock/blockers.
                                               READ-ONLY.
  lock_period(company, payroll_period)       — set summaries to Locked; throws if
                                               blockers exist.

``generate_period_summaries`` creates or refreshes Draft/Ready summary rows;
``lock_period`` locks existing rows once readiness blockers are clear.
"""

from __future__ import annotations

import calendar
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, now_datetime

from stabler.api._attendance_processor import summarize_day
from stabler.api._attendance_rules import policies_from_ruleset
from stabler.api._payroll_summary import rollup_month
from stabler.api.approvals import _assert_company_scope

_SUMMARY = "Stabler Payroll Attendance Summary"
_EXCEPTION = "Stabler Attendance Exception"
_CORRECTION = "Stabler Attendance Correction Request"
_ATTENDANCE = "Attendance"
_CHECKIN = "Employee Checkin"
_RULESET = "Stabler Attendance Rule Set"

# Roles allowed to lock payroll periods (beyond generic write-on-summary).
_LOCK_ROLES = ("HR Manager", "System Manager", "Stabler Admin")


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------

def _require_auth() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)


def _guard_read() -> None:
	"""Require auth + read permission on the summary doctype."""
	_require_auth()
	if not frappe.has_permission(_SUMMARY, "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _require_lock_role() -> None:
	"""Require auth + write on summary + a locking role."""
	_require_auth()
	if not frappe.has_permission(_SUMMARY, "write"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	roles = frappe.get_roles()
	if not any(r in roles for r in _LOCK_ROLES):
		frappe.throw(
			_("You must hold an HR Manager, System Manager, or Stabler Admin role to lock a payroll period."),
			frappe.PermissionError,
		)


def _parse_limit(raw, default: int = 200, cap: int = 500) -> int:
	try:
		return min(int(raw), cap)
	except (TypeError, ValueError):
		return default


def _period_date_range(payroll_period: str):
	"""Return (start_date, end_date) strings for a payroll period name.

	Tries the ERPNext Payroll Period doctype first; falls back to a
	"YYYY-MM" string parse so the endpoint works without payroll setup.
	Returns (None, None) if the period cannot be resolved.
	"""
	period_start = None
	period_end = None

	if (
		frappe.db.exists("DocType", "Payroll Period")
		and frappe.db.exists("Payroll Period", payroll_period)
	):
		period_start, period_end = frappe.db.get_value(
			"Payroll Period", payroll_period, ["start_date", "end_date"]
		)

	if not period_start and len(payroll_period) == 7:
		# Fallback: treat as "YYYY-MM"
		try:
			y, m = payroll_period.split("-")
			period_start = f"{y}-{m}-01"
			last_day = calendar.monthrange(int(y), int(m))[1]
			period_end = f"{y}-{m}-{last_day:02d}"
		except Exception:
			pass

	return period_start, period_end


def _period_days(payroll_period: str) -> list[str]:
	period_start, period_end = _period_date_range(payroll_period)
	if not period_start or not period_end:
		frappe.throw(_("Could not resolve payroll period: {0}").format(payroll_period))
	start = getdate(period_start)
	end = getdate(period_end)
	if end < start:
		frappe.throw(_("Payroll period end date cannot be before start date."))
	days = []
	current = start
	while current <= end:
		days.append(str(current))
		current += timedelta(days=1)
	return days


def _active_employees(company: str, period_start: str, period_end: str) -> list[dict]:
	rows = frappe.get_all(
		"Employee",
		filters={"company": company, "status": "Active"},
		fields=["name", "employee_name", "date_of_joining", "relieving_date", "default_shift", "holiday_list"],
		order_by="employee_name asc",
		limit_page_length=10000,
	)
	employees = []
	for row in rows:
		joined = str(row.get("date_of_joining") or period_start)
		relieved = str(row.get("relieving_date") or "")
		if joined > period_end:
			continue
		if relieved and relieved < period_start:
			continue
		employees.append(row)
	return employees


def _ruleset(company: str) -> dict:
	name = frappe.db.get_value(
		_RULESET,
		{"company": company, "enabled": 1, "is_default": 1},
		"name",
	)
	if not name:
		name = frappe.db.get_value(_RULESET, {"enabled": 1, "is_default": 1}, "name")
	return frappe.get_doc(_RULESET, name).as_dict() if name else {}


def _hm(value) -> str | None:
	if value is None:
		return None
	text = str(value)
	if " " in text:
		text = text.split(" ", 1)[1]
	return text[:5] if len(text) >= 5 else None


def _shift_context(employee: dict) -> dict:
	shift_type = employee.get("default_shift")
	shift_start = "09:00"
	shift_label = "DAY"
	if shift_type and frappe.db.exists("Shift Type", shift_type):
		shift = frappe.get_doc("Shift Type", shift_type)
		shift_start = _hm(shift.start_time) or "09:00"
		if int(shift_start.split(":", 1)[0]) >= 18:
			shift_label = "NIGHT"
	return {"shift_type": shift_type, "shift_start_hm": shift_start, "shift": shift_label}


def _checkin_punches(employee: str, date: str) -> list[dict]:
	rows = frappe.get_all(
		_CHECKIN,
		filters={
			"employee": employee,
			"time": ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]],
		},
		fields=["time", "log_type"],
		order_by="time asc",
		limit_page_length=100,
	)
	return [
		{"timestamp": str(row["time"]).replace(" ", "T"), "type": row.get("log_type") or "UNKNOWN"}
		for row in rows
	]


def _attendance_status_summary(status: str | None, date: str, late_min=0, early_min=0, overtime_min=0) -> dict:
	normalized = (status or "").lower()
	if normalized in ("present", "work from home"):
		mapped = "present"
	elif normalized == "half day":
		mapped = "half_day"
	elif normalized == "on leave":
		mapped = "holiday"
	else:
		mapped = "absent"
	lm = int(late_min or 0)
	em = int(early_min or 0)
	ot = int(overtime_min or 0)
	return {
		"date": date,
		"entry": None,
		"exit": None,
		"punch_count": 0,
		"worked_min": 0,
		"status": mapped,
		"late_min": lm,
		"late_fee_uzs": 0.0,
		"early_leave_min": em,
		"overtime_min": ot,
		"is_night": False,
		"exceptions": [],
		"payroll_impacting": mapped in ("half_day", "absent") or lm > 0 or ot > 0,
	}


def _daily_summaries(employee: dict, company: str, days: list[str]) -> list[dict]:
	late, night, half, min_worked = policies_from_ruleset(_ruleset(company))
	shift = _shift_context(employee)
	hire_date = str(employee.get("date_of_joining") or days[0])
	termination_date = str(employee.get("relieving_date")) if employee.get("relieving_date") else None
	att_min_cols = [c for c in ("custom_late_minutes", "custom_early_minutes", "custom_overtime_minutes") if frappe.db.has_column(_ATTENDANCE, c)]
	summaries = []
	for date in days:
		attendance = frappe.db.get_value(
			_ATTENDANCE,
			{"employee": employee["name"], "attendance_date": date, "company": company, "docstatus": ["<", 2]},
			["status"] + att_min_cols,
			as_dict=True,
		)
		punches = _checkin_punches(employee["name"], date)
		if punches:
			summaries.append(
				summarize_day(
					punches,
					shift=shift["shift"],
					shift_start_hm=shift["shift_start_hm"],
					is_holiday=False,
					date_str=date,
					hire_date=hire_date,
					termination_date=termination_date,
					late=late,
					half=half,
					night=night,
					min_worked_present=min_worked,
				)
			)
		elif attendance:
			summaries.append(
				_attendance_status_summary(
					attendance.get("status"),
					date,
					attendance.get("custom_late_minutes"),
					attendance.get("custom_early_minutes"),
					attendance.get("custom_overtime_minutes"),
				)
			)
	return summaries


def _employee_period_count(
	doctype: str,
	employee: str,
	date_field: str,
	period_start: str,
	period_end: str,
	extra: dict,
) -> int:
	filters = {"employee": employee, date_field: ["between", [period_start, period_end]], **extra}
	return frappe.db.count(doctype, filters)


def _upsert_summary(employee: dict, company: str, payroll_period: str, period_start: str, period_end: str, rollup: dict) -> str | None:
	existing = frappe.db.get_value(
		_SUMMARY,
		{"employee": employee["name"], "payroll_period": payroll_period},
		["name", "status"],
		as_dict=True,
	)
	if existing and existing.get("status") == "Locked":
		return None

	doc = frappe.get_doc(_SUMMARY, existing["name"]) if existing else frappe.new_doc(_SUMMARY)
	doc.employee = employee["name"]
	doc.payroll_period = payroll_period
	doc.company = company
	doc.present_days = rollup["present_days"]
	doc.absent_days = rollup["absent_days"]
	doc.half_days = rollup["half_days"]
	doc.paid_leave_days = rollup["holiday_days"]
	doc.unpaid_leave_days = 0
	doc.late_count = rollup["late_count"]
	doc.late_minutes = rollup["late_minutes"]
	doc.late_deduction_amount = rollup["late_deduction_amount"]
	doc.early_leave_minutes = rollup["early_leave_minutes"]
	doc.overtime_minutes = rollup["overtime_minutes"]
	doc.night_minutes = rollup["night_minutes"]
	doc.unresolved_exceptions_count = _employee_period_count(
		_EXCEPTION,
		employee["name"],
		"exception_date",
		period_start,
		period_end,
		{"status": "Open"},
	)
	doc.approved_corrections_count = _employee_period_count(
		_CORRECTION,
		employee["name"],
		"correction_date",
		period_start,
		period_end,
		{"status": "Applied"},
	)
	doc.status = "Ready"
	doc.save(ignore_permissions=False)
	return doc.name


@frappe.whitelist()
def generate_period_summaries(company: str, payroll_period: str) -> dict:
	"""Generate or refresh Draft/Ready Payroll Attendance Summary rows."""
	_require_auth()
	if not frappe.has_permission(_SUMMARY, "write"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)
	if not payroll_period:
		frappe.throw(_("payroll_period is required."))

	days = _period_days(payroll_period)
	period_start = days[0]
	period_end = days[-1]
	employees = _active_employees(company, period_start, period_end)

	generated = []
	locked_skipped = 0
	for employee in employees:
		rollup = rollup_month(_daily_summaries(employee, company, days))
		name = _upsert_summary(employee, company, payroll_period, period_start, period_end, rollup)
		if name:
			generated.append(name)
		else:
			locked_skipped += 1

	frappe.db.commit()
	return {
		"payroll_period": payroll_period,
		"employees": len(employees),
		"generated": len(generated),
		"locked_skipped": locked_skipped,
		"summaries": generated,
	}


# ---------------------------------------------------------------------------
# attendance_dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def attendance_dashboard(company: str, date: str | None = None) -> dict:
	"""Daily attendance snapshot for a given date (default today).

	READ-ONLY. Counts from ERPNext Attendance for the day, plus open-exception
	and pending-correction aggregates from Stabler doctypes.

	Returns:
	  {
	    "date": "YYYY-MM-DD",
	    "present": int,
	    "absent": int,
	    "late": int,
	    "on_leave": int,
	    "total_marked": int,
	    "open_exceptions": int,
	    "exceptions_by_type": {"<type>": int, ...},
	    "pending_corrections": int,
	    "payroll_impacting_pending": int,
	  }
	"""
	_guard_read()

	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)

	target_date = (date or "").strip() or nowdate()

	# --- ERPNext Attendance counts by status for company + date ---
	# Fetch all attendance rows for the day; aggregate in Python to avoid
	# GROUP BY SQL that would need frappe.db.sql.
	att_rows = frappe.get_all(
		_ATTENDANCE,
		filters={"company": company, "attendance_date": target_date},
		fields=["status"],
	)

	present = 0
	absent = 0
	late = 0
	on_leave = 0
	for row in att_rows:
		s = (row.get("status") or "").lower()
		if s in ("present", "work from home"):
			present += 1
		elif s == "absent":
			absent += 1
		elif s == "half day":
			# ERPNext Half Day counts as a partial presence; bucket to present
			# for dashboard purposes (matches typical HR expectation).
			present += 1
		elif s == "on leave":
			on_leave += 1

	total_marked = len(att_rows)

	# Late is derived from Stabler Attendance Exception type "late" for that date,
	# since ERPNext Attendance has no native "late" status — it's a Stabler concept.
	late_exc_rows = frappe.get_all(
		_EXCEPTION,
		filters={
			"company": company,
			"exception_date": target_date,
			"exception_type": "late",
		},
		fields=["name"],
	)
	late = len(late_exc_rows)

	# --- Open exceptions (all types) for the company on this date ---
	exc_rows = frappe.get_all(
		_EXCEPTION,
		filters={"company": company, "status": "Open", "exception_date": target_date},
		fields=["exception_type"],
	)
	open_exceptions = len(exc_rows)
	exceptions_by_type: dict = {}
	for row in exc_rows:
		et = row.get("exception_type") or "unknown"
		exceptions_by_type[et] = exceptions_by_type.get(et, 0) + 1

	# --- Pending corrections ---
	corr_filters_base = {"company": company, "status": "Pending", "correction_date": target_date}
	pending_rows = frappe.get_all(
		_CORRECTION,
		filters=corr_filters_base,
		fields=["payroll_impact"],
	)
	pending_corrections = len(pending_rows)
	payroll_impacting_pending = sum(1 for r in pending_rows if r.get("payroll_impact"))

	return {
		"date": target_date,
		"present": present,
		"absent": absent,
		"late": late,
		"on_leave": on_leave,
		"total_marked": total_marked,
		"open_exceptions": open_exceptions,
		"exceptions_by_type": exceptions_by_type,
		"pending_corrections": pending_corrections,
		"payroll_impacting_pending": payroll_impacting_pending,
	}


# ---------------------------------------------------------------------------
# list_payroll_summaries
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_payroll_summaries(
	company: str,
	payroll_period: str = "",
	status: str = "",
	limit: int | str = 200,
) -> dict:
	"""List Stabler Payroll Attendance Summary rows, newest period first.

	Optional filters: payroll_period, status (Draft / Ready / Locked).

	Returns:
	  {
	    "summaries": [
	      {
	        "name", "employee", "employee_name", "payroll_period", "company",
	        "present_days", "absent_days", "late_count",
	        "late_deduction_amount", "overtime_minutes",
	        "unresolved_exceptions_count", "status", "locked_at",
	      }, ...
	    ],
	    "total": int,
	  }
	"""
	_guard_read()

	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)

	limit = _parse_limit(limit)

	filters: dict = {"company": company}
	if payroll_period:
		filters["payroll_period"] = payroll_period
	if status:
		filters["status"] = status

	rows = frappe.get_all(
		_SUMMARY,
		filters=filters,
		fields=[
			"name",
			"employee",
			"employee_name",
			"payroll_period",
			"company",
			"present_days",
			"absent_days",
			"late_count",
			"late_deduction_amount",
			"overtime_minutes",
			"unresolved_exceptions_count",
			"status",
			"locked_at",
		],
		order_by="payroll_period desc, employee_name asc",
		limit_page_length=limit,
	)
	total = frappe.db.count(_SUMMARY, filters)

	# Enrich for the anjan-hr-style attendance summary table: department,
	# designation, and a discipline ratio (present / (present + absent)).
	emp_ids = list({r["employee"] for r in rows if r.get("employee")})
	emp_meta = {}
	if emp_ids:
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", emp_ids]},
			fields=["name", "department", "designation"],
		):
			emp_meta[e["name"]] = e
	for r in rows:
		m = emp_meta.get(r.get("employee"), {})
		r["department"] = m.get("department")
		r["designation"] = m.get("designation")
		present = float(r.get("present_days") or 0)
		absent = float(r.get("absent_days") or 0)
		r["discipline"] = round(present / (present + absent), 4) if (present + absent) > 0 else None

	return {"summaries": rows, "total": total}


# ---------------------------------------------------------------------------
# period_readiness
# ---------------------------------------------------------------------------

@frappe.whitelist()
def period_readiness(company: str, payroll_period: str) -> dict:
	"""Read-only pre-lock check — delegates to hr_corrections.period_lock_readiness.

	Thin wrapper so the SPA has a single canonical readiness endpoint under
	the hr_payroll module boundary.

	Returns:
	  {
	    "can_lock": bool,
	    "blockers": [{"code": str, "message": str, "count": int}, ...],
	    "summary_count": int,
	    "ctx": {
	      "open_punch_days": int,
	      "unresolved_exceptions": int,
	      "pending_corrections": int,
	      "employees_without_summary": int,
	      "already_locked": bool,
	    },
	  }
	"""
	_guard_read()

	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)

	if not payroll_period:
		frappe.throw(_("payroll_period is required."))

	# Delegate to the canonical readiness implementation in hr_corrections.
	# Import inline to avoid circular imports at module load time.
	from stabler.api.hr_corrections import period_lock_readiness as _plr

	readiness = _plr(company=company, payroll_period=payroll_period)

	# Append a summary_count so the SPA can display "N summaries will be locked".
	summary_count = frappe.db.count(
		_SUMMARY,
		{"company": company, "payroll_period": payroll_period},
	)

	return {
		"can_lock": readiness["can_lock"],
		"blockers": readiness["blockers"],
		"summary_count": summary_count,
		"ctx": readiness["ctx"],
	}


# ---------------------------------------------------------------------------
# lock_period
# ---------------------------------------------------------------------------

@frappe.whitelist()
def lock_period(company: str, payroll_period: str) -> dict:
	"""Lock all Draft/Ready summaries for a payroll period.

	Permission: caller must hold write on Stabler Payroll Attendance Summary
	AND one of (HR Manager / System Manager / Stabler Admin).

	Pre-condition: period_readiness.can_lock must be True.  If blockers exist
	this endpoint raises frappe.ValidationError listing them — it does NOT lock.

	Action: for every Stabler Payroll Attendance Summary with
	  company == company AND payroll_period == payroll_period
	  AND status in ("Draft", "Ready")
	sets status = "Locked", locked_by = session user, locked_at = now,
	then saves (ignore_permissions=False) and commits.

	Returns:
	  {"locked": int, "payroll_period": str}

	TODO (Phase-3 generator): generating Stabler Payroll Attendance Summary
	rows from raw Attendance / Employee Checkin data is a separate Phase-3
	task that requires a live bench with the attendance processor.  This
	endpoint only locks *existing* summary rows; if no summaries exist for
	the period it will lock zero rows (and period_readiness will have already
	blocked via missing_summaries blocker if employees_without_summary > 0).
	"""
	_require_lock_role()

	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)

	if not payroll_period:
		frappe.throw(_("payroll_period is required."))

	# --- Pre-lock readiness gate ---
	# Re-use the canonical readiness logic from hr_corrections.
	from stabler.api.hr_corrections import period_lock_readiness as _plr
	from stabler.api._payroll_summary import period_blockers, can_lock

	readiness = _plr(company=company, payroll_period=payroll_period)

	if not readiness["can_lock"]:
		blocker_lines = "; ".join(
			b["message"] for b in readiness["blockers"]
		)
		frappe.throw(
			_("Cannot lock period — resolve the following blockers first: {0}").format(
				blocker_lines
			),
			frappe.ValidationError,
		)

	# --- Fetch summaries to lock ---
	to_lock = frappe.get_all(
		_SUMMARY,
		filters={
			"company": company,
			"payroll_period": payroll_period,
			"status": ["in", ["Draft", "Ready"]],
		},
		fields=["name"],
	)

	locked_count = 0
	locked_by = frappe.session.user
	locked_at = now_datetime()

	for row in to_lock:
		doc = frappe.get_doc(_SUMMARY, row["name"])
		doc.status = "Locked"
		doc.locked_by = locked_by
		doc.locked_at = locked_at
		doc.save(ignore_permissions=False)
		locked_count += 1

	if locked_count:
		frappe.db.commit()

	return {"locked": locked_count, "payroll_period": payroll_period}
