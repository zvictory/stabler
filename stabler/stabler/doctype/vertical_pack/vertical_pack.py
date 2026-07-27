"""Vertical Pack — toggleable bundle of Custom Fields for industry verticals.

When `enabled` flips 0 -> 1, the controller parses `required_fields_json` and
materializes each entry as a Custom Field via
`create_custom_field`. The helper is idempotent so re-enabling is safe.

When `enabled` flips 1 -> 0 the Custom Fields are NOT removed — data
preservation. We only clear `last_applied_at` and add a comment.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.model.document import Document
from frappe.utils import now_datetime


class VerticalPack(Document):
	def before_save(self) -> None:
		# Detect transition by comparing to db value.
		prev = None
		if not self.is_new():
			prev = frappe.db.get_value("Vertical Pack", self.name, "enabled")
		prev_int = int(prev or 0)
		new_int = int(self.enabled or 0)

		if prev_int == 0 and new_int == 1:
			self._apply_required_fields()
			self.last_applied_at = now_datetime()
		elif prev_int == 1 and new_int == 0:
			self.last_applied_at = None
			# Comment is added in `on_update` (doc must exist & be saved first).
			self._pending_disable_comment = True

	def on_update(self) -> None:
		if getattr(self, "_pending_disable_comment", False):
			try:
				self.add_comment(
					"Info",
					f"Vertical Pack '{self.pack_key}' disabled. Custom Fields preserved.",
				)
			except Exception:
				# Comments are best-effort — do not block the save.
				pass
			self._pending_disable_comment = False

	def _apply_required_fields(self) -> None:
		payload = self.required_fields_json or ""
		if not payload.strip():
			return
		try:
			entries = frappe.parse_json(payload) or []
		except Exception as e:
			frappe.throw(f"Invalid required_fields_json for pack '{self.pack_key}': {e}")

		if not isinstance(entries, list):
			frappe.throw(f"required_fields_json for pack '{self.pack_key}' must be a JSON array")

		for entry in entries:
			if not isinstance(entry, dict):
				continue
			dt = entry.get("dt")
			if not dt:
				continue
			# Build the Custom Field spec — strip the 'dt' meta key.
			spec = {k: v for k, v in entry.items() if k != "dt"}
			create_custom_field(dt, spec)
