# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document


class StablerAttendanceRuleSet(Document):
	def validate(self):
		if self.is_default:
			# Only one rule set can be default per company at a time.
			frappe.db.set_value(
				"Stabler Attendance Rule Set",
				{"is_default": 1, "company": self.company, "name": ("!=", self.name)},
				"is_default",
				0,
			)
