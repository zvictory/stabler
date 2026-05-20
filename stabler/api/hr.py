"""HR module — Employees, Attendance, Leave, Payroll basics."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, getdate, today, add_days, date_diff


def _require_company(company: str) -> str:
	if not company:
		frappe.throw("Company is required.")
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}")
	return company


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
	if not name or not frappe.db.exists("Employee", name):
		frappe.throw(f"Unknown employee: {name}")
	doc = frappe.get_doc("Employee", name)
	return {
		"name": doc.name,
		"employee_name": doc.employee_name,
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"status": doc.status,
		"company": doc.company,
		"department": doc.department,
		"designation": doc.designation,
		"date_of_birth": doc.date_of_birth,
		"date_of_joining": doc.date_of_joining,
		"gender": doc.gender,
		"cell_number": doc.cell_number,
		"personal_email": getattr(doc, "personal_email", None),
		"company_email": getattr(doc, "company_email", None),
		"user_id": doc.user_id,
		"image": doc.image,
		"holiday_list": doc.holiday_list,
		"employment_type": getattr(doc, "employment_type", None),
	}


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
	doc.insert()
	return {"name": doc.name, "employee_name": doc.employee_name}


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
	conds = []
	params: dict = {"limit": int(limit)}
	if company:
		conds.append("(company = %(c)s OR company IS NULL OR company = '')")
		params["c"] = company
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
