from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate, today

from stabler.api._attendance_rules import policies_from_ruleset
from stabler.api._attendance_processor import summarize_day
from stabler.api._timepay_processor import (
	attendance_status_from_summary,
	plan_raw_event_groups,
	raw_event_to_punch,
)

RAW_EVENT = "Stabler Raw Attendance Event"
MAPPING = "Stabler Employee Device Mapping"
EXCEPTION = "Stabler Attendance Exception"
LOG = "Stabler Attendance Processing Log"
RULESET = "Stabler Attendance Rule Set"
PROCESSOR_VERSION = "timepay-processor-v1"


def _settings_enabled() -> bool:
	return bool(
		frappe.db.exists("DocType", "Stabler Timepay Credential")
		and frappe.db.get_single_value("Stabler Timepay Credential", "enabled")
	)


def _json(data: Any) -> str:
	return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _date_filter(date: str | None) -> list:
	if not date:
		return []
	return [[RAW_EVENT, "timestamp", "between", [f"{date} 00:00:00", f"{date} 23:59:59"]]]


def _pending_raw_events(date: str | None = None, limit: int | None = None) -> list[dict]:
	filters: list = [[RAW_EVENT, "processing_status", "=", "Pending"]]
	filters.extend(_date_filter(date))
	return frappe.get_all(
		RAW_EVENT,
		filters=filters,
		fields=[
			"name",
			"external_event_id",
			"device",
			"device_user_id",
			"device_user_name",
			"timestamp",
			"direction",
			"source",
			"raw_payload",
			"processing_status",
		],
		order_by="timestamp asc",
		limit_page_length=int(limit or 1000),
	)


def _mapping_rows() -> list[dict]:
	rows = frappe.get_all(
		MAPPING,
		filters={"status": "Active"},
		fields=["employee", "device", "device_user_id", "timepay_full_name", "active_from", "active_to", "status"],
		limit_page_length=10000,
	)
	out = []
	for row in rows:
		out.append({
			**row,
			"device_id": row.get("device"),
			"active_from": str(row.get("active_from") or ""),
			"active_to": str(row.get("active_to") or ""),
		})
	return out


def _employee_timepay_rows() -> dict[str, list[str]]:
	if not frappe.db.has_column("Employee", "custom_timepay_id"):
		return {}
	rows = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "custom_timepay_id"],
		limit_page_length=10000,
	)
	out: dict[str, list[str]] = {}
	for row in rows:
		timepay_id = str(row.get("custom_timepay_id") or "").strip()
		if not timepay_id:
			continue
		out.setdefault(timepay_id, []).append(row["name"])
	return out


def _set_raw_status(events: list[dict], status: str, **values) -> None:
	for event in events:
		frappe.db.set_value(
			RAW_EVENT,
			event["name"],
			{
				"processing_status": status,
				**values,
			},
			update_modified=True,
		)


def _log(raw_event: str | None, result: str, **values) -> None:
	frappe.get_doc({
		"doctype": LOG,
		"raw_event": raw_event,
		"processor_version": PROCESSOR_VERSION,
		"result": result,
		**values,
	}).insert(ignore_permissions=True)


def _upsert_exception(
	*,
	employee: str | None,
	company: str | None,
	date: str,
	exception_type: str,
	raw_event: str | None,
	details: str,
) -> str:
	filters = {
		"exception_date": date,
		"exception_type": exception_type,
		"status": "Open",
	}
	if employee:
		filters["employee"] = employee
	if raw_event:
		filters["raw_event"] = raw_event
	existing = frappe.db.get_value(EXCEPTION, filters, "name")
	if existing:
		doc = frappe.get_doc(EXCEPTION, existing)
	else:
		doc = frappe.new_doc(EXCEPTION)
		doc.exception_date = date
		doc.exception_type = exception_type
		doc.status = "Open"
	if employee:
		doc.employee = employee
	if company:
		doc.company = company
	if raw_event:
		doc.raw_event = raw_event
	doc.details = details
	doc.save(ignore_permissions=True)
	return doc.name


def _exception_type(raw_type: str) -> str:
	return {
		"single_punch": "missing_check_out",
		"excess_punches": "manual_review",
		"present_but_under_threshold": "manual_review",
	}.get(raw_type, raw_type)


