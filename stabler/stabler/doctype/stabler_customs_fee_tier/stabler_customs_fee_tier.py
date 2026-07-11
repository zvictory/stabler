"""Stabler Customs Fee Tier — BRV-multiplier tiers by CI USD value.

Clearance fee = multiplier x BRV; the tier is chosen by the CI value
(imports_module/customs_fee_math.tier_multiplier). System Manager / Imports Manager only.
"""

import frappe
from frappe.model.document import Document


class StablerCustomsFeeTier(Document):
	pass
