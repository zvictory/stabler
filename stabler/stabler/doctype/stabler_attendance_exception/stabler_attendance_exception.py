# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class StablerAttendanceException(Document):
	"""One detected exception for a given employee-date pair.

	Raised by the attendance processor when it cannot cleanly resolve a day's
	punches. Workflow: Open → Resolved (HR acts) or Ignored (explicitly skipped).
	The resolved_by / resolved_at fields are stamped by the controller on status
	transitions away from Open, so they are always trustworthy.
	"""

	def validate(self):
		if self.status in ("Resolved", "Ignored") and not self.resolved_by:
			self.resolved_by = frappe.session.user
		if self.status in ("Resolved", "Ignored") and not self.resolved_at:
			self.resolved_at = frappe.utils.now_datetime()
