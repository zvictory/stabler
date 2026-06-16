"""Whitelisted gate/device/mapping/raw-event admin API.

Serves the SPA pages that manage:
  - Stabler Gate Device            (list + save)
  - Stabler Employee Device Mapping (list + save + delete)
  - Stabler Raw Attendance Event    (list — read-only; plus reprocess stub)

Every endpoint rejects Guest and checks frappe.has_permission.
Named-record mutators additionally call _assert_can_write/_assert_can_read
(defence-in-depth against IDOR — @frappe.whitelist gates the method, not the
specific record).
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from stabler.api._common import _assert_can_read, _assert_can_write

_GATE_DEVICE = "Stabler Gate Device"
_MAPPING = "Stabler Employee Device Mapping"
_RAW_EVENT = "Stabler Raw Attendance Event"

# ── per-doctype permission guards ─────────────────────────────────────────────

def _guard_device(ptype: str = "read") -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)
	if not frappe.has_permission(_GATE_DEVICE, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _guard_mapping(ptype: str = "read") -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)
	if not frappe.has_permission(_MAPPING, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _guard_event(ptype: str = "read") -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)
	if not frappe.has_permission(_RAW_EVENT, ptype):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


# ── Stabler Gate Device ────────────────────────────────────────────────────────

_DEVICE_WRITABLE_FIELDS = {
	"device_name",
	"device_type",
	"integration_type",
	"enabled",
	"branch",
	"timezone",
	"status",
}

_DEVICE_LIST_FIELDS = [
	"name",
	"device_name",
	"integration_type",
	"enabled",
	"branch",
	"status",
	"last_sync",
]


@frappe.whitelist()
def list_gate_devices() -> list[dict]:
	"""Return all Gate Devices (name, device_name, integration_type, enabled,
	branch, status, last_sync)."""
	_guard_device("read")
	return frappe.get_all(
		_GATE_DEVICE,
		fields=_DEVICE_LIST_FIELDS,
		order_by="device_name asc",
	)


@frappe.whitelist()
def save_gate_device(payload) -> dict:
	"""Create or update a Stabler Gate Device.

	`payload` may be a JSON string or dict. If `name` is present and the doc
	exists the endpoint updates it (per-doc write permission checked to prevent
	IDOR). Otherwise a new doc is created.

	Returns ``{"name": "<docname>"}``.
	"""
	_guard_device("read")  # base check; write/create checked below

	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("Invalid payload — expected JSON object."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	device_name = (payload.get("device_name") or "").strip()
	if not device_name:
		frappe.throw(_("device_name is required."))

	existing_name = payload.get("name", "").strip()
	is_update = bool(existing_name and frappe.db.exists(_GATE_DEVICE, existing_name))

	if is_update:
		_assert_can_write(_GATE_DEVICE, existing_name, "write")
		doc = frappe.get_doc(_GATE_DEVICE, existing_name)
	else:
		if not frappe.has_permission(_GATE_DEVICE, "create"):
			frappe.throw(_("Not permitted to create Gate Devices."), frappe.PermissionError)
		doc = frappe.new_doc(_GATE_DEVICE)

	for field in _DEVICE_WRITABLE_FIELDS:
		if field in payload:
			doc.set(field, payload[field])

	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name}


# ── Stabler Employee Device Mapping ───────────────────────────────────────────

_MAPPING_WRITABLE_FIELDS = {
	"employee",
	"device",
	"device_user_id",
	"phone",
	"status",
	"active_from",
	"active_to",
}

_MAPPING_LIST_FIELDS = [
	"name",
	"employee",
	"employee_name",
	"device",
	"device_user_id",
	"phone",
	"status",
	"active_from",
	"active_to",
]


@frappe.whitelist()
def list_device_mappings(
	search: str = "",
	status: str = "",
	limit: int | str = 200,
) -> list[dict]:
	"""List Employee Device Mappings.

	Supports optional text ``search`` over employee_name / device_user_id, and
	optional ``status`` filter (Active / Inactive).

	Returns fields: name, employee, employee_name, device, device_user_id, phone,
	status, active_from, active_to.
	"""
	_guard_mapping("read")

	try:
		limit = int(limit)
	except (TypeError, ValueError):
		limit = 200

	filters: list = []
	if status:
		filters.append([_MAPPING, "status", "=", status])
	if search:
		search_like = f"%{search}%"
		# frappe.get_all doesn't support OR filters natively; use db.get_all
		# with a condition list. We use two separate passes and merge instead so
		# we stay on the safe whitelist-only path (no raw SQL / f-strings).
		by_name = frappe.get_all(
			_MAPPING,
			filters=filters + [[_MAPPING, "employee_name", "like", search_like]],
			fields=_MAPPING_LIST_FIELDS,
			order_by="employee_name asc",
			limit_page_length=limit,
		)
		by_uid = frappe.get_all(
			_MAPPING,
			filters=filters + [[_MAPPING, "device_user_id", "like", search_like]],
			fields=_MAPPING_LIST_FIELDS,
			order_by="employee_name asc",
			limit_page_length=limit,
		)
		# Merge, deduplicate by name, preserve order.
		seen: set[str] = set()
		merged: list[dict] = []
		for row in by_name + by_uid:
			if row["name"] not in seen:
				seen.add(row["name"])
				merged.append(row)
		return merged[:limit]

	return frappe.get_all(
		_MAPPING,
		filters=filters,
		fields=_MAPPING_LIST_FIELDS,
		order_by="employee_name asc",
		limit_page_length=limit,
	)


@frappe.whitelist()
def save_device_mapping(payload) -> dict:
	"""Create or update a Stabler Employee Device Mapping.

	`payload` may be a JSON string or dict. If `name` is present and the doc
	exists → per-doc write permission is checked (anti-IDOR) before update.
	Otherwise a new doc is created.

	Validates:
	  - employee and device_user_id must be non-empty.
	  - (employee, device_user_id) pair must be unique (no duplicate mappings).

	Returns ``{"name": "<docname>"}``.
	"""
	_guard_mapping("read")  # base; write/create checked below

	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("Invalid payload — expected JSON object."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	employee = (payload.get("employee") or "").strip()
	device_user_id = (payload.get("device_user_id") or "").strip()
	if not employee:
		frappe.throw(_("employee is required."))
	if not device_user_id:
		frappe.throw(_("device_user_id is required."))

	existing_name = payload.get("name", "").strip()
	is_update = bool(existing_name and frappe.db.exists(_MAPPING, existing_name))

	# Duplicate check: the (employee, device_user_id) pair must not exist on
	# any other doc.
	dup_filters = {"employee": employee, "device_user_id": device_user_id}
	dups = frappe.get_all(_MAPPING, filters=dup_filters, fields=["name"], limit=2)
	for dup in dups:
		if not is_update or dup["name"] != existing_name:
			frappe.throw(
				_("A mapping for employee {0} with device user ID {1} already exists ({2}).").format(
					employee, device_user_id, dup["name"]
				)
			)

	if is_update:
		_assert_can_write(_MAPPING, existing_name, "write")
		doc = frappe.get_doc(_MAPPING, existing_name)
	else:
		if not frappe.has_permission(_MAPPING, "create"):
			frappe.throw(_("Not permitted to create Employee Device Mappings."), frappe.PermissionError)
		doc = frappe.new_doc(_MAPPING)

	for field in _MAPPING_WRITABLE_FIELDS:
		if field in payload:
			doc.set(field, payload[field])

	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def delete_device_mapping(name: str) -> dict:
	"""Delete a Stabler Employee Device Mapping by name.

	Checks delete permission per-doc (anti-IDOR) before deletion.

	Returns ``{"name": "<docname>", "deleted": true}``.
	"""
	_guard_mapping("delete")
	if not name:
		frappe.throw(_("name is required."))
	if not frappe.db.exists(_MAPPING, name):
		frappe.throw(_("Employee Device Mapping {0} not found.").format(name), frappe.DoesNotExistError)
	_assert_can_write(_MAPPING, name, "delete")
	frappe.delete_doc(_MAPPING, name, ignore_permissions=False)
	frappe.db.commit()
	return {"name": name, "deleted": True}


# ── Stabler Raw Attendance Event (read-only + reprocess stub) ─────────────────

_EVENT_LIST_FIELDS = [
	"name",
	"external_event_id",
	"device",
	"device_user_id",
	"timestamp",
	"direction",
	"processing_status",
	"matched_employee",
	"error_message",
]


@frappe.whitelist()
def list_raw_events(
	processing_status: str = "",
	device: str = "",
	limit: int | str = 200,
	start: int | str = 0,
) -> list[dict]:
	"""List Raw Attendance Events (newest first).

	Optional filters:
	  - ``processing_status``: one of Pending / Processed / Duplicate / Unmatched / Error.
	  - ``device``: name of a Stabler Gate Device.

	Returns fields: name, external_event_id, device, device_user_id, timestamp,
	direction, processing_status, matched_employee, error_message.
	"""
	_guard_event("read")

	try:
		limit = int(limit)
	except (TypeError, ValueError):
		limit = 200
	try:
		start = int(start)
	except (TypeError, ValueError):
		start = 0

	filters: dict = {}
	if processing_status:
		filters["processing_status"] = processing_status
	if device:
		filters["device"] = device

	return frappe.get_all(
		_RAW_EVENT,
		filters=filters,
		fields=_EVENT_LIST_FIELDS,
		order_by="timestamp desc",
		limit_page_length=limit,
		limit_start=start,
	)


@frappe.whitelist()
def reprocess_raw_event(name: str) -> dict:
	"""Reset a Raw Attendance Event to Pending so the processor re-runs it.

	Only ``processing_status`` is mutated — all immutable source fields
	(external_event_id, device, device_user_id, timestamp, direction, source,
	raw_payload) are left untouched.

	Returns ``{"name": "<docname>", "processing_status": "Pending"}``.
	"""
	_guard_event("read")
	if not name:
		frappe.throw(_("name is required."))
	if not frappe.db.exists(_RAW_EVENT, name):
		frappe.throw(_("Raw Attendance Event {0} not found.").format(name), frappe.DoesNotExistError)
	_assert_can_write(_RAW_EVENT, name, "write")

	doc = frappe.get_doc(_RAW_EVENT, name)
	doc.processing_status = "Pending"
	doc.error_message = None
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "processing_status": doc.processing_status}
