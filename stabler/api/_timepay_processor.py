"""Pure planning helpers for the Timepay attendance processor.

This module stays Frappe-free. The integration layer owns database reads/writes;
these helpers only decide how raw events should be grouped and translated.
"""

from __future__ import annotations

from collections import OrderedDict

from stabler.api._attendance_ingest import resolve_employee


def _date_of_timestamp(value) -> str:
	text = str(value or "")
	return text[:10] if len(text) >= 10 else ""


def raw_event_to_punch(event: dict) -> dict:
	timestamp = str(event.get("timestamp") or "")
	return {
		"timestamp": timestamp.replace(" ", "T")[:19],
		"direction": str(event.get("direction") or "UNKNOWN").upper(),
	}


def attendance_status_from_summary(summary: dict) -> str:
	status = str((summary or {}).get("status") or "").lower()
	if status == "absent":
		return "Absent"
	if status == "half_day":
		return "Half Day"
	if status == "holiday":
		return "On Leave"
	return "Present"


def resolve_timepay_employee(
	event: dict,
	mappings: list[dict],
	employees_by_timepay_id: dict[str, list[str]] | None = None,
) -> str | None:
	employee = resolve_employee(
		{
			**event,
			"timestamp": raw_event_to_punch(event)["timestamp"],
			"device_id": event.get("device"),
		},
		mappings,
	)
	if employee:
		return employee
	matches = (employees_by_timepay_id or {}).get(str(event.get("device_user_id") or "").strip(), [])
	return matches[0] if len(matches) == 1 else None


def plan_raw_event_groups(
	events: list[dict],
	mappings: list[dict],
	employees_by_timepay_id: dict[str, list[str]] | None = None,
) -> dict:
	groups: OrderedDict[tuple[str, str], dict] = OrderedDict()
	unmatched = []
	for event in events:
		date = _date_of_timestamp(event.get("timestamp"))
		employee = resolve_timepay_employee(event, mappings, employees_by_timepay_id)
		if not employee:
			unmatched.append(event)
			continue
		key = (employee, date)
		if key not in groups:
			groups[key] = {"employee": employee, "date": date, "events": []}
		groups[key]["events"].append(event)
	return {"groups": list(groups.values()), "unmatched": unmatched}
