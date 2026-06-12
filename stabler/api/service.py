"""ERPNext-native HoReCa Service APIs for Stabler."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from stabler.api._common import _assert_can_read, _require_company
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
def create_invoice_from_visit(visit: str, items, posting_date: str | None = None, submit: int = 0):
	if not visit or not frappe.db.exists("Maintenance Visit", visit):
		frappe.throw(_("Visit is required."))
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
