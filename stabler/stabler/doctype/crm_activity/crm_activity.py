from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class CRMActivity(Document):
	def before_insert(self):
		self.created_by = frappe.session.user
		self.status = "Planned"

	def before_save(self):
		if not self.is_new() and not getattr(frappe.flags, "crm_activity_completion", False):
			frappe.throw(_("CRM Activity records may only be completed through the CRM API."))

	def on_trash(self):
		frappe.throw(_("CRM Activity records are immutable."))
