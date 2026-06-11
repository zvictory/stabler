"""ERPNext-native HoReCa Service APIs for Stabler."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from stabler.api._common import _assert_can_read, _require_company
from stabler.api.organization import _can_access_module
from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for


ISSUE_STATUSES = ("Open", "Assigned", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled")
TECH_STATES = ("Accepted", "En Route", "Started")


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
	}
