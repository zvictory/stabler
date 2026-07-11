"""Stabler BRV Setting — dated BRV (Base Reference Value, UZS) master.

One row per decree; the customs-clearance fee reads the value in force on a date
(imports_module/customs_fee_math.effective_brv). System Manager / Imports Manager only.
"""

import frappe
from frappe.model.document import Document


class StablerBRVSetting(Document):
	pass
