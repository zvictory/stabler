# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Fields that capture "what the device reported". Once written they are evidence
# and must never change — only the processing-status fields may be updated by the
# processor. System Manager is exempt for genuine data-fix emergencies (audited).
_IMMUTABLE = (
	"external_event_id",
	"device",
	"device_user_id",
	"device_user_name",
	"timestamp",
	"direction",
	"raw_payload",
	"source",
)


class StablerRawAttendanceEvent(Document):
	"""Immutable landing record for one gate punch (Phase 2).

	Stored before any processing so events are auditable and replayable. The
	source fields are frozen after creation; the processor only advances
	processing_status / matched_employee / created_checkin / error_message.
	"""

	def validate(self):
		if self.is_new():
			return
		if "System Manager" in frappe.get_roles():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [f for f in _IMMUTABLE if (before.get(f) or "") != (self.get(f) or "")]
		if changed:
			frappe.throw(
				_("Raw attendance events are immutable. Cannot change: {0}").format(", ".join(changed)),
				title=_("Immutable record"),
			)

	def on_trash(self):
		if "System Manager" not in frappe.get_roles():
			frappe.throw(
				_("Raw attendance events cannot be deleted (audit evidence)."),
				title=_("Delete blocked"),
			)
