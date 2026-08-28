"""One recorded stop on one line.

Measured on anjan 2026-08-28: 0 Downtime Entry rows, against 3757 Manufacture
entries. ERPNext's own doctype cannot be saved on this site -- all three of its
required fields are unmet (`workstation` -> 0 Workstations, `operator` -> 439
Employees of which 0 carry a `user_id`, `stop_reason` -> a machine-shop Select).

This one is keyed on what the floor has: `wip_warehouse` for the line, the same
column the shift log filters and the plan board places on, and the signed-in
user for who reported it.
"""

from __future__ import annotations

from frappe import _, throw
from frappe.model.document import Document

from stabler.api._downtime import stop_minutes, validate_stop

#: The message shown for each refusal `validate_stop` can return. Kept here
#: rather than in the frappe-free helper so that module stays importable without
#: a bench, and so the wording is translated in one place.
_REFUSALS = {
	"missing_start": "A stop needs a start time.",
	"missing_end": "A stop needs an end time.",
	"zero_length": "A stop with no length is a double-tap, not an event.",
	"ends_before_it_starts": "The stop ends before it starts.",
	"too_long": "A stop longer than 12 hours is a forgotten timer. Split it, or correct the times.",
}


class StablerLineStop(Document):
	def validate(self):
		allowed, refusal = validate_stop(self.from_time, self.to_time)
		if not allowed:
			throw(_(_REFUSALS.get(refusal, "These times cannot be recorded.")))
		# Derived, never typed: a minutes column somebody can edit apart from the
		# stamps is one that disagrees with them, and the disagreement is silent.
		self.minutes = stop_minutes(self.from_time, self.to_time)
