"""ERPNext-native HoReCa Service APIs for Stabler."""

from __future__ import annotations

import calendar
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from stabler.api._common import _assert_can_read, _require_company, _assert_can_write
from stabler.api.approvals import _assert_company_scope
from stabler.api._equipment import coverage_state, summarise_coverage
from stabler.api.organization import _can_access_module
from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for


ISSUE_STATUSES = ("Open", "Assigned", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled")
TECH_STATES = ("Accepted", "En Route", "Started")
BILLABLE_ISSUE_TYPES = {"Refill", "Repair"}


def _validation_error(message: str) -> None:
	raise frappe.ValidationError(message)


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		return frappe.get_meta(doctype).has_field(fieldname)
	except Exception:
		return False


def _current_company() -> str | None:
	user = frappe.session.user
	return frappe.defaults.get_user_default("company", user) or frappe.db.get_value("Company", {}, "name")


def _company_for_issue(doc) -> str | None:
	if _has_field("Issue", "company") and getattr(doc, "company", None):
		return doc.company
	return _current_company()


def _require_service(company: str | None = None) -> str:
	company = _require_company(company or _current_company())
	# Tenant isolation for every Service endpoint at once: reject a company the
	# caller is not permitted to see (admins / unrestricted users pass through).
	_assert_company_scope(company)
	if not module_map_for(company).get("service"):
		frappe.throw(_("Service module is not enabled for {0}.").format(company), frappe.PermissionError)
	if not _can_access_module(frappe.session.user, "service"):
		frappe.throw(_("Not permitted for Service module."), frappe.PermissionError)
	return company


def _parse_assign(value) -> list[str]:
	if not value:
		return []
	if isinstance(value, list):
		return [str(v) for v in value if v]
	try:
		return [str(v) for v in json.loads(value or "[]") if v]
	except Exception:
		return []


def _coerce_list(value) -> list:
	if not value:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value or "[]")
		except Exception:
			_validation_error("Invalid JSON payload.")
	if not isinstance(value, list):
		_validation_error("Expected a list payload.")
	return value


