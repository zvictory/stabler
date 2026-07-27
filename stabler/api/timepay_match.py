"""Resolve unmatched TimePay users → Stabler Employees.

TimePay punches match an Employee by ``custom_timepay_id``. When a device user
has no mapping, the raw event is parked with ``processing_status = 'Unmatched'``
and the device's FIO (full name) is kept on ``device_user_name``. FIO comes in
Latin / Cyrillic / typo variants, so we fuzzy-match the FIO against employee
names and let HR confirm. Confirming sets ``custom_timepay_id`` and re-queues the
parked events so the next process run turns them into check-ins.
"""

from __future__ import annotations

from difflib import SequenceMatcher

import frappe
from frappe import _

_RAW_EVENT = "Stabler Raw Attendance Event"
_HR_ROLES = frozenset(
	("Accounts Manager", "Payroll Manager", "HR Manager", "System Manager", "Stabler Admin")
)


def _require_hr() -> None:
	if not (set(frappe.get_roles()) & _HR_ROLES):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _norm(s: str) -> str:
	return " ".join((s or "").lower().split())


def _token_sorted(s: str) -> str:
	return " ".join(sorted(_norm(s).split()))


def _score(fio: str, name: str) -> float:
	"""Best of direct vs token-sorted ratio (handles 'Surname Name' order swaps)."""
	a, b = _norm(fio), _norm(name)
	if not a or not b:
		return 0.0
	direct = SequenceMatcher(None, a, b).ratio()
	sorted_r = SequenceMatcher(None, _token_sorted(fio), _token_sorted(name)).ratio()
	return round(max(direct, sorted_r), 3)


@frappe.whitelist()
def unmatched_timepay_users(limit: int = 50) -> dict:
	"""Distinct unmatched TimePay users + the top employee-name suggestions."""
	_require_hr()
	limit = min(int(limit or 50), 200)

	groups = frappe.get_all(
		_RAW_EVENT,
		filters={"processing_status": "Unmatched"},
		fields=[
			"device_user_id",
			"max(device_user_name) as fio",
			"count(name) as events",
			"max(timestamp) as last_seen",
		],
		group_by="device_user_id",
		order_by="last_seen desc",
		limit_page_length=limit,
	)
	if not groups:
		return {"users": []}

	# Active employees, with the ids already taken (so we don't re-suggest them).
	emps = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "custom_timepay_name", "custom_timepay_id"],
		limit_page_length=0,
	)
	taken = {str(e.custom_timepay_id).strip() for e in emps if e.custom_timepay_id}

	users = []
	for g in groups:
		fio = (g.get("fio") or "").strip()
		ranked = []
		for e in emps:
			if e.custom_timepay_id:
				continue  # already mapped to some TimePay id
			sc = max(_score(fio, e.employee_name or ""), _score(fio, e.custom_timepay_name or ""))
			if sc >= 0.4:
				ranked.append({"employee": e.name, "employee_name": e.employee_name, "score": sc})
		ranked.sort(key=lambda r: r["score"], reverse=True)
		users.append(
			{
				"device_user_id": g["device_user_id"],
				"fio": fio,
				"events": g.get("events") or 0,
				"last_seen": str(g.get("last_seen") or ""),
				"already_taken": g["device_user_id"] in taken,
				"suggestions": ranked[:3],
			}
		)
	return {"users": users}


@frappe.whitelist()
def link_timepay_user(device_user_id: str, employee: str) -> dict:
	"""Map a TimePay user id to an Employee and re-queue its parked events."""
	_require_hr()
	device_user_id = str(device_user_id or "").strip()
	if not device_user_id:
		frappe.throw(_("Missing TimePay user id."))
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Employee {0} not found.").format(employee))

	# Uniqueness — the id must not already belong to another employee.
	clash = frappe.get_all(
		"Employee",
		filters={"custom_timepay_id": device_user_id, "name": ["!=", employee]},
		pluck="name",
		limit=1,
	)
	if clash:
		frappe.throw(_("TimePay id {0} is already linked to {1}.").format(device_user_id, clash[0]))

	parked = frappe.get_all(
		_RAW_EVENT,
		filters={"device_user_id": device_user_id, "processing_status": "Unmatched"},
		fields=["name", "device_user_name"],
		limit_page_length=0,
	)
	fio = next((p.device_user_name for p in parked if p.device_user_name), None)

	emp = frappe.get_doc("Employee", employee)
	emp.custom_timepay_id = device_user_id
	if fio and not emp.custom_timepay_name:
		emp.custom_timepay_name = fio
	emp.save(ignore_permissions=False)

	# Re-queue parked events so the next process run turns them into check-ins.
	for p in parked:
		frappe.db.set_value(
			_RAW_EVENT, p.name, {"processing_status": "Pending", "error_message": None}, update_modified=False
		)
	return {"employee": employee, "device_user_id": device_user_id, "requeued": len(parked)}
