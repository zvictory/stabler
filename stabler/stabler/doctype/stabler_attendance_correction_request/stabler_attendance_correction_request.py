# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Request-body fields that are frozen once the correction has been Applied.
# Operational metadata (review_note, approver, reviewed_at, linked_attendance,
# payroll_impact) may still be touched by the API after application.
_LOCKED_WHEN_APPLIED = (
	"employee",
	"correction_date",
	"correction_type",
	"before_value",
	"requested_value",
	"reason",
)


class StablerAttendanceCorrectionRequest(Document):
	"""HR-initiated request to correct an attendance record for one employee-date.

	Lifecycle: Draft → Pending (submitted for approval) → Approved/Rejected
	→ Applied (the correction has been written to the attendance layer).

	Once status reaches Applied the request body is frozen — only System Manager
	may alter core fields (for emergency data-fix, with a full audit trail).
	The API layer sets payroll_impact and linked_attendance after application.
	"""

	def validate(self):
		before = self.get_doc_before_save()

		# Stamp requested_by on first save if not already set.
		if self.is_new() and not self.requested_by:
			self.requested_by = frappe.session.user

		# Stamp reviewed_at when the approver acts.
		if (
			self.status in ("Approved", "Rejected")
			and not self.reviewed_at
		):
			self.reviewed_at = frappe.utils.now_datetime()
			if not self.approver:
				self.approver = frappe.session.user

		# Immutability: once Applied, lock request-body fields for non-System-Managers.
		if (
			before
			and before.get("status") == "Applied"
			and "System Manager" not in frappe.get_roles()
		):
			changed = [
				f for f in _LOCKED_WHEN_APPLIED
				if (before.get(f) or "") != (self.get(f) or "")
			]
			if changed:
				frappe.throw(
					_("Applied corrections are locked. Cannot change: {0}").format(
						", ".join(changed)
					),
					title=_("Correction locked"),
				)
