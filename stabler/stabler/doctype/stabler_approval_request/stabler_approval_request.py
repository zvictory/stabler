# Copyright (c) 2026, Stabler and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document


class StablerApprovalRequest(Document):
	"""Maker-checker approval record for a money-movement document.

	The request is the audit trail: who asked (requested_by), who decided
	(reviewed_by), when, and the outcome (status). Segregation of duties is
	enforced in stabler.api.approvals — the reviewer must differ from the
	requester. This doc itself is intentionally NOT submittable; it is a
	lightweight tracking record so the SPA can render an approval queue
	without touching the Frappe Desk.
	"""

	def before_insert(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		if not self.requested_at:
			self.requested_at = frappe.utils.now_datetime()
		if not self.status:
			self.status = "Pending"
