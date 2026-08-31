"""What an operator is told when a shop-floor stock posting is refused.

Frappe-free on purpose. The decision is a mapping and a rule about wording, and
keeping it out of `manufacturing.py` is what lets `make check` execute it — the
whole module there imports frappe at the top and only the bench run can load it.

The strings are English source strings, translated at the throw site with `_()`
the same way every other user-facing message in this app is. They are constants
and must stay constants; `test_wo_posting_errors.py` refuses a substitution slot
in either of them, because a slot is how an item code finds its way back into a
message that still reads as sanitised.
"""

from __future__ import annotations

#: The store cannot cover a line. Measured on anjan 2026-08-31: all three of the
#: one pure operator's open Work Orders are in this state, so this is the likely
#: outcome of pressing Start, not an edge case.
SHORT_STOCK = "The store does not have enough of this order's materials. Tell the shift lead."

#: Everything else ERPNext can refuse with.
POST_FAILED = "This could not be recorded. Tell the shift lead."


def operator_posting_error(exc_name: str) -> str | None:
	"""The words an operator gets instead of ERPNext's own.

	@param exc_name `type(exception).__name__` of what the posting raised.
	@returns the replacement message, or None when the original must reach the
	         operator unchanged.

	Default-deny, and that is the whole design: ERPNext raises from a dozen places
	in `stock_entry.py` alone and several of them interpolate a row's item into the
	message, so an unrecognised class is assumed to name something rather than
	assumed safe. Enumerating the safe ones is a list that goes stale silently on
	the next ERPNext upgrade; enumerating the unsafe ones is a list that goes stale
	loudly, by leaking.

	Only managers ever see the original — the caller decides that, not this
	function, because "who is asking" is a question about the session and this
	module has none.
	"""
	if exc_name == "PermissionError":
		# Names no item, and is the one refusal an operator can act on. It is what
		# every Manufacturing User met on every Work Order on anjan until the
		# Custom DocPerm row landed on 2026-08-31; replacing it with a shrug would
		# have hidden that root cause rather than the recipe.
		return None
	if exc_name == "NegativeStockError":
		return SHORT_STOCK
	return POST_FAILED