def _employee_context(employee: str, date: str) -> dict:
	emp = frappe.get_doc("Employee", employee)
	shift = _active_shift(employee, date) or emp.default_shift
	shift_start = "09:00"
	shift_label = "DAY"
	holiday_list = emp.holiday_list
	if shift and frappe.db.exists("Shift Type", shift):
		shift_doc = frappe.get_doc("Shift Type", shift)
		shift_start = _hm(shift_doc.start_time) or "09:00"
		holiday_list = holiday_list or shift_doc.holiday_list
		if _hour(shift_start) >= 18:
			shift_label = "NIGHT"
	is_holiday = _is_holiday(holiday_list, date)
	return {
		"company": emp.company,
		"hire_date": str(emp.date_of_joining or date),
		"termination_date": str(emp.relieving_date) if emp.relieving_date else None,
		"shift": shift_label,
		"shift_type": shift,
		"shift_start_hm": shift_start,
		"is_holiday": is_holiday,
	}


def _active_shift(employee: str, date: str) -> str | None:
	rows = frappe.get_all(
		"Shift Assignment",
		filters=[
			["Shift Assignment", "employee", "=", employee],
			["Shift Assignment", "status", "=", "Active"],
			["Shift Assignment", "start_date", "<=", date],
		],
		fields=["shift_type", "start_date", "end_date"],
		order_by="start_date desc",
		limit_page_length=20,
	)
	for row in rows:
		end_date = row.get("end_date")
		if not end_date or str(end_date) >= date:
			return row.get("shift_type")
	return None


def _hm(value) -> str | None:
	if value is None:
		return None
	text = str(value)
	if " " in text:
		text = text.split(" ", 1)[1]
	return text[:5] if len(text) >= 5 else None


def _hour(hm: str) -> int:
	try:
		return int(hm.split(":", 1)[0])
	except Exception:
		return 9


def _is_holiday(holiday_list: str | None, date: str) -> bool:
	if not holiday_list:
		return False
	return bool(
		frappe.db.exists(
			"Holiday",
			{"parent": holiday_list, "holiday_date": date},
		)
	)


def _ruleset(company: str) -> dict:
	name = frappe.db.get_value(
		RULESET,
		{"company": company, "enabled": 1, "is_default": 1},
		"name",
	)
	if not name:
		name = frappe.db.get_value(RULESET, {"enabled": 1, "is_default": 1}, "name")
	return frappe.get_doc(RULESET, name).as_dict() if name else {}


