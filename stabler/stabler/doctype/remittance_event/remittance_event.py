"""Append-only trail of everything that happened to a transfer.

Append-only is enforced, not merely asserted: the permissions grant read and create but
never write or delete, and both `validate` (on an existing row) and `on_trash` throw.
Same shape as `CRM Stage Event` and `Vehicle Finance Payment Application`.

The reason is narrower than "audit is good". The refund flow has two gates — approval
carries authority, payment moves cash — and the payout flow counts failed code attempts
towards a lock. If a row of this trail can be edited or removed after the fact, then how
many attempts were made and who approved what become unanswerable exactly when someone
is asking.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class RemittanceEvent(Document):
	def validate(self) -> None:
		if not self.is_new():
			frappe.throw(_("Remittance Event records are immutable. Write a new event instead."))

	def on_trash(self) -> None:
		frappe.throw(_("Remittance Event records are immutable and cannot be deleted."))