def _normalize_visit_items(items) -> list[dict]:
	rows = _coerce_list(items)
	if not rows:
		_validation_error("At least one item line is required.")

	normalized = []
	for row in rows:
		if not isinstance(row, dict):
			_validation_error("Each item line must be an object.")
		item_code = (row.get("item_code") or "").strip()
		if not item_code:
			_validation_error("Each item line needs an item_code.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			_validation_error("Each item line needs a positive qty.")
		rate = row.get("rate")
		basic_rate = row.get("basic_rate")
		normalized.append(
			{
				"item_code": item_code,
				"qty": qty,
				"rate": flt(rate) if rate not in (None, "") else None,
				"basic_rate": flt(basic_rate) if basic_rate not in (None, "") else None,
				"warehouse": (row.get("warehouse") or row.get("s_warehouse") or "").strip() or None,
				"uom": (row.get("uom") or "").strip() or None,
			}
		)
	return normalized


def _visit_needs_billing(issue_type: str | None, under_coverage: bool) -> bool:
	return bool(issue_type in BILLABLE_ISSUE_TYPES and not under_coverage)


def _visit_billing_filter_condition(billing_status: str | None) -> str:
	conditions = {
		"open": "mv.docstatus = 0",
		"unbilled": (
			"mv.docstatus = 1 AND (mv.custom_sales_invoice IS NULL OR mv.custom_sales_invoice = '') "
			"AND (mv.custom_stock_entry IS NULL OR mv.custom_stock_entry = '')"
		),
		"invoiced": "mv.custom_sales_invoice IS NOT NULL AND mv.custom_sales_invoice != ''",
		"stock_issued": "mv.custom_stock_entry IS NOT NULL AND mv.custom_stock_entry != ''",
	}
	return conditions.get(billing_status or "", "")


def _service_calendar_state(completion_status: str | None, scheduled_date, current_date=None) -> str:
	if completion_status == "Fully Completed":
		return "paid"
	if completion_status == "Partially Completed":
		return "partial"
	current = getdate(current_date or today())
	return "overdue" if getdate(scheduled_date) < current else "upcoming"


def _latest_visit_state(visits: list[dict], current_date=None) -> dict:
	"""Reduce a customer's visits (each {date, completion_status}) to a single map
	pin state, taken from the most recent visit. No visits → state 'none'."""
	dated = [v for v in (visits or []) if v.get("date")]
	if not dated:
		return {"state": "none", "last_date": None, "visit_count": len(visits or [])}
	latest = max(dated, key=lambda v: getdate(v["date"]))
	return {
		"state": _service_calendar_state(latest.get("completion_status"), latest["date"], current_date),
		"last_date": latest["date"],
		"visit_count": len(visits or []),
	}


def _serial_under_coverage(serial_no: str | None) -> bool:
	if not serial_no or not frappe.db.exists("Serial No", serial_no):
		return False
	serial = frappe.db.get_value("Serial No", serial_no, ["warranty_expiry_date", "amc_expiry_date"], as_dict=True)
	if not serial:
		return False
	current = getdate(today())
	return any(getdate(value) >= current for value in (serial.warranty_expiry_date, serial.amc_expiry_date) if value)


def _company_for_visit(doc) -> str | None:
	return getattr(doc, "company", None) or _current_company()


def _ticket_row(row: dict) -> dict:
	resolution_by = row.get("resolution_by")
	sla_failed = False
	if resolution_by and row.get("status") not in ("Resolved", "Closed", "Cancelled"):
		try:
			sla_failed = get_datetime(resolution_by) < now_datetime()
		except Exception:
			sla_failed = False
	return {
		"name": row.get("name"),
		"subject": row.get("subject"),
		"status": row.get("status"),
		"tech_state": row.get("custom_tech_state"),
		"issue_type": row.get("issue_type"),
		"priority": row.get("priority"),
		"customer": row.get("customer"),
		"customer_name": row.get("customer_name") or row.get("customer"),
		"serial_no": row.get("custom_serial_no"),
		"assignees": _parse_assign(row.get("_assign")),
		"opening_date": row.get("opening_date"),
		"modified": row.get("modified"),
		"resolution_by": resolution_by,
		"sla_failed": sla_failed,
	}


def _ticket_doc_payload(doc) -> dict:
	data = _ticket_row(doc.as_dict())
	data.update(
		{
			"description": doc.get("description"),
			"company": _company_for_issue(doc),
			"maintenance_visit": doc.get("custom_maintenance_visit"),
			"comments": frappe.get_all(
				"Comment",
				filters={
					"reference_doctype": "Issue",
					"reference_name": doc.name,
					"comment_type": ["in", ["Comment", "Info"]],
				},
				fields=["name", "comment_type", "content", "owner", "creation"],
				order_by="creation desc",
				limit_page_length=50,
			),
			"files": frappe.get_all(
				"File",
				filters={"attached_to_doctype": "Issue", "attached_to_name": doc.name},
				fields=["name", "file_name", "file_url", "creation"],
				order_by="creation desc",
				limit_page_length=50,
			),
		}
	)
	return data


@frappe.whitelist()
def list_tickets(
	company: str,
	status: str | None = None,
	issue_type: str | None = None,
	technician: str | None = None,
	customer: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 200,
):
	company = _require_service(company)
	limit = max(1, min(cint(limit) or 200, 500))
	params = {"company": company, "limit": limit}
	conds = ["1=1"]

	if _has_field("Issue", "company"):
		conds.append("i.company = %(company)s")
	if status:
		conds.append("i.status = %(status)s")
		params["status"] = status
	if issue_type:
		conds.append("i.issue_type = %(issue_type)s")
		params["issue_type"] = issue_type
	if customer:
		conds.append("i.customer = %(customer)s")
		params["customer"] = customer
	if technician:
		conds.append("i._assign LIKE %(technician)s")
		params["technician"] = f"%{technician}%"
	if from_date:
		conds.append("i.opening_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("i.opening_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)

	customer_name_expr = "c.customer_name" if frappe.db.has_column("Customer", "customer_name") else "i.customer"
	resolution_expr = "i.resolution_by" if _has_field("Issue", "resolution_by") else "NULL"
	serial_expr = "i.custom_serial_no" if _has_field("Issue", "custom_serial_no") else "NULL"
	tech_expr = "i.custom_tech_state" if _has_field("Issue", "custom_tech_state") else "NULL"

	rows = frappe.db.sql(
		f"""
		SELECT
			i.name, i.subject, i.status, {tech_expr} AS custom_tech_state,
			i.issue_type, i.priority, i.customer, {customer_name_expr} AS customer_name,
			{serial_expr} AS custom_serial_no, i._assign, i.opening_date, i.modified,
			{resolution_expr} AS resolution_by
		FROM `tabIssue` i
		LEFT JOIN `tabCustomer` c ON c.name = i.customer
		WHERE {" AND ".join(conds)}
		ORDER BY i.modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	return [_ticket_row(r) for r in rows]


@frappe.whitelist()
def ticket_detail(name: str):
	if not name:
		frappe.throw(_("Ticket is required."))
	_assert_can_read("Issue", name)
	doc = frappe.get_doc("Issue", name)
	_require_service(_company_for_issue(doc))
	return _ticket_doc_payload(doc)


@frappe.whitelist()
def create_ticket(
	company: str,
	customer: str,
	subject: str,
	issue_type: str,
	priority: str | None = None,
	serial_no: str | None = None,
	description: str | None = None,
):
	company = _require_service(company)
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer is required."))
	if not subject:
		frappe.throw(_("Subject is required."))
	if not issue_type or not frappe.db.exists("Issue Type", issue_type):
		frappe.throw(_("Valid issue type is required."))
	if serial_no and not frappe.db.exists("Serial No", serial_no):
		frappe.throw(_("Unknown serial number: {0}").format(serial_no))

	doc = frappe.new_doc("Issue")
	doc.subject = subject
	doc.customer = customer
	doc.issue_type = issue_type
	doc.status = "Open"
	if priority:
		doc.priority = priority
	if description:
		doc.description = description
	if _has_field("Issue", "company"):
		doc.company = company
	if serial_no and _has_field("Issue", "custom_serial_no"):
		doc.custom_serial_no = serial_no

	doc.insert()
	frappe.db.commit()
	return _ticket_doc_payload(doc)


@frappe.whitelist()
def update_ticket_status(name: str, status: str, tech_state: str | None = None):
	_assert_can_write("Issue", name, "write")
	if not name:
		frappe.throw(_("Ticket is required."))
	if status in TECH_STATES:
		tech_state = status
		status = "In Progress"
	if status not in ISSUE_STATUSES:
		frappe.throw(_("Invalid ticket status: {0}").format(status))
	if tech_state and tech_state not in TECH_STATES:
		frappe.throw(_("Invalid technician state: {0}").format(tech_state))

	doc = frappe.get_doc("Issue", name)
	_require_service(_company_for_issue(doc))
	doc.status = status
	if _has_field("Issue", "custom_tech_state"):
		doc.custom_tech_state = tech_state if status == "In Progress" else ""
	doc.save()
	frappe.db.commit()
	return _ticket_doc_payload(doc)


@frappe.whitelist()
def assign_ticket(name: str, user: str):
	_assert_can_write("Issue", name, "write")
	if not name:
		frappe.throw(_("Ticket is required."))
	if not user or not frappe.db.exists("User", user):
		frappe.throw(_("Valid user is required."))
	doc = frappe.get_doc("Issue", name)
	_require_service(_company_for_issue(doc))

	from frappe.desk.form.assign_to import add

	add(
		{
			"assign_to": [user],
			"doctype": "Issue",
			"name": name,
			"description": _("Service ticket assignment"),
		}
	)
	frappe.db.commit()
	doc.reload()
	return _ticket_doc_payload(doc)


@frappe.whitelist()
def ticket_board_meta(company: str):
	company = _require_service(company)
	issue_types = frappe.get_all("Issue Type", fields=["name"], order_by="name asc")
	priorities = frappe.get_all("Issue Priority", fields=["name"], order_by="name asc")
	service_people = frappe.get_all(
		"Sales Person",
		filters={"enabled": 1, "is_group": 0},
		fields=["name", "sales_person_name"],
		order_by="sales_person_name asc",
	)
	technicians = frappe.db.sql(
		"""
		SELECT DISTINCT u.name, COALESCE(NULLIF(u.full_name, ''), u.name) AS full_name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` r
			ON r.parent = u.name AND r.parenttype = 'User'
		WHERE u.enabled = 1
		  AND r.role IN ('Support Team', 'Maintenance User', 'Maintenance Manager')
		ORDER BY full_name ASC
		""",
		as_dict=True,
	)
	return {
		"company": company,
		"statuses": list(ISSUE_STATUSES),
		"tech_states": list(TECH_STATES),
		"issue_types": [r.name for r in issue_types],
		"priorities": [r.name for r in priorities] or ["Low", "Medium", "High", "Urgent"],
		"technicians": technicians,
		"service_people": service_people,
	}


@frappe.whitelist()
def create_visit_from_ticket(
	ticket: str,
	work_done: str,
	completion_status: str = "Fully Completed",
	serial_purposes=None,
	signature: str | None = None,
	feedback: str | None = None,
	maintenance_type: str = "Unscheduled",
):
	if not ticket or not frappe.db.exists("Issue", ticket):
		frappe.throw(_("Ticket is required."))
	if not (work_done or "").strip():
		frappe.throw(_("Work done is required."))
	if completion_status not in ("Partially Completed", "Fully Completed"):
		frappe.throw(_("Invalid completion status."))
	if maintenance_type not in ("Scheduled", "Unscheduled", "Breakdown"):
		frappe.throw(_("Invalid maintenance type."))

	issue = frappe.get_doc("Issue", ticket)
	company = _require_service(_company_for_issue(issue))
	customer = issue.get("customer")
	if not customer:
		frappe.throw(_("Ticket must have a customer before closing a visit."))
	purposes = _coerce_list(serial_purposes)
	if not purposes:
		frappe.throw(_("At least one visit purpose is required."))

	visit = frappe.new_doc("Maintenance Visit")
	visit.company = company
	visit.customer = customer
	visit.mntc_date = getdate(today())
	visit.maintenance_type = maintenance_type
	visit.completion_status = completion_status
	visit.customer_feedback = feedback or work_done
	if _has_field("Maintenance Visit", "custom_issue"):
		visit.custom_issue = ticket
	if signature and _has_field("Maintenance Visit", "custom_customer_signature"):
		visit.custom_customer_signature = signature

	for purpose in purposes:
		if not isinstance(purpose, dict):
			frappe.throw(_("Each purpose row must be an object."), frappe.ValidationError)
		service_person = (purpose.get("service_person") or "").strip()
		if not service_person:
			frappe.throw(_("Each purpose row needs a service person."), frappe.ValidationError)
		row = visit.append("purposes", {})
		row.service_person = service_person
		row.work_done = (purpose.get("work_done") or work_done).strip()
		if purpose.get("item_code"):
			row.item_code = purpose["item_code"]
		if purpose.get("serial_no"):
			row.serial_no = purpose["serial_no"]
		if purpose.get("description"):
			row.description = purpose["description"]

	visit.insert()
	visit.submit()

	if _has_field("Issue", "custom_maintenance_visit"):
		issue.custom_maintenance_visit = visit.name
	if _has_field("Issue", "custom_tech_state"):
		issue.custom_tech_state = ""
	issue.status = "Resolved"
	issue.save()
	frappe.db.commit()

	under_coverage = _serial_under_coverage(issue.get("custom_serial_no"))
	return {
		"name": visit.name,
		"docstatus": visit.docstatus,
		"ticket": issue.name,
		"needs_billing": 1 if _visit_needs_billing(issue.issue_type, under_coverage) else 0,
		"under_coverage": 1 if under_coverage else 0,
	}


@frappe.whitelist()
def visit_detail(name: str):
	if not name:
		frappe.throw(_("Visit is required."))
	_assert_can_read("Maintenance Visit", name)
	doc = frappe.get_doc("Maintenance Visit", name)
	_require_service(_company_for_visit(doc))
	return doc.as_dict()


@frappe.whitelist()
def list_visits(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	service_person: str | None = None,
	customer: str | None = None,
	issue_type: str | None = None,
	billing_status: str | None = None,
	limit: int = 200,
):
	company = _require_service(company)
	limit = max(1, min(cint(limit) or 200, 500))
	params = {"company": company, "limit": limit}
	conds = ["mv.company = %(company)s"]
	if from_date:
		conds.append("mv.mntc_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("mv.mntc_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if customer:
		conds.append("mv.customer = %(customer)s")
		params["customer"] = customer
	if issue_type:
		conds.append("i.issue_type = %(issue_type)s")
		params["issue_type"] = issue_type
	if service_person:
		conds.append(
			"EXISTS (SELECT 1 FROM `tabMaintenance Visit Purpose` p "
			"WHERE p.parent = mv.name AND p.service_person = %(service_person)s)"
		)
		params["service_person"] = service_person
	billing_condition = _visit_billing_filter_condition(billing_status)
	if billing_condition:
		conds.append(billing_condition)

	return frappe.db.sql(
		f"""
		SELECT
			mv.name, mv.mntc_date, mv.customer, mv.customer_name,
			mv.completion_status, mv.maintenance_type, mv.docstatus,
			mv.custom_issue, i.subject, i.issue_type,
			mv.custom_sales_invoice, mv.custom_stock_entry,
			GROUP_CONCAT(DISTINCT p.service_person ORDER BY p.service_person SEPARATOR ', ') AS service_people
		FROM `tabMaintenance Visit` mv
		LEFT JOIN `tabIssue` i ON i.name = mv.custom_issue
		LEFT JOIN `tabMaintenance Visit Purpose` p ON p.parent = mv.name
		WHERE {" AND ".join(conds)}
		GROUP BY mv.name
		ORDER BY mv.mntc_date DESC, mv.modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def calendar_feed(company: str, month: str, service_person: str | None = None, customer: str | None = None):
	company = _require_service(company)
	if not month or len(month) != 7:
		frappe.throw(_("Month is required in YYYY-MM format."))
	year, month_no = [cint(part) for part in month.split("-", 1)]
	if year < 1900 or month_no < 1 or month_no > 12:
		frappe.throw(_("Invalid month."))
	start_date = getdate(f"{year:04d}-{month_no:02d}-01")
	end_date = getdate(f"{year:04d}-{month_no:02d}-{calendar.monthrange(year, month_no)[1]:02d}")
	params = {"company": company, "start_date": start_date, "end_date": end_date}
	conds = [
		"ms.company = %(company)s",
		"ms.docstatus = 1",
		"sd.scheduled_date BETWEEN %(start_date)s AND %(end_date)s",
	]
	if service_person:
		conds.append("sd.sales_person = %(service_person)s")
		params["service_person"] = service_person
	if customer:
		conds.append("ms.customer = %(customer)s")
		params["customer"] = customer

	planned = frappe.db.sql(
		f"""
		SELECT
			sd.name, sd.scheduled_date, sd.completion_status, sd.sales_person,
			sd.item_code, sd.item_name, sd.serial_no,
			ms.name AS schedule, ms.customer, ms.customer_name
		FROM `tabMaintenance Schedule Detail` sd
		INNER JOIN `tabMaintenance Schedule` ms ON ms.name = sd.parent
		WHERE {" AND ".join(conds)}
		ORDER BY sd.scheduled_date ASC, ms.customer_name ASC
		""",
		params,
		as_dict=True,
	)

	visit_conds = [
		"mv.company = %(company)s",
		"mv.docstatus = 1",
		"mv.mntc_date BETWEEN %(start_date)s AND %(end_date)s",
	]
	if service_person:
		visit_conds.append(
			"EXISTS (SELECT 1 FROM `tabMaintenance Visit Purpose` p "
			"WHERE p.parent = mv.name AND p.service_person = %(service_person)s)"
		)
	if customer:
		visit_conds.append("mv.customer = %(customer)s")

	visits = frappe.db.sql(
		f"""
		SELECT
			mv.name, mv.mntc_date, mv.completion_status, mv.customer, mv.customer_name,
			mv.custom_issue, i.subject, i.issue_type,
			GROUP_CONCAT(DISTINCT p.service_person ORDER BY p.service_person SEPARATOR ', ') AS service_people
		FROM `tabMaintenance Visit` mv
		LEFT JOIN `tabIssue` i ON i.name = mv.custom_issue
		LEFT JOIN `tabMaintenance Visit Purpose` p ON p.parent = mv.name
		WHERE {" AND ".join(visit_conds)}
		GROUP BY mv.name
		ORDER BY mv.mntc_date ASC, mv.customer_name ASC
		""",
		params,
		as_dict=True,
	)

	events = []
	for row in planned:
		label = row.customer_name or row.customer or row.schedule
		if row.item_name or row.item_code:
			label = f"{label} · {row.item_name or row.item_code}"
		events.append(
			{
				"kind": "planned",
				"date": row.scheduled_date,
				"label": label,
				"amount": 0,
				"contractId": row.name,
				"schedule": row.schedule,
				"customer": row.customer,
				"customer_name": row.customer_name,
				"service_person": row.sales_person,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"serial_no": row.serial_no,
				"completion_status": row.completion_status,
				"state": _service_calendar_state(row.completion_status, row.scheduled_date),
			}
		)
	for row in visits:
		label = row.customer_name or row.customer or row.name
		if row.issue_type:
			label = f"{label} · {row.issue_type}"
		events.append(
			{
				"kind": "done",
				"date": row.mntc_date,
				"label": label,
				"amount": 0,
				"contractId": row.name,
				"visit": row.name,
				"customer": row.customer,
				"customer_name": row.customer_name,
				"service_person": row.service_people,
				"issue": row.custom_issue,
				"subject": row.subject,
				"issue_type": row.issue_type,
				"completion_status": row.completion_status,
				"state": "paid" if row.completion_status == "Fully Completed" else "partial",
			}
		)
	return events


@frappe.whitelist()
def reschedule_detail(name: str, date: str):
	_assert_can_write("Maintenance Schedule Detail", name, "write")
	if not name or not frappe.db.exists("Maintenance Schedule Detail", name):
		frappe.throw(_("Schedule detail is required."))
	detail = frappe.get_doc("Maintenance Schedule Detail", name)
	schedule = frappe.get_doc("Maintenance Schedule", detail.parent)
	_require_service(_company_for_visit(schedule))
	if detail.completion_status and detail.completion_status != "Pending":
		frappe.throw(_("Only pending schedule rows can be rescheduled."))
	detail.scheduled_date = getdate(date)
	detail.db_update()
	frappe.db.commit()
	return {"name": detail.name, "scheduled_date": detail.scheduled_date}


@frappe.whitelist()
def map_feed(company: str, month: str | None = None, service_person: str | None = None):
	"""Outlets (HoReCa venues) plotted on a map, each coloured by the service state
	of its customer's most recent Maintenance Visit in the chosen month.

	Geo lives on Outlet.gps_lat/gps_lng; service state comes via Outlet.customer →
	Maintenance Visit. Company- and module-scoped. Read-only.
	"""
	company = _require_service(company)

	# Period (default = current month), mirroring calendar_feed.
	if month:
		try:
			year, mon = (int(x) for x in str(month).split("-")[:2])
		except (ValueError, TypeError):
			frappe.throw(_("Invalid month: {0}").format(month))
	else:
		d = getdate(today())
		year, mon = d.year, d.month
	last_day = calendar.monthrange(year, mon)[1]
	start_date = getdate(f"{year:04d}-{mon:02d}-01")
	end_date = getdate(f"{year:04d}-{mon:02d}-{last_day:02d}")

	# 1) GPS-bearing, active outlets for this company.
	outlets = frappe.db.sql(
		"""
		SELECT name, outlet_name, customer, address, outlet_class,
			gps_lat, gps_lng, assigned_field_user
		FROM `tabOutlet`
		WHERE company = %(company)s AND is_active = 1
		  AND gps_lat IS NOT NULL AND gps_lng IS NOT NULL
		  AND gps_lat <> 0 AND gps_lng <> 0
		ORDER BY outlet_name ASC
		""",
		{"company": company},
		as_dict=True,
	)
	total_active = frappe.db.count("Outlet", {"company": company, "is_active": 1})

	customers = sorted({o.customer for o in outlets if o.customer})

	# 2) Customer names (single batched lookup).
	cust_names: dict[str, str] = {}
	if customers:
		for row in frappe.get_all(
			"Customer", filters={"name": ["in", customers]}, fields=["name", "customer_name"]
		):
			cust_names[row.name] = row.customer_name

	# 3) This month's submitted visits for those customers, grouped by customer.
	visits_by_customer: dict[str, list[dict]] = {}
	if customers:
		visit_filters = {
			"company": company,
			"docstatus": 1,
			"mntc_date": ["between", [start_date, end_date]],
			"customer": ["in", customers],
		}
		rows = frappe.get_all(
			"Maintenance Visit",
			filters=visit_filters,
			fields=["name", "customer", "mntc_date", "completion_status"],
		)
		if service_person:
			sp_names = {
				p.parent
				for p in frappe.get_all(
					"Maintenance Visit Purpose",
					filters={"service_person": service_person},
					fields=["parent"],
				)
			}
			rows = [r for r in rows if r.name in sp_names]
		for r in rows:
			visits_by_customer.setdefault(r.customer, []).append(
				{"date": r.mntc_date, "completion_status": r.completion_status}
			)

	# 4) Build one pin per outlet.
	current = getdate(today())
	pins = []
	for o in outlets:
		agg = _latest_visit_state(visits_by_customer.get(o.customer, []), current)
		pins.append(
			{
				"outlet": o.name,
				"outlet_name": o.outlet_name,
				"customer": o.customer,
				"customer_name": cust_names.get(o.customer) or o.customer,
				"lat": flt(o.gps_lat),
				"lng": flt(o.gps_lng),
				"address": o.address,
				"outlet_class": o.outlet_class,
				"state": agg["state"],
				"last_date": str(agg["last_date"]) if agg["last_date"] else None,
				"visit_count": agg["visit_count"],
			}
		)

	# 5) Service people for the filter dropdown.
	service_people = [
		r.service_person
		for r in frappe.db.sql(
			"""
			SELECT DISTINCT p.service_person
			FROM `tabMaintenance Visit Purpose` p
			JOIN `tabMaintenance Visit` mv ON mv.name = p.parent
			WHERE mv.company = %(company)s
			  AND p.service_person IS NOT NULL AND p.service_person <> ''
			ORDER BY p.service_person
			""",
			{"company": company},
			as_dict=True,
		)
	]

	return {
		"company": company,
		"month": f"{year:04d}-{mon:02d}",
		"pins": pins,
		"without_gps": max(0, total_active - len(outlets)),
		"service_people": service_people,
	}


@frappe.whitelist()
def create_invoice_from_visit(visit: str, items, posting_date: str | None = None, submit: int = 0):
	if not visit or not frappe.db.exists("Maintenance Visit", visit):
		frappe.throw(_("Visit is required."))
	_assert_can_read("Maintenance Visit", visit)
	visit_doc = frappe.get_doc("Maintenance Visit", visit)
	company = _require_service(_company_for_visit(visit_doc))
	if visit_doc.get("custom_sales_invoice"):
		frappe.throw(_("Visit already has a linked Sales Invoice."))
	rows = _normalize_visit_items(items)

	doc = frappe.new_doc("Sales Invoice")
	doc.company = company
	doc.customer = visit_doc.customer
	doc.posting_date = getdate(posting_date or today())
	doc.due_date = doc.posting_date
	doc.update_stock = 1 if any(row["warehouse"] for row in rows) else 0
	for row in rows:
		item = doc.append("items", {})
		item.item_code = row["item_code"]
		item.qty = row["qty"]
		if row["uom"]:
			item.uom = row["uom"]
		if row["rate"] is not None:
			item.rate = row["rate"]
			item.price_list_rate = row["rate"]
		if row["warehouse"]:
			item.warehouse = row["warehouse"]

	doc.set_missing_values()
	doc.calculate_taxes_and_totals()
	doc.insert()
	if cint(submit):
		doc.submit()

	frappe.db.set_value("Maintenance Visit", visit_doc.name, "custom_sales_invoice", doc.name)
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus, "grand_total": flt(doc.grand_total)}


@frappe.whitelist()
def create_material_issue_from_visit(
	visit: str,
	items,
	warehouse: str,
	posting_date: str | None = None,
	submit: int = 1,
):
	if not visit or not frappe.db.exists("Maintenance Visit", visit):
		frappe.throw(_("Visit is required."))
	if not warehouse or not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Source warehouse is required."))
	_assert_can_read("Maintenance Visit", visit)
	visit_doc = frappe.get_doc("Maintenance Visit", visit)
	company = _require_service(_company_for_visit(visit_doc))
	if visit_doc.get("custom_stock_entry"):
		frappe.throw(_("Visit already has a linked Stock Entry."))
	rows = _normalize_visit_items(items)

	doc = frappe.new_doc("Stock Entry")
	doc.company = company
	doc.purpose = "Material Issue"
	doc.stock_entry_type = "Material Issue"
	doc.from_warehouse = warehouse
	doc.posting_date = getdate(posting_date or today())
	doc.remarks = _("Service visit {0}").format(visit)
	for row in rows:
		item = doc.append("items", {})
		item.item_code = row["item_code"]
		item.qty = row["qty"]
		item.s_warehouse = row["warehouse"] or warehouse
		if row["uom"]:
			item.uom = row["uom"]
		if row["basic_rate"] is not None:
			item.basic_rate = row["basic_rate"]

	doc.set_missing_values()
	doc.insert()
	if cint(submit):
		doc.submit()

	frappe.db.set_value("Maintenance Visit", visit_doc.name, "custom_stock_entry", doc.name)
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def unbilled_visits(company: str, from_date: str | None = None, to_date: str | None = None, limit: int = 200):
	company = _require_service(company)
	limit = max(1, min(cint(limit) or 200, 500))
	params = {"company": company, "limit": limit}
	conds = [
		"mv.company = %(company)s",
		"mv.docstatus = 1",
		"(mv.custom_sales_invoice IS NULL OR mv.custom_sales_invoice = '')",
		"(mv.custom_stock_entry IS NULL OR mv.custom_stock_entry = '')",
		"i.issue_type IN ('Refill', 'Repair')",
	]
	if from_date:
		conds.append("mv.mntc_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("mv.mntc_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)

	return frappe.db.sql(
		f"""
		SELECT
			mv.name, mv.mntc_date, mv.customer, mv.customer_name,
			mv.completion_status, mv.maintenance_type,
			mv.custom_issue, i.subject, i.issue_type,
			mv.custom_sales_invoice, mv.custom_stock_entry
		FROM `tabMaintenance Visit` mv
		INNER JOIN `tabIssue` i ON i.name = mv.custom_issue
		WHERE {" AND ".join(conds)}
		ORDER BY mv.mntc_date DESC, mv.modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Equipment (ERPNext Serial No — fridges/freezers placed at customers)
# ---------------------------------------------------------------------------

def _serial_company_clause(company: str) -> tuple[str, dict]:
	"""Serial No has a company field on standard ERPNext; guard for older schemas."""
	if _has_field("Serial No", "company"):
		return "sn.company = %(company)s", {"company": company}
	return "1=1", {}


@frappe.whitelist()
def list_equipment(
	company: str,
	customer: str | None = None,
	coverage: str | None = None,
	search: str | None = None,
	limit: int = 500,
):
	"""Serialised equipment under service, with warranty/AMC coverage state.

	`coverage` filters the result to covered | expired | none (client-side of the
	SQL, since coverage is a derived value). Returns {rows, summary}.
	"""
	company = _require_service(company)
	limit = max(1, min(cint(limit) or 500, 2000))
	clause, params = _serial_company_clause(company)
	conds = [clause]
	if customer:
		conds.append("sn.customer = %(customer)s")
		params["customer"] = customer
	if search:
		conds.append("(sn.name LIKE %(needle)s OR sn.item_code LIKE %(needle)s OR sn.item_name LIKE %(needle)s)")
		params["needle"] = f"%{search}%"
	params["limit"] = limit

	rows = frappe.db.sql(
		f"""
		SELECT
			sn.name AS serial_no, sn.item_code, sn.item_name, sn.customer,
			c.customer_name, sn.warranty_expiry_date, sn.amc_expiry_date,
			sn.status, sn.warehouse
		FROM `tabSerial No` sn
		LEFT JOIN `tabCustomer` c ON c.name = sn.customer
		WHERE {" AND ".join(conds)}
		ORDER BY sn.modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)

	today_iso = str(today())
	for r in rows:
		r["coverage"] = coverage_state(r.get("warranty_expiry_date"), r.get("amc_expiry_date"), today_iso)
		r["warranty_expiry_date"] = str(r["warranty_expiry_date"]) if r.get("warranty_expiry_date") else None
		r["amc_expiry_date"] = str(r["amc_expiry_date"]) if r.get("amc_expiry_date") else None

	summary = summarise_coverage(rows, today_iso)
	if coverage in ("covered", "expired", "none"):
		rows = [r for r in rows if r["coverage"] == coverage]

	return {"company": company, "rows": rows, "summary": summary}


@frappe.whitelist()
def equipment_detail(serial_no: str):
	"""One serial's coverage + recent service tickets that referenced it."""
	if not serial_no or not frappe.db.exists("Serial No", serial_no):
		frappe.throw(_("Unknown serial number: {0}").format(serial_no))
	sn = frappe.db.get_value(
		"Serial No",
		serial_no,
		["name", "item_code", "item_name", "customer", "warranty_expiry_date", "amc_expiry_date", "status", "warehouse"],
		as_dict=True,
	)
	serial_company = frappe.db.get_value("Serial No", serial_no, "company") if _has_field("Serial No", "company") else None
	_require_service(serial_company or _current_company())

	tickets = []
	if _has_field("Issue", "custom_serial_no"):
		tickets = frappe.get_all(
			"Issue",
			filters={"custom_serial_no": serial_no},
			fields=["name", "subject", "status", "issue_type", "opening_date"],
			order_by="modified desc",
			limit=20,
		)
		for t in tickets:
			t["opening_date"] = str(t["opening_date"]) if t.get("opening_date") else None

	return {
		"serial_no": sn.name,
		"item_code": sn.item_code,
		"item_name": sn.item_name,
		"customer": sn.customer,
		"customer_name": frappe.db.get_value("Customer", sn.customer, "customer_name") if sn.customer else None,
		"warranty_expiry_date": str(sn.warranty_expiry_date) if sn.warranty_expiry_date else None,
		"amc_expiry_date": str(sn.amc_expiry_date) if sn.amc_expiry_date else None,
		"status": sn.status,
		"warehouse": sn.warehouse,
		"coverage": coverage_state(sn.warranty_expiry_date, sn.amc_expiry_date, str(today())),
		"tickets": tickets,
	}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def dashboard_summary(company: str, month: str | None = None):
	"""KPI roll-up for the Service dashboard: tickets by status, this month's
	visits, the unbilled queue size, and equipment coverage."""
	company = _require_service(company)

	if month:
		try:
			year, mon = (int(x) for x in str(month).split("-")[:2])
		except (ValueError, TypeError):
			frappe.throw(_("Invalid month: {0}").format(month))
	else:
		d = getdate(today())
		year, mon = d.year, d.month
	last_day = calendar.monthrange(year, mon)[1]
	start_date = getdate(f"{year:04d}-{mon:02d}-01")
	end_date = getdate(f"{year:04d}-{mon:02d}-{last_day:02d}")

	# Tickets by status (open = everything not Closed/Cancelled).
	ticket_company = "AND i.company = %(company)s" if _has_field("Issue", "company") else ""
	status_rows = frappe.db.sql(
		f"""
		SELECT i.status, COUNT(*) AS n
		FROM `tabIssue` i
		WHERE 1=1 {ticket_company}
		GROUP BY i.status
		""",
		{"company": company},
		as_dict=True,
	)
	tickets_by_status = {s: 0 for s in ISSUE_STATUSES}
	for r in status_rows:
		tickets_by_status[r.status] = tickets_by_status.get(r.status, 0) + cint(r.n)
	open_tickets = sum(v for k, v in tickets_by_status.items() if k not in ("Closed", "Cancelled"))

	# This month's visits, by completion state.
	visit_rows = frappe.db.sql(
		"""
		SELECT mv.completion_status, mv.mntc_date
		FROM `tabMaintenance Visit` mv
		WHERE mv.company = %(company)s AND mv.docstatus = 1
		  AND mv.mntc_date BETWEEN %(start_date)s AND %(end_date)s
		""",
		{"company": company, "start_date": start_date, "end_date": end_date},
		as_dict=True,
	)
	visits = {"total": 0, "completed": 0, "partial": 0, "open": 0}
	for r in visit_rows:
		visits["total"] += 1
		if r.completion_status == "Fully Completed":
			visits["completed"] += 1
		elif r.completion_status == "Partially Completed":
			visits["partial"] += 1
		else:
			visits["open"] += 1
	visits["completion_rate"] = round(100.0 * visits["completed"] / visits["total"], 1) if visits["total"] else 0.0

	# Unbilled (billing queue) — Refill/Repair visits not yet invoiced/issued.
	unbilled = frappe.db.sql(
		"""
		SELECT COUNT(*) AS n
		FROM `tabMaintenance Visit` mv
		INNER JOIN `tabIssue` i ON i.name = mv.custom_issue
		WHERE mv.company = %(company)s AND mv.docstatus = 1
		  AND (mv.custom_sales_invoice IS NULL OR mv.custom_sales_invoice = '')
		  AND (mv.custom_stock_entry IS NULL OR mv.custom_stock_entry = '')
		  AND i.issue_type IN ('Refill', 'Repair')
		""",
		{"company": company},
		as_dict=True,
	)
	unbilled_count = cint(unbilled[0].n) if unbilled else 0

	# Equipment coverage.
	clause, eparams = _serial_company_clause(company)
	serials = frappe.db.sql(
		f"""
		SELECT sn.warranty_expiry_date, sn.amc_expiry_date
		FROM `tabSerial No` sn
		WHERE {clause}
		""",
		eparams,
		as_dict=True,
	)
	equipment = summarise_coverage(serials, str(today()))

	return {
		"company": company,
		"month": f"{year:04d}-{mon:02d}",
		"tickets_by_status": tickets_by_status,
		"open_tickets": open_tickets,
		"visits": visits,
		"unbilled": unbilled_count,
		"equipment": equipment,
	}