def _checkin_for_event(employee: str, event: dict, shift_type: str | None) -> str:
	existing = frappe.db.get_value(
		"Employee Checkin",
		{
			"employee": employee,
			"time": event["timestamp"],
			"log_type": event["direction"],
			"device_id": event.get("device"),
		},
		"name",
	)
	if existing:
		return existing
	doc = frappe.get_doc({
		"doctype": "Employee Checkin",
		"employee": employee,
		"time": event["timestamp"],
		"log_type": event["direction"],
		"device_id": event.get("device"),
		"shift": shift_type,
		"skip_auto_attendance": 1,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def _attendance_for_day(employee: str, date: str, company: str) -> str | None:
	return frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": date, "company": company, "docstatus": ["<", 2]},
		"name",
	)


def _processor_owns_attendance(attendance_name: str) -> bool:
	return bool(
		frappe.db.exists(
			LOG,
			{
				"created_document": attendance_name,
				"processor_version": PROCESSOR_VERSION,
				"result": "Processed",
			},
		)
	)


def _has_manual_correction(employee: str, date: str, company: str) -> bool:
	if frappe.db.exists(
		"Stabler Attendance Correction Request",
		{"employee": employee, "correction_date": date, "status": "Applied"},
	):
		return True
	attendance_name = _attendance_for_day(employee, date, company)
	return bool(attendance_name and not _processor_owns_attendance(attendance_name))


def _upsert_attendance(employee: str, date: str, ctx: dict, summary: dict) -> str:
	existing = _attendance_for_day(employee, date, ctx["company"])
	if existing:
		doc = frappe.get_doc("Attendance", existing)
	else:
		doc = frappe.new_doc("Attendance")
		doc.employee = employee
		doc.attendance_date = date
		doc.company = ctx["company"]
	doc.status = attendance_status_from_summary(summary)
	doc.shift = ctx.get("shift_type")
	doc.in_time = _dt(date, summary.get("entry"))
	doc.out_time = _dt(date, summary.get("exit"))
	doc.working_hours = round(float(summary.get("worked_min") or 0) / 60, 2)
	doc.late_entry = 1 if int(summary.get("late_min") or 0) > 0 else 0
	doc.early_exit = 1 if int(summary.get("early_leave_min") or 0) > 0 else 0
	doc.save(ignore_permissions=True)
	if doc.docstatus == 0:
		doc.submit()
	return doc.name


def _dt(date: str, hm: str | None):
	if not hm:
		return None
	return datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M")


def _process_group(group: dict) -> dict:
	employee = group["employee"]
	date = group["date"]
	events = group["events"]
	ctx = _employee_context(employee, date)
	if _has_manual_correction(employee, date, ctx["company"]):
		_set_raw_status(events, "Pending", matched_employee=employee, error_message="Skipped: manual correction applied")
		for event in events:
			_log(event["name"], "Skipped Manual", before_value=_json(event))
		return {"processed": 0, "skipped_manual": len(events), "errors": 0}

	punches = [raw_event_to_punch(event) for event in events]
	late, night, half, min_worked = policies_from_ruleset(_ruleset(ctx["company"]))
	summary = summarize_day(
		punches,
		shift=ctx["shift"],
		shift_start_hm=ctx["shift_start_hm"],
		is_holiday=ctx["is_holiday"],
		date_str=date,
		hire_date=ctx["hire_date"],
		termination_date=ctx["termination_date"],
		late=late,
		half=half,
		night=night,
		min_worked_present=min_worked,
	)
	checkins = []
	for event in events:
		checkins.append(_checkin_for_event(employee, event, ctx.get("shift_type")))
	attendance_name = _upsert_attendance(employee, date, ctx, summary)
	for raw_type in summary.get("exceptions") or []:
		_upsert_exception(
			employee=employee,
			company=ctx["company"],
			date=date,
			exception_type=_exception_type(raw_type),
			raw_event=events[0]["name"] if events else None,
			details=f"Timepay processor detected {raw_type}.",
		)
	_set_raw_status(
		events,
		"Processed",
		matched_employee=employee,
		created_checkin=", ".join(checkins),
		error_message=None,
	)
	for event in events:
		_log(
			event["name"],
			"Processed",
			created_document=attendance_name,
			after_value=_json({"summary": summary, "checkins": checkins}),
		)
	return {"processed": len(events), "skipped_manual": 0, "errors": 0}


def _unmatched_details(event: dict, employees_by_timepay_id: dict[str, list[str]]) -> str:
	timepay_id = str(event.get("device_user_id") or "").strip()
	timepay_name = str(event.get("device_user_name") or "").strip() or "unknown"
	matches = employees_by_timepay_id.get(timepay_id, [])
	if len(matches) > 1:
		return (
			f"Unmatched Timepay user {timepay_id} ({timepay_name}). "
			f"Ambiguous Employee custom_timepay_id matches: {', '.join(matches)}."
		)
	return f"Unmatched Timepay user {timepay_id} ({timepay_name}). No active mapping or unique Employee custom_timepay_id."


def _mark_unmatched(event: dict, employees_by_timepay_id: dict[str, list[str]]) -> None:
	date = str(event.get("timestamp"))[:10]
	_upsert_exception(
		employee=None,
		company=None,
		date=date,
		exception_type="unmatched_gate_user",
		raw_event=event["name"],
		details=_unmatched_details(event, employees_by_timepay_id),
	)
	_set_raw_status([event], "Unmatched", error_message="No active mapping or unique Employee custom_timepay_id")
	_log(event["name"], "Unmatched", before_value=_json(event))


def process_pending(date: str | None = None, employee: str | None = None, limit: int | None = None) -> dict:
	events = _pending_raw_events(date=date, limit=limit)
	employees_by_timepay_id = _employee_timepay_rows()
	plan = plan_raw_event_groups(events, _mapping_rows(), employees_by_timepay_id)
	out = {"processed": 0, "unmatched": 0, "errors": 0, "skipped_manual": 0}
	for event in plan["unmatched"]:
		if employee:
			continue
		_mark_unmatched(event, employees_by_timepay_id)
		out["unmatched"] += 1
	for group in plan["groups"]:
		if employee and group["employee"] != employee:
			continue
		try:
			result = _process_group(group)
			for key in ("processed", "errors", "skipped_manual"):
				out[key] += result.get(key, 0)
		except Exception:
			out["errors"] += len(group["events"])
			msg = frappe.get_traceback()
			_set_raw_status(group["events"], "Error", error_message=msg[:1000])
			for event in group["events"]:
				_log(event["name"], "Error", error=msg[:2000], before_value=_json(event))
			frappe.log_error(title=f"timepay processor failed {group['employee']} {group['date']}", message=msg)
	frappe.db.commit()
	return out


def nightly_process() -> dict:
	if not _settings_enabled():
		return {"processed": 0, "unmatched": 0, "errors": 0, "skipped_manual": 0}
	return process_pending(date=add_days(today(), -1))


@frappe.whitelist()
def manual_process(date: str, employee: str | None = None) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if not frappe.has_permission(RAW_EVENT, "write"):
		frappe.throw(_("Not permitted to process Timepay attendance."), frappe.PermissionError)
	return process_pending(date=date, employee=employee)
