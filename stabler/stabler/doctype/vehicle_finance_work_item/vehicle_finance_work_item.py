"""Work Item — one generated collections/payables task.

Storage for the deterministic queue: the scheduler writes one row per fired
policy, identified by `company + agreement + schedule_row + event_type +
policy_date`, and the work status axis lives here so it can move without ever
touching the agreement, the schedule or any money.
"""

from __future__ import annotations

from frappe.model.document import Document
from frappe.utils import now


class VehicleFinanceWorkItem(Document):
	def validate(self) -> None:
		self.generated_on = self.generated_on or now()
		if self.work_status == "Resolved":
			self.resolved_on = self.resolved_on or now()
		else:
			self.resolved_on = None
