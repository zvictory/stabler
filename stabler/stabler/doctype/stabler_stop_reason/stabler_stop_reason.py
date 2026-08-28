"""Why a line stopped, or why product was lost.

Stabler-side rather than ERPNext's `Downtime Entry.stop_reason`, because that
field is a fixed seven-option Select written for a machine shop -- `On-machine
press checks`, `Excessive machine set up time` -- and cannot be extended without
a customisation. A catalogue nobody can correct is one whose commonest entry
becomes "Other".
"""

from __future__ import annotations

from frappe.model.document import Document


class StablerStopReason(Document):
	pass
