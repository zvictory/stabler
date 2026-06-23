"""Doc-event hook: compute a line's billable qty from its dimension inputs.

Registered as `before_validate` on Sales Order + Sales Invoice. Whatever the entry
path (Stabler SPA, Desk, REST), if a line carries length/width/height/pieces and
its item is dimensional (Item.custom_dimension_mode), the qty (in the item's stock
UOM = m / m² / m³) is recomputed here — so it is authoritative and never trusts a
client-sent qty for dimensional items. Rate stays per stock UOM → amount = qty×rate
and ERPNext stock/valuation/GL remain consistent.
"""

import frappe
from frappe.utils import flt

from stabler.api._dimensions import dimensional_qty, is_dimensional


def apply_dimensional_qty(doc, method=None):
	# Pre-patch safety: the custom column may not exist yet.
	if not frappe.db.has_column("Item", "custom_dimension_mode"):
		return
	for it in (doc.get("items") or []):
		if not getattr(it, "item_code", None):
			continue
		mode = frappe.get_cached_value("Item", it.item_code, "custom_dimension_mode")
		if not is_dimensional(mode):
			continue
		# Only override when the user actually entered measurements on this line —
		# otherwise leave a manually-typed qty alone.
		if not any(flt(it.get(f)) for f in ("custom_length", "custom_width", "custom_height")):
			continue
		q = dimensional_qty(
			mode,
			length=it.get("custom_length"),
			width=it.get("custom_width"),
			height=it.get("custom_height"),
			pieces=it.get("custom_pieces"),
		)
		if q is not None:
			it.qty = q
