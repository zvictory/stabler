"""Attendance Correction Requests and Attendance Exceptions API.

Endpoints (all reject Guest, check frappe.has_permission, anti-IDOR on named
records, consistent dict/list envelopes):

  request_correction(payload)         — create a Correction Request (Pending)
  list_corrections(...)               — list Correction Requests newest-first
  approve_correction(name, note)      — approve + SoD gate
  reject_correction(name, note)       — reject
  list_exceptions(...)                — list Attendance Exceptions
  resolve_exception(name, resolution) — Resolved / Ignored
  period_lock_readiness(company, pp)  — read-only lock-gate check

Payroll-impacting corrections (per is_correction_payroll_impacting) are routed
through the approval engine via ``ensure_request_for_doc`` so a second approver
is required.  The ``Stabler Attendance Correction Request`` doctype must be
present in the controlled-doctype list if you want the before_submit gate;
here we record the payroll_impact flag and status transitions directly.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from stabler.api._common import _assert_can_read, _assert_can_write
from stabler.api._payroll_summary import (
	can_lock,
	is_correction_payroll_impacting,
	period_blockers,
)
from stabler.api.approvals import _assert_company_scope, is_self_approval

_CORRECTION = "Stabler Attendance Correction Request"
_EXCEPTION = "Stabler Attendance Exception"
_SUMMARY = "Stabler Payroll Attendance Summary"

# Correction types accepted by the API.
_VALID_CORRECTION_TYPES = frozenset(
	{
		"check_in",
		"check_out",
		"status",
		"late_excuse",
		"add_attendance",
		"remove_attendance",
		"overtime_adjust",
		"note",
	}
)

# Roles that may approve corrections.
_APPROVER_ROLES = ("HR Manager", "System Manager", "Stabler Admin")


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------


def _require_auth() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)


def _guard_correction(ptype: str = "read") -> None:
	_require_auth()
	if not frappe.has_permission(_CORRECTION, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _guard_exception(ptype: str = "read") -> None:
	_require_auth()
	if not frappe.has_permission(_EXCEPTION, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _require_correction_approver() -> None:
	_require_auth()
	roles = frappe.get_roles()
	if not any(r in roles for r in _APPROVER_ROLES):
		frappe.throw(
			_("You are not permitted to approve or reject correction requests."),
			frappe.PermissionError,
		)


# ---------------------------------------------------------------------------
# request_correction
# ---------------------------------------------------------------------------


@frappe.whitelist()
def request_correction(payload) -> dict:
	"""Create a Stabler Attendance Correction Request (status Pending).

	``payload`` may be a JSON string or a dict.

	Required fields:
	  employee, correction_date, correction_type, requested_value, reason, company.

	Optional fields:
	  before_value, attachment, linked_attendance.

	Sets:
	  requested_by = frappe.session.user
	  payroll_impact = is_correction_payroll_impacting(correction_type, before_value, requested_value)
	  status = "Pending"

	For payroll-impacting corrections the request is also routed through the
	approval engine so a second approver is required (the approvals queue shows it).

	Returns {"name": "<docname>", "payroll_impact": bool, "status": "Pending"}.
	"""
	_guard_correction("create")

	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("Invalid payload — expected JSON object."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	# Required field validation
	employee = (payload.get("employee") or "").strip()
	if not employee:
		frappe.throw(_("employee is required."))

	correction_date = (payload.get("correction_date") or "").strip()
	if not correction_date:
		frappe.throw(_("correction_date is required."))

	correction_type = (payload.get("correction_type") or "").strip()
	if not correction_type:
		frappe.throw(_("correction_type is required."))
	if correction_type not in _VALID_CORRECTION_TYPES:
		frappe.throw(
			_("Invalid correction_type '{0}'. Valid values: {1}").format(
				correction_type, ", ".join(sorted(_VALID_CORRECTION_TYPES))
			)
		)

	requested_value = payload.get("requested_value")
	if requested_value is None or str(requested_value).strip() == "":
		frappe.throw(_("requested_value is required."))

	reason = (payload.get("reason") or "").strip()
	if not reason:
		frappe.throw(_("reason is required and must not be empty."))

	company = (payload.get("company") or "").strip()
	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))

	before_value = payload.get("before_value")

	# Compute payroll impact via the pure helper.
	payroll_impact = is_correction_payroll_impacting(
		correction_type,
		before_value,
		requested_value,
	)

	doc = frappe.new_doc(_CORRECTION)
	doc.employee = employee
	doc.correction_date = correction_date
	doc.correction_type = correction_type
	doc.before_value = before_value
	doc.requested_value = str(requested_value)
	doc.reason = reason
	doc.company = company
	doc.payroll_impact = 1 if payroll_impact else 0
	doc.status = "Pending"
	doc.requested_by = frappe.session.user

	if payload.get("attachment"):
		doc.attachment = payload["attachment"]
	if payload.get("linked_attendance"):
		doc.linked_attendance = payload["linked_attendance"]

	doc.insert(ignore_permissions=False)
	frappe.db.commit()

	# For payroll-impacting corrections, also create an approval-engine request
	# so the correction appears in the standard approvals queue and requires a
	# second approver.  The Stabler Approval Request acts as the audit trail;
	# the correction's own status lifecycle is what the HR UI reads.
	approval_request = None
	if payroll_impact:
		try:
			from stabler.api.approvals import ensure_request_for_doc

			# ensure_request_for_doc expects a doc with .doctype, .name, .company,
			# and attribute access. Stabler Attendance Correction Request may not be
			# in CONTROLLED_DOCTYPES; we call it only if the doctype is registered
			# there.  If not registered, we fall through silently — the correction's
			# own approval flow (approve_correction endpoint) is still enforced.
			approval_request = ensure_request_for_doc(doc)
		except Exception:
			# If the doctype isn't in CONTROLLED_DOCTYPES the call returns None
			# (requires_approval == False).  Non-fatal — correction-level SoD is
			# still enforced in approve_correction.
			pass

	return {
		"name": doc.name,
		"payroll_impact": payroll_impact,
		"status": doc.status,
		"approval_request": approval_request,
	}


# ---------------------------------------------------------------------------
# list_corrections
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_corrections(
	status: str = "",
	employee: str = "",
	company: str = "",
	limit: int | str = 200,
) -> dict:
	"""List Stabler Attendance Correction Requests, newest first.

	Optional filters: status, employee, company.
	Returns {"corrections": [...], "total": int}.
	"""
	_guard_correction("read")
	if company:
		_assert_company_scope(company)

	try:
		limit = min(int(limit), 500)
	except TypeError, ValueError:
		limit = 200

	filters: dict = {}
	if status:
		filters["status"] = status
	if employee:
		filters["employee"] = employee
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		_CORRECTION,
		filters=filters,
		fields=[
			"name",
			"employee",
			"correction_date",
			"correction_type",
			"before_value",
			"requested_value",
			"reason",
			"status",
			"payroll_impact",
			"requested_by",
			"approver",
			"reviewed_at",
			"review_note",
			"linked_attendance",
			"company",
			"creation",
			"modified",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)
	total = frappe.db.count(_CORRECTION, filters)
	return {"corrections": rows, "total": total}


# ---------------------------------------------------------------------------
# approve_correction
# ---------------------------------------------------------------------------


@frappe.whitelist()
def approve_correction(name: str, note: str | None = None) -> dict:
	"""Approve a Correction Request.

	Guards:
	  - Caller must have write permission on the specific doc (anti-IDOR).
	  - Caller must hold an approver role (HR Manager / System Manager / Stabler Admin).
	  - SoD: requester != approver (is_self_approval semantics from approvals.py).

	Sets status = "Approved", approver = session user, reviewed_at = now.

	TODO (Phase-3 apply processor): once a live bench is available,
	``apply_correction`` should be called here to:
	  1. Update Employee Checkin (check_in/check_out corrections).
	  2. Update / create / delete Attendance records (status, add_attendance,
	     remove_attendance corrections).
	  3. Call _attendance_processor.summarize_day for the affected date to
	     recalculate the Stabler Attendance Summary row.
	  4. If the period is already locked, raise a ValidationError unless the
	     caller holds an override role.

	Returns {"name": "<docname>", "status": "Approved"}.
	"""
	_guard_correction("write")
	_require_correction_approver()

	if not name:
		frappe.throw(_("Correction request name is required."))

	# Anti-IDOR: verify caller can write this specific document.
	_assert_can_write(_CORRECTION, name, "write")

	doc = frappe.get_doc(_CORRECTION, name)
	_assert_company_scope(doc.company)

	if doc.status != "Pending":
		frappe.throw(_("This correction is already {0} and cannot be approved.").format(_(doc.status)))

	# Segregation of duties: the approver must differ from the requester.
	# Reuse is_self_approval from approvals.py (same semantics as maker-checker).
	if is_self_approval(doc.requested_by, frappe.session.user):
		frappe.throw(
			_(
				"Segregation of duties: you raised this correction request — it must be approved by someone else."
			),
			title=_("Self-approval blocked"),
		)

	doc.status = "Approved"
	doc.approver = frappe.session.user
	doc.reviewed_at = now_datetime()
	if note:
		doc.review_note = note

	doc.save(ignore_permissions=False)
	frappe.db.commit()

	return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# reject_correction
# ---------------------------------------------------------------------------


@frappe.whitelist()
def reject_correction(name: str, note: str | None = None) -> dict:
	"""Reject a Correction Request.

	Caller must have write permission on the specific doc (anti-IDOR) and hold an
	approver role.  The requester may not reject their own request (same SoD rule
	as approve).

	Sets status = "Rejected", approver = session user, reviewed_at = now,
	review_note = note.

	Returns {"name": "<docname>", "status": "Rejected"}.
	"""
	_guard_correction("write")
	_require_correction_approver()

	if not name:
		frappe.throw(_("Correction request name is required."))

	_assert_can_write(_CORRECTION, name, "write")

	doc = frappe.get_doc(_CORRECTION, name)
	_assert_company_scope(doc.company)

	if doc.status != "Pending":
		frappe.throw(_("This correction is already {0} and cannot be rejected.").format(_(doc.status)))

	if is_self_approval(doc.requested_by, frappe.session.user):
		frappe.throw(
			_(
				"Segregation of duties: you raised this correction request — it must be reviewed by someone else."
			),
			title=_("Self-review blocked"),
		)

	doc.status = "Rejected"
	doc.approver = frappe.session.user
	doc.reviewed_at = now_datetime()
	if note:
		doc.review_note = note

	doc.save(ignore_permissions=False)
	frappe.db.commit()

	return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# list_exceptions
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_exceptions(
	status: str = "Open",
	exception_type: str = "",
	employee: str = "",
	company: str = "",
	limit: int | str = 200,
) -> dict:
	"""List Stabler Attendance Exceptions.

	Default filter: status = "Open".  Pass status="" to list all.
	Returns {"exceptions": [...], "total": int}.
	"""
	_guard_exception("read")
	if company:
		_assert_company_scope(company)

	try:
		limit = min(int(limit), 500)
	except TypeError, ValueError:
		limit = 200

	filters: dict = {}
	if status:
		filters["status"] = status
	if exception_type:
		filters["exception_type"] = exception_type
	if employee:
		filters["employee"] = employee
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		_EXCEPTION,
		filters=filters,
		fields=[
			"name",
			"employee",
			"exception_date",
			"exception_type",
			"status",
			"raw_event",
			"details",
			"company",
			"resolved_by",
			"resolved_at",
			"creation",
			"modified",
		],
		order_by="exception_date desc, creation desc",
		limit_page_length=limit,
	)
	total = frappe.db.count(_EXCEPTION, filters)
	return {"exceptions": rows, "total": total}


# ---------------------------------------------------------------------------
# resolve_exception
# ---------------------------------------------------------------------------


@frappe.whitelist()
def resolve_exception(name: str, resolution: str = "Resolved") -> dict:
	"""Resolve or ignore a Stabler Attendance Exception.

	``resolution`` must be "Resolved" or "Ignored".

	Caller must have write permission on the specific doc (anti-IDOR).

	Sets status = resolution, resolved_by = session user, resolved_at = now.

	Returns {"name": "<docname>", "status": "<resolution>"}.
	"""
	_guard_exception("write")

	if not name:
		frappe.throw(_("Exception name is required."))

	valid_resolutions = ("Resolved", "Ignored")
	if resolution not in valid_resolutions:
		frappe.throw(
			_("Invalid resolution '{0}'. Must be one of: {1}").format(
				resolution, ", ".join(valid_resolutions)
			)
		)

	# Anti-IDOR: verify caller can write this specific document.
	_assert_can_write(_EXCEPTION, name, "write")

	doc = frappe.get_doc(_EXCEPTION, name)
	_assert_company_scope(doc.company)

	if doc.status != "Open":
		frappe.throw(_("This exception is already {0}.").format(_(doc.status)))

	doc.status = resolution
	doc.resolved_by = frappe.session.user
	doc.resolved_at = now_datetime()
	doc.save(ignore_permissions=False)
	frappe.db.commit()

	return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# period_lock_readiness
# ---------------------------------------------------------------------------


@frappe.whitelist()
def period_lock_readiness(company: str, payroll_period: str) -> dict:
	"""Read-only pre-lock check for a payroll period.

	Assembles a context dict from live Frappe data and passes it through the
	pure ``period_blockers`` / ``can_lock`` functions from _payroll_summary.

	Returns:
	  {
	    "can_lock": bool,
	    "blockers": [{"code": str, "message": str, "count": int}, ...],
	    "ctx": {
	      "unresolved_exceptions": int,
	      "pending_corrections": int,
	      ... (other keys stubbed at 0 with TODO — see inline comments)
	    }
	  }
	"""
	_require_auth()
	if not frappe.has_permission(_CORRECTION, "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if not company:
		frappe.throw(_("company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	_assert_company_scope(company)

	if not payroll_period:
		frappe.throw(_("payroll_period is required."))

	# Derive date range from the payroll_period name.
	# A Stabler / ERPNext Payroll Period has start_date and end_date.
	# If the doctype doesn't exist or the name isn't found, fall back to a
	# simple YYYY-MM parse so the API can still be tested without payroll setup.
	period_start = None
	period_end = None
	if frappe.db.exists("DocType", "Payroll Period") and frappe.db.exists("Payroll Period", payroll_period):
		period_start, period_end = frappe.db.get_value(
			"Payroll Period", payroll_period, ["start_date", "end_date"]
		)
	if not period_start and len(payroll_period) == 7:
		# Fallback: treat payroll_period as "YYYY-MM"
		try:
			y, m = payroll_period.split("-")
			import calendar

			period_start = f"{y}-{m}-01"
			last_day = calendar.monthrange(int(y), int(m))[1]
			period_end = f"{y}-{m}-{last_day:02d}"
		except Exception:
			pass

	# 1. Count Open exceptions for this company in the period.
	exc_filters: dict = {"company": company, "status": "Open"}
	if period_start and period_end:
		exc_filters["exception_date"] = ["between", [period_start, period_end]]
	unresolved_exceptions = frappe.db.count(_EXCEPTION, exc_filters)

	# 2. Count Pending payroll-impacting corrections for this company in the period.
	corr_filters: dict = {
		"company": company,
		"status": "Pending",
		"payroll_impact": 1,
	}
	if period_start and period_end:
		corr_filters["correction_date"] = ["between", [period_start, period_end]]
	pending_corrections = frappe.db.count(_CORRECTION, corr_filters)
	open_punch_filters: dict = {
		"company": company,
		"status": "Open",
		"exception_type": "missing_check_out",
	}
	if period_start and period_end:
		open_punch_filters["exception_date"] = ["between", [period_start, period_end]]
	open_punch_days = frappe.db.count(_EXCEPTION, open_punch_filters)

	employees_without_summary = 0
	if period_start and period_end:
		employee_rows = frappe.get_all(
			"Employee",
			filters={"company": company, "status": "Active"},
			fields=["name", "date_of_joining", "relieving_date"],
			limit_page_length=10000,
		)
		active_employees = []
		for row in employee_rows:
			joined = str(row.get("date_of_joining") or period_start)
			relieved = str(row.get("relieving_date") or "")
			if joined > str(period_end):
				continue
			if relieved and relieved < str(period_start):
				continue
			active_employees.append(row["name"])
		summary_rows = frappe.get_all(
			_SUMMARY,
			filters={"company": company, "payroll_period": payroll_period},
			fields=["employee"],
			limit_page_length=10000,
		)
		summarized = {row["employee"] for row in summary_rows if row.get("employee")}
		employees_without_summary = len([name for name in active_employees if name not in summarized])

	already_locked = bool(
		frappe.db.exists(
			_SUMMARY,
			{"company": company, "payroll_period": payroll_period, "status": "Locked"},
		)
	)

	ctx = {
		"open_punch_days": open_punch_days,
		"unresolved_exceptions": unresolved_exceptions,
		"pending_corrections": pending_corrections,
		"employees_without_summary": employees_without_summary,
		"already_locked": already_locked,
	}

	blockers = period_blockers(ctx)
	lockable = can_lock(ctx)

	return {
		"can_lock": lockable,
		"blockers": blockers,
		"ctx": ctx,
	}
