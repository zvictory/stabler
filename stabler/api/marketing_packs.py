"""Vertical Pack toggle API.

Admin-only endpoints to list, seed, and toggle Vertical Packs — bundles of
Custom Fields that get materialized when the pack is enabled.

The heavy lifting (creating Custom Fields) lives in the VerticalPack
controller's `before_save` hook.
"""

from __future__ import annotations

import json
import os

import frappe
from frappe import _

from stabler.api.admin import _require_admin


def _fixtures_dir() -> str:
	return frappe.get_app_path("stabler", "fixtures", "vertical_packs")


def _load_fixture(pack_key: str) -> dict | None:
	path = os.path.join(_fixtures_dir(), f"{pack_key}.json")
	if not os.path.isfile(path):
		return None
	with open(path, encoding="utf-8") as f:
		return json.load(f)


def _doc_to_dict(doc) -> dict:
	return {
		"name": doc.name,
		"pack_key": doc.pack_key,
		"label": doc.label,
		"enabled": int(doc.enabled or 0),
		"last_applied_at": doc.last_applied_at,
		"required_fields_json": doc.required_fields_json,
		"additional_doctypes_json": doc.additional_doctypes_json,
	}


@frappe.whitelist()
def list_vertical_packs():
	"""Return all Vertical Pack docs (lightweight columns)."""
	_require_admin()
	rows = frappe.get_all(
		"Vertical Pack",
		fields=["name", "pack_key", "label", "enabled", "last_applied_at"],
		order_by="pack_key asc",
	)
	for r in rows:
		r["enabled"] = int(r.get("enabled") or 0)
	return rows


@frappe.whitelist()
def seed_vertical_packs():
	"""Upsert one Vertical Pack per fixture JSON. Idempotent — no auto-enable."""
	_require_admin()

	results = []
	directory = _fixtures_dir()
	if not os.path.isdir(directory):
		frappe.throw(_("Fixtures directory missing: {0}").format(directory))

	for fname in sorted(os.listdir(directory)):
		if not fname.endswith(".json"):
			continue
		path = os.path.join(directory, fname)
		with open(path, encoding="utf-8") as f:
			payload = json.load(f)

		pack_key = payload.get("pack_key")
		if not pack_key:
			continue

		required_fields = payload.get("required_fields") or []
		required_fields_json = json.dumps(required_fields, ensure_ascii=False, indent=2)

		if frappe.db.exists("Vertical Pack", pack_key):
			doc = frappe.get_doc("Vertical Pack", pack_key)
			doc.label = payload.get("label") or doc.label
			doc.required_fields_json = required_fields_json
			doc.save(ignore_permissions=True)
			results.append({"pack_key": pack_key, "action": "updated"})
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Vertical Pack",
					"pack_key": pack_key,
					"label": payload.get("label") or pack_key,
					"enabled": 0,
					"required_fields_json": required_fields_json,
				}
			)
			doc.insert(ignore_permissions=True)
			results.append({"pack_key": pack_key, "action": "created"})

	return results


@frappe.whitelist()
def toggle_vertical_pack(pack_key: str, enabled):
	"""Flip a pack's enabled flag. Creates the doc from fixture if missing."""
	_require_admin()

	if not pack_key:
		frappe.throw(_("pack_key is required"))

	enabled_int = 1 if str(enabled) in ("1", "true", "True") else 0

	if not frappe.db.exists("Vertical Pack", pack_key):
		payload = _load_fixture(pack_key)
		if not payload:
			frappe.throw(_("Unknown vertical pack: {0}").format(pack_key))
		required_fields = payload.get("required_fields") or []
		doc = frappe.get_doc(
			{
				"doctype": "Vertical Pack",
				"pack_key": pack_key,
				"label": payload.get("label") or pack_key,
				"enabled": 0,
				"required_fields_json": json.dumps(required_fields, ensure_ascii=False, indent=2),
			}
		)
		doc.insert(ignore_permissions=True)

	doc = frappe.get_doc("Vertical Pack", pack_key)
	doc.enabled = enabled_int
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return _doc_to_dict(doc)
