"""Follow-up Log — append-only collections contact history."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


class VehicleFinanceFollowUpLog(Document):
	def validate(self) -> None:
		if not self.is_new() and not getattr(self.flags, "vf_internal", False):
			frappe.throw(_("Follow-up Log entries are append-only."))
		self.logged_by = self.logged_by or frappe.session.user
		self.logged_on = self.logged_on or now()

	def on_trash(self) -> None:
		frappe.throw(_("Follow-up Log entries are append-only and cannot be deleted."))
