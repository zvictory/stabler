from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class CRMStageEvent(Document):
	def before_save(self):
		if not self.is_new():
			frappe.throw(_("CRM Stage Event records are immutable."))

	def on_trash(self):
		frappe.throw(_("CRM Stage Event records are immutable."))
