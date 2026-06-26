# Copyright (c) 2026, Stabler and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StablerSOStage(Document):
	def on_trash(self):
		"""Guard: never orphan Sales Orders parked on this stage."""
		in_use = frappe.db.count("Sales Order", {"custom_board_stage": self.name})
		if in_use:
			frappe.throw(
				frappe._("Cannot delete stage '{0}' — {1} Sales Order(s) are still in it. "
				         "Move them first.").format(self.name, in_use)
			)
