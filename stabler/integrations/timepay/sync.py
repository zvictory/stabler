from __future__ import annotations

import json
from datetime import date as Date
from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, today

from stabler.api._attendance_ingest import decide_event_action, dedupe_key
from stabler.integrations.timepay.client import TimepayClient
from stabler.integrations.timepay.credential import FrappeTimepayTokenStore, get_client_config

PAGE_LIMIT = 100
RAW_EVENT = "Stabler Raw Attendance Event"
PROCESSING_LOG = "Stabler Attendance Processing Log"
TIMEPAY_DEVICE_NAME = "Timepay API"


def _normalize_time(date: str, value: str | None) -> str | None:
	if not value:
		return None
	text = str(value).strip()
	if not text:
		return None
	if "T" in text:
		return text.replace("T", " ")[:19]
	if len(text) == 5:
		return f"{date} {text}:00"
	if len(text) == 8:
		return f"{date} {text}"
	return text


def events_from_daily_stat(row: dict[str, Any], *, date: str) -> list[dict[str, Any]]:
	stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
	device_user_id = str(row.get("id") or "").strip()
	if not device_user_id:
		return []
	device_user_name = str(row.get("full_name") or "").strip()
	raw_payload = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
	events = []
	for suffix, fieldname, direction in (
		("in", "first_check_in", "IN"),
		("out", "last_check_out", "OUT"),
	):
		timestamp = _normalize_time(date, stats.get(fieldname))
		if not timestamp:
			continue
		events.append({
			"external_event_id": f"timepay:{date}:{device_user_id}:{suffix}",
			"device_user_id": device_user_id,
			"device_user_name": device_user_name,
			"timestamp": timestamp,
			"direction": direction,
			"source": "TIMEPAY_API",
			"processing_status": "Pending",
			"raw_payload": raw_payload,
		})
	return events


def _iter_dates(start_date: str, end_date: str) -> list[str]:
	start = Date.fromisoformat(start_date)
	end = Date.fromisoformat(end_date)
	if end < start:
		raise ValueError("end_date must be on or after start_date")
	days = []
	current = start
	while current <= end:
		days.append(current.isoformat())
		current += timedelta(days=1)
	return days


class FrappeRawEventRepository:
	def __init__(self, *, device: str | None = None):
		self.device = device or ensure_timepay_device()

	def existing_keys(self, date: str) -> set[str]:
		start = f"{date} 00:00:00"
		end = f"{date} 23:59:59"
		rows = frappe.get_all(
			RAW_EVENT,
			filters={"source": "TIMEPAY_API", "timestamp": ["between", [start, end]]},
			fields=["external_event_id"],
			limit_page_length=10000,
		)
		return {dedupe_key({"external_event_id": row["external_event_id"]}) for row in rows if row.get("external_event_id")}

	def insert_raw_event(self, event: dict[str, Any]) -> str:
		doc = frappe.get_doc({
			"doctype": RAW_EVENT,
			"device": self.device,
			**event,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def log(self, **kwargs) -> None:
		doc = frappe.get_doc({
			"doctype": PROCESSING_LOG,
			"processor_version": "timepay-sync-v1",
			**kwargs,
		})
		doc.insert(ignore_permissions=True)


def fetch_daily_rows(
	client: TimepayClient,
	*,
	date: str,
	page_limit: int = PAGE_LIMIT,
	employee_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	offset = 0
	while True:
		page = client.daily_stats(date=date, offset=offset, limit=page_limit, employee_ids=employee_ids)
		page_rows = page.get("results") or []
		rows.extend(page_rows)
		if not page.get("next") or len(page_rows) == 0:
			break
		offset += page_limit
	return rows


def sync_date(
	*,
	client: TimepayClient,
	repo,
	date: str,
	page_limit: int = PAGE_LIMIT,
	employee_ids: list[int] | None = None,
) -> dict[str, int]:
	rows = fetch_daily_rows(client, date=date, page_limit=page_limit, employee_ids=employee_ids)
	seen = repo.existing_keys(date)
	inserted = 0
	duplicates = 0
	for row in rows:
		for event in events_from_daily_stat(row, date=date):
			action = decide_event_action(event, seen)
			if action == "duplicate":
				duplicates += 1
				repo.log(result="Duplicate", before_value=event.get("raw_payload"))
				continue
			raw_name = repo.insert_raw_event(event)
			seen.add(dedupe_key(event))
			inserted += 1
			repo.log(raw_event=raw_name, result="Processed", after_value=event.get("raw_payload"))
	return {"inserted": inserted, "duplicates": duplicates, "rows_seen": len(rows)}


def ensure_timepay_device() -> str:
	if frappe.db.exists("Stabler Gate Device", TIMEPAY_DEVICE_NAME):
		return TIMEPAY_DEVICE_NAME
	doc = frappe.get_doc({
		"doctype": "Stabler Gate Device",
		"device_name": TIMEPAY_DEVICE_NAME,
		"device_type": "API",
		"integration_type": "Timepay",
		"enabled": 1,
		"timezone": "Asia/Tashkent",
		"status": "Active",
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def _settings_enabled() -> bool:
	if not frappe.db.exists("DocType", "Stabler Timepay Credential"):
		return False
	return bool(frappe.db.get_single_value("Stabler Timepay Credential", "enabled"))


def sync_range(start_date: str, end_date: str | None = None, employee_ids: list[int] | None = None) -> dict[str, int]:
	if not _settings_enabled():
		return {"inserted": 0, "duplicates": 0, "rows_seen": 0}
	config = get_client_config()
	client = TimepayClient(
		FrappeTimepayTokenStore(),
		api_base=config["api_base"],
		origin=config["origin"],
	)
	repo = FrappeRawEventRepository()
	total = {"inserted": 0, "duplicates": 0, "rows_seen": 0, "errors": 0}
	for day in _iter_dates(start_date, end_date or start_date):
		# Per-day isolation: one day's API/parse failure must not abort the whole
		# range. Log it to the Processing Log and carry on to the next day.
		try:
			result = sync_date(client=client, repo=repo, date=day, employee_ids=employee_ids)
			for key in ("inserted", "duplicates", "rows_seen"):
				total[key] += result[key]
		except Exception:
			total["errors"] += 1
			repo.log(result="Error", error=f"{day}: {frappe.get_traceback()}")
			frappe.log_error(title=f"timepay sync failed for {day}", message=frappe.get_traceback())
	frappe.db.commit()
	return total


def nightly_sync() -> dict[str, int]:
	# "Yesterday" in the SITE timezone (Asia/Tashkent), not the server's clock —
	# frappe.utils.today() resolves against System Settings.time_zone.
	yesterday = add_days(today(), -1)
	return sync_range(yesterday, yesterday)


@frappe.whitelist()
def manual_sync(start_date: str, end_date: str | None = None) -> dict[str, int]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if not frappe.has_permission(RAW_EVENT, "create"):
		frappe.throw(_("Not permitted to sync Timepay attendance."), frappe.PermissionError)
	return sync_range(start_date, end_date or start_date)
