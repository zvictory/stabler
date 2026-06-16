"""HR module — Employees, Attendance, Leave, Payroll basics."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, getdate, today, add_days, date_diff


from stabler.api._common import _require_company, _assert_can_read, _assert_can_write


# ---------------------------------------------------------------------------
# Salary-visibility helper
# ---------------------------------------------------------------------------

#: Roles whose holders may read/write salary-sensitive fields.
_PAYROLL_VISIBLE_ROLES = frozenset(
	("Accounts Manager", "Payroll Manager", "HR Manager", "System Manager")
)

#: Fields masked for non-payroll-visible users.
SALARY_FIELDS = frozenset(("custom_base_salary", "custom_allowance_config"))

#: All native + custom employee fields surfaced by Stabler.
_EMPLOYEE_NATIVE_FIELDS = (
	"employee_name",
	"image",
	"department",
	"designation",
	"date_of_joining",
	"relieving_date",
	"status",
	"cell_number",
	"company",
)

_EMPLOYEE_CUSTOM_FIELDS = (
	"custom_timepay_id",
	"custom_timepay_name",
	"custom_base_salary",
	"custom_shift_class",
	"custom_region",
	"custom_work_mode",
	"custom_stake_coefficient",
	"custom_heavy_conditions",
	"custom_additional_duties",
	"custom_allowance_config",
)

#: All writable field names (whitelist for update_employee).
_EMPLOYEE_WRITABLE_FIELDS = frozenset(
	_EMPLOYEE_NATIVE_FIELDS + _EMPLOYEE_CUSTOM_FIELDS
)

#: Enum validators for custom fields.
_VALID_SHIFT_CLASS = frozenset(("DAY", "NIGHT", "OFFICE", "LIGHT"))
_VALID_REGION = frozenset(("CITY", "DISTRICT", "FAR_DISTRICT", "NO_TRAVEL"))
_VALID_WORK_MODE = frozenset(("SHIFT_8H", "SHIFT_12H", "HALF_RATE", "FLEXIBLE", "REMOTE"))


def _user_can_see_salary(user: str | None = None) -> bool:
	"""Return True when the session/given user holds a payroll-visible role."""
	user = user or frappe.session.user
	if user in ("Administrator",):
		return True
	from stabler.api.organization import _ADMIN_ROLES
	roles = set(frappe.get_roles(user))
	return bool(roles & (_PAYROLL_VISIBLE_ROLES | set(_ADMIN_ROLES)))


def _parse_items(items):
	if items is None:
		return []
	if isinstance(items, str):
		try:
			return json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload (expected JSON).")
	return list(items)


# ----- Employees -----------------------------------------------------------


@frappe.whitelist()
def list_employees(company: str, search: str = "", status: str = "", limit: int = 100):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	if search:
		conds.append(
			"(name LIKE %(s)s OR employee_name LIKE %(s)s OR cell_number LIKE %(s)s OR user_id LIKE %(s)s)"
		)
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, employee_name, status, designation, department,
		       date_of_joining, cell_number, user_id, image, gender
		FROM `tabEmployee`
		WHERE {where}
		ORDER BY status='Active' DESC, employee_name
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def employee_detail(name: str):
	_assert_can_read("Employee", name)
	if not name or not frappe.db.exists("Employee", name):
		frappe.throw(f"Unknown employee: {name}")
	doc = frappe.get_doc("Employee", name)
	can_see_salary = _user_can_see_salary()
	payload = {
		# Core identity
		"name": doc.name,
		"employee_name": doc.employee_name,
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"status": doc.status,
		"company": doc.company,
		"image": getattr(doc, "image", None),
		# Role / org
		"department": doc.department,
		"designation": doc.designation,
		# Dates
		"date_of_birth": doc.date_of_birth,
		"date_of_joining": doc.date_of_joining,
		"relieving_date": getattr(doc, "relieving_date", None),
		# Contact
		"gender": doc.gender,
		"cell_number": doc.cell_number,
		"personal_email": getattr(doc, "personal_email", None),
		"company_email": getattr(doc, "company_email", None),
		"user_id": doc.user_id,
		# Misc
		"holiday_list": doc.holiday_list,
		"employment_type": getattr(doc, "employment_type", None),
		# Custom — identity / integration
		"custom_timepay_id": getattr(doc, "custom_timepay_id", None),
		"custom_timepay_name": getattr(doc, "custom_timepay_name", None),
		# Custom — work configuration
		"custom_shift_class": getattr(doc, "custom_shift_class", None),
		"custom_region": getattr(doc, "custom_region", None),
		"custom_work_mode": getattr(doc, "custom_work_mode", None),
		"custom_stake_coefficient": flt(getattr(doc, "custom_stake_coefficient", 1.0)),
		"custom_heavy_conditions": int(getattr(doc, "custom_heavy_conditions", 0) or 0),
		"custom_additional_duties": int(getattr(doc, "custom_additional_duties", 0) or 0),
		# Custom — salary (masked for non-payroll roles)
		"custom_base_salary": flt(getattr(doc, "custom_base_salary", 0)) if can_see_salary else None,
		"custom_allowance_config": getattr(doc, "custom_allowance_config", None) if can_see_salary else None,
	}
	return payload


@frappe.whitelist()
def create_employee(
	company: str,
	first_name: str,
	last_name: str = "",
	gender: str = "",
	date_of_birth: str = "",
	date_of_joining: str = "",
	designation: str = "",
	department: str = "",
	cell_number: str = "",
	user_id: str = "",
	# Custom fields (all optional)
	custom_timepay_id: str = "",
	custom_timepay_name: str = "",
	custom_shift_class: str = "",
	custom_region: str = "",
	custom_work_mode: str = "",
	custom_stake_coefficient: float = 1.0,
	custom_heavy_conditions: int = 0,
	custom_additional_duties: int = 0,
	custom_base_salary: float = 0.0,
	custom_allowance_config: str = "",
):
	_require_company(company)
	if not first_name:
		frappe.throw("First name is required.")
	if not gender:
		frappe.throw("Gender is required.")
	if not date_of_birth:
		frappe.throw("Date of birth is required.")
	if not date_of_joining:
		date_of_joining = today()

	# Validate custom enums
	if custom_shift_class and custom_shift_class not in _VALID_SHIFT_CLASS:
		frappe.throw(f"Invalid custom_shift_class: {custom_shift_class}. Must be one of {sorted(_VALID_SHIFT_CLASS)}.")
	if custom_region and custom_region not in _VALID_REGION:
		frappe.throw(f"Invalid custom_region: {custom_region}. Must be one of {sorted(_VALID_REGION)}.")
	if custom_work_mode and custom_work_mode not in _VALID_WORK_MODE:
		frappe.throw(f"Invalid custom_work_mode: {custom_work_mode}. Must be one of {sorted(_VALID_WORK_MODE)}.")

	# Validate stake_coefficient
	coeff = flt(custom_stake_coefficient or 1.0)
	if custom_work_mode != "HALF_RATE":
		coeff = 1.0
	elif not (0.1 <= coeff <= 2.0):
		frappe.throw("custom_stake_coefficient must be between 0.1 and 2.0.")

	# Validate allowance_config JSON if provided
	if custom_allowance_config:
		try:
			json.loads(custom_allowance_config)
		except Exception:
			frappe.throw("custom_allowance_config must be valid JSON.")

	# Salary fields — only payroll-visible users may set them
	can_see_salary = _user_can_see_salary()

	doc = frappe.new_doc("Employee")
	doc.company = company
	doc.first_name = first_name
	doc.last_name = last_name or ""
	doc.gender = gender
	doc.date_of_birth = getdate(date_of_birth)
	doc.date_of_joining = getdate(date_of_joining)
	doc.status = "Active"
	if designation:
		doc.designation = designation
	if department:
		doc.department = department
	if cell_number:
		doc.cell_number = cell_number
	if user_id:
		doc.user_id = user_id
	# Custom fields
	if custom_timepay_id:
		doc.custom_timepay_id = custom_timepay_id
	if custom_timepay_name:
		doc.custom_timepay_name = custom_timepay_name
	if custom_shift_class:
		doc.custom_shift_class = custom_shift_class
	if custom_region:
		doc.custom_region = custom_region
	if custom_work_mode:
		doc.custom_work_mode = custom_work_mode
	doc.custom_stake_coefficient = coeff
	doc.custom_heavy_conditions = int(custom_heavy_conditions or 0)
	doc.custom_additional_duties = int(custom_additional_duties or 0)
	if can_see_salary:
		if flt(custom_base_salary):
			doc.custom_base_salary = flt(custom_base_salary)
		if custom_allowance_config:
			doc.custom_allowance_config = custom_allowance_config
	doc.insert()
	return {"name": doc.name, "employee_name": doc.employee_name}


@frappe.whitelist()
def update_employee(name: str, payload=None):
	"""Update an existing Employee record.

	Parameters
	----------
	name:
		Employee docname (e.g. ``"HR-EMP-00001"``).
	payload:
		Dict (or JSON string) of fields to update.  Only fields in the
		explicit whitelist are applied; arbitrary keys are silently ignored.
		Salary fields (``custom_base_salary``, ``custom_allowance_config``)
		are silently ignored unless the caller holds a payroll-visible role.

	Returns
	-------
	``{"name": doc.name}``
	"""
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	_assert_can_write("Employee", name, "write")
	if not name or not frappe.db.exists("Employee", name):
		frappe.throw(f"Unknown employee: {name}")

	# Normalise payload
	if payload is None:
		payload = {}
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw("payload must be a valid JSON object.")
	if not isinstance(payload, dict):
		frappe.throw("payload must be a JSON object.")

	can_see_salary = _user_can_see_salary()

	# Validate enum fields if present in payload
	shift_class = payload.get("custom_shift_class")
	if shift_class is not None and shift_class not in _VALID_SHIFT_CLASS:
		frappe.throw(f"Invalid custom_shift_class: {shift_class}. Must be one of {sorted(_VALID_SHIFT_CLASS)}.")

	region = payload.get("custom_region")
	if region is not None and region not in _VALID_REGION:
		frappe.throw(f"Invalid custom_region: {region}. Must be one of {sorted(_VALID_REGION)}.")

	work_mode = payload.get("custom_work_mode")
	if work_mode is not None and work_mode not in _VALID_WORK_MODE:
		frappe.throw(f"Invalid custom_work_mode: {work_mode}. Must be one of {sorted(_VALID_WORK_MODE)}.")

	# Validate stake_coefficient
	if "custom_stake_coefficient" in payload:
		# Determine effective work_mode: either from payload or from DB
		effective_work_mode = work_mode
		if effective_work_mode is None:
			effective_work_mode = frappe.db.get_value("Employee", name, "custom_work_mode")
		coeff = flt(payload["custom_stake_coefficient"])
		if effective_work_mode != "HALF_RATE":
			# Force 1.0 for non-HALF_RATE modes
			payload["custom_stake_coefficient"] = 1.0
		elif not (0.1 <= coeff <= 2.0):
			frappe.throw("custom_stake_coefficient must be between 0.1 and 2.0.")
	elif work_mode is not None and work_mode != "HALF_RATE":
		# Changing work_mode away from HALF_RATE resets coefficient to 1.0
		payload["custom_stake_coefficient"] = 1.0

	# Validate custom_allowance_config JSON
	if "custom_allowance_config" in payload and payload["custom_allowance_config"]:
		try:
			json.loads(payload["custom_allowance_config"])
		except Exception:
			frappe.throw("custom_allowance_config must be valid JSON.")

	# Apply whitelisted fields only
	doc = frappe.get_doc("Employee", name)
	for field, value in payload.items():
		if field not in _EMPLOYEE_WRITABLE_FIELDS:
			continue
		if field in SALARY_FIELDS and not can_see_salary:
			continue
		setattr(doc, field, value)

	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def list_designations(search: str = "", limit: int = 50):
	conds = []
	params: dict = {"limit": int(limit)}
	if search:
		conds.append("name LIKE %(s)s")
		params["s"] = f"%{search}%"
	where = (" WHERE " + " AND ".join(conds)) if conds else ""
	return frappe.db.sql(
		f"SELECT name FROM `tabDesignation`{where} ORDER BY name LIMIT %(limit)s",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def list_departments(company: str = "", search: str = "", limit: int = 50):
	# Authn/authz: require the HR module (the rest of hr.py gates via
	# _require_company; this reader is company-optional so it needs its own
	# guard). Then scope by company: validate a passed company against the
	# caller's allowed set, and when omitted restrict a scoped non-admin to
	# their allowed companies (global / NULL-company departments stay visible).
	from stabler.api.organization import (
		_ADMIN_ROLES,
		_can_access_module,
		_user_allowed_companies,
	)

	if not _can_access_module(frappe.session.user, "hr"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
	allowed = [] if is_admin else _user_allowed_companies(frappe.session.user)

	conds = []
	params: dict = {"limit": int(limit)}
	if company:
		if allowed and company not in allowed:
			frappe.throw(
				frappe._("Not permitted for company {0}").format(company), frappe.PermissionError
			)
		conds.append("(company = %(c)s OR company IS NULL OR company = '')")
		params["c"] = company
	elif allowed:
		conds.append("(company IN %(allowed)s OR company IS NULL OR company = '')")
		params["allowed"] = tuple(allowed)
	if search:
		conds.append("name LIKE %(s)s")
		params["s"] = f"%{search}%"
	where = (" WHERE " + " AND ".join(conds)) if conds else ""
	return frappe.db.sql(
		f"SELECT name FROM `tabDepartment`{where} ORDER BY name LIMIT %(limit)s",
		params,
		as_dict=True,
	)


# ----- Attendance ----------------------------------------------------------


@frappe.whitelist()
def list_attendance(
	company: str,
	from_date: str = "",
	to_date: str = "",
	employee: str = "",
	status: str = "",
	limit: int = 200,
):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("attendance_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("attendance_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if employee:
		conds.append("employee = %(employee)s")
		params["employee"] = employee
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, employee, employee_name, attendance_date, status,
		       in_time, out_time, working_hours, leave_type, docstatus
		FROM `tabAttendance`
		WHERE {where}
		ORDER BY attendance_date DESC, employee
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def mark_attendance(
	company: str,
	employee: str,
	attendance_date: str,
	status: str,
	in_time: str = "",
	out_time: str = "",
	submit: int = 1,
):
	_require_company(company)
	if not employee or not frappe.db.exists("Employee", employee):
		frappe.throw(f"Unknown employee: {employee}")
	if status not in ("Present", "Absent", "On Leave", "Half Day", "Work From Home"):
		frappe.throw(f"Invalid status: {status}")
	att_date = getdate(attendance_date or today())
	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": att_date, "docstatus": ("<", 2)},
		"name",
	)
	if existing:
		frappe.throw(f"Attendance already recorded for {employee} on {att_date} ({existing}).")

	doc = frappe.new_doc("Attendance")
	doc.company = company
	doc.employee = employee
	doc.attendance_date = att_date
	doc.status = status
	if in_time:
		doc.in_time = in_time
	if out_time:
		doc.out_time = out_time
	doc.insert()
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "status": doc.status, "docstatus": doc.docstatus}


# ----- Leave Applications --------------------------------------------------


@frappe.whitelist()
def list_leave_applications(
	company: str,
	status: str = "",
	employee: str = "",
	from_date: str = "",
	to_date: str = "",
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	if employee:
		conds.append("employee = %(employee)s")
		params["employee"] = employee
	if from_date:
		conds.append("from_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("to_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, employee, employee_name, leave_type, from_date, to_date,
		       total_leave_days, status, posting_date, docstatus, description
		FROM `tabLeave Application`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def list_leave_types(limit: int = 50):
	return frappe.db.sql(
		"SELECT name, max_continuous_days_allowed, is_lwp, allow_negative FROM `tabLeave Type` ORDER BY name LIMIT %(limit)s",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def create_leave_application(
	company: str,
	employee: str,
	leave_type: str,
	from_date: str,
	to_date: str,
	description: str = "",
	submit: int = 0,
):
	_require_company(company)
	if not employee or not frappe.db.exists("Employee", employee):
		frappe.throw(f"Unknown employee: {employee}")
	if not leave_type or not frappe.db.exists("Leave Type", leave_type):
		frappe.throw(f"Unknown leave type: {leave_type}")
	fd, td = getdate(from_date), getdate(to_date)
	if td < fd:
		frappe.throw("To date cannot be before from date.")

	doc = frappe.new_doc("Leave Application")
	doc.company = company
	doc.employee = employee
	doc.leave_type = leave_type
	doc.from_date = fd
	doc.to_date = td
	doc.posting_date = today()
	doc.status = "Open"
	if description:
		doc.description = description
	doc.insert()
	if int(submit or 0):
		doc.status = "Approved"
		doc.submit()
	return {"name": doc.name, "status": doc.status, "docstatus": doc.docstatus}


@frappe.whitelist()
def approve_leave(name: str, status: str = "Approved"):
	_assert_can_write("Leave Application", name, "submit")
	if not name or not frappe.db.exists("Leave Application", name):
		frappe.throw(f"Unknown leave application: {name}")
	if status not in ("Approved", "Rejected"):
		frappe.throw(f"Invalid status: {status}")
	doc = frappe.get_doc("Leave Application", name)
	if doc.docstatus == 1:
		frappe.throw("Already submitted.")
	doc.status = status
	if status == "Approved":
		doc.submit()
	else:
		doc.save()
	return {"name": doc.name, "status": doc.status, "docstatus": doc.docstatus}


# ----- Payroll -------------------------------------------------------------


@frappe.whitelist()
def list_salary_slips(
	company: str,
	from_date: str = "",
	to_date: str = "",
	employee: str = "",
	status: str = "",
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("start_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("end_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if employee:
		conds.append("employee = %(employee)s")
		params["employee"] = employee
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, employee, employee_name, posting_date, start_date, end_date,
		       total_working_days, payment_days, gross_pay, net_pay, currency,
		       status, docstatus
		FROM `tabSalary Slip`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def salary_slip_detail(name: str):
	_assert_can_read("Salary Slip", name)
	if not name or not frappe.db.exists("Salary Slip", name):
		frappe.throw(f"Unknown salary slip: {name}")
	doc = frappe.get_doc("Salary Slip", name)
	earnings = [
		{"component": r.salary_component, "amount": flt(r.amount)}
		for r in (doc.earnings or [])
	]
	deductions = [
		{"component": r.salary_component, "amount": flt(r.amount)}
		for r in (doc.deductions or [])
	]
	return {
		"name": doc.name,
		"employee": doc.employee,
		"employee_name": doc.employee_name,
		"posting_date": doc.posting_date,
		"start_date": doc.start_date,
		"end_date": doc.end_date,
		"company": doc.company,
		"currency": doc.currency,
		"total_working_days": flt(doc.total_working_days),
		"payment_days": flt(doc.payment_days),
		"gross_pay": flt(doc.gross_pay),
		"total_deduction": flt(doc.total_deduction),
		"net_pay": flt(doc.net_pay),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"earnings": earnings,
		"deductions": deductions,
	}


@frappe.whitelist()
def create_payroll_entry(
	company: str,
	start_date: str,
	end_date: str,
	posting_date: str = "",
	payroll_frequency: str = "Monthly",
	submit: int = 0,
):
	"""Create a Payroll Entry covering employees with salary structures.

	Returns the payroll entry name plus generated salary slip names.
	"""
	_require_company(company)
	fd, td = getdate(start_date), getdate(end_date)
	if td < fd:
		frappe.throw("End date cannot be before start date.")

	doc = frappe.new_doc("Payroll Entry")
	doc.company = company
	doc.start_date = fd
	doc.end_date = td
	doc.posting_date = getdate(posting_date or today())
	doc.payroll_frequency = payroll_frequency

	# Frappe will pull eligible employees via the controller
	if hasattr(doc, "fill_employee_details"):
		doc.fill_employee_details()
	doc.insert()

	created_slips: list[str] = []
	try:
		if hasattr(doc, "create_salary_slips"):
			doc.create_salary_slips()
		created_slips = [
			s.name
			for s in frappe.get_all(
				"Salary Slip",
				filters={"payroll_entry": doc.name},
				pluck="name",
			)
		]
		if int(submit or 0) and hasattr(doc, "submit_salary_slips"):
			doc.submit_salary_slips()
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "Payroll Entry generation failed")
		return {
			"name": doc.name,
			"warning": f"Created payroll entry but slip generation hit: {exc}",
			"salary_slips": created_slips,
		}

	return {"name": doc.name, "salary_slips": created_slips}


# ----- Org chart -----------------------------------------------------------


@frappe.whitelist()
def employee_org_tree(company: str, status: str = "Active"):
	"""Nested tree of employees by reports_to. Roots = employees with no reports_to.

	Returns a single root `NestedNode` ready for ApexTree. When multiple
	top-level employees exist, they are grouped under a synthetic Company node.
	"""
	_require_company(company)
	params: dict = {"company": company}
	conds = ["company = %(company)s"]
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	rows = frappe.db.sql(
		f"""
		SELECT name, employee_name, designation, department, image,
		       reports_to, status, user_id, cell_number, gender, date_of_joining
		FROM `tabEmployee`
		WHERE {' AND '.join(conds)}
		ORDER BY employee_name
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return {"id": company, "name": company, "data": {"name": company, "title": "Company"}, "children": []}

	node_by_id: dict[str, dict] = {}
	for r in rows:
		node_by_id[r["name"]] = {
			"id": r["name"],
			"name": r["employee_name"] or r["name"],
			"data": {
				"name": r["employee_name"] or r["name"],
				"title": r["designation"] or "",
				"subtitle": r["department"] or "",
				"imageURL": r["image"] or "",
				"badge": {"text": r["status"]} if r["status"] and r["status"] != "Active" else None,
				"id": r["name"],
				"reports_to": r["reports_to"],
				"user_id": r["user_id"],
				"cell_number": r["cell_number"],
				"gender": r["gender"],
				"date_of_joining": str(r["date_of_joining"]) if r["date_of_joining"] else None,
			},
			"children": [],
		}

	roots: list[dict] = []
	for r in rows:
		node = node_by_id[r["name"]]
		parent_id = r["reports_to"]
		if parent_id and parent_id in node_by_id:
			node_by_id[parent_id]["children"].append(node)
		else:
			roots.append(node)

	if len(roots) == 1:
		return roots[0]
	return {
		"id": f"__company__{company}",
		"name": company,
		"data": {"name": company, "title": "Company", "subtitle": f"{len(rows)} employees"},
		"children": roots,
	}


# ----- Dashboard helpers ---------------------------------------------------


@frappe.whitelist()
def hr_overview(company: str):
	"""Quick stats for the HR home tab header."""
	_require_company(company)
	active = frappe.db.count("Employee", {"company": company, "status": "Active"})
	on_leave_today = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT employee) FROM `tabLeave Application`
		WHERE company = %s AND status = 'Approved' AND docstatus = 1
		  AND from_date <= %s AND to_date >= %s
		""",
		(company, today(), today()),
	)[0][0]
	pending_leave = frappe.db.count(
		"Leave Application", {"company": company, "status": "Open", "docstatus": 0}
	)
	return {
		"active_employees": int(active or 0),
		"on_leave_today": int(on_leave_today or 0),
		"pending_leave_requests": int(pending_leave or 0),
	}
