"""Money rules for tender landed-charge lines. Deliberately Frappe-free.

WP-T3. A landed charge is often quoted in the forwarder's or the declarant's own
currency while the PO control board compares vendors in company currency. This
module holds the one rule that turns the first into the second, so it is covered
by `make check` rather than only by a live bench.

Sibling: `imports_module/lcv_math.line_company_amount` does the same job for the
imports LCV and reaches the same two conclusions -- round to 2, and refuse rather
than guess when the rate is missing. It is not reused here because it converts a
batch of lines against one date-keyed rate map, while a tender landed line
carries its own rate and its own quote date; forcing one signature over both
would make each read worse than it does apart. If either side ever changes its
rounding or its missing-rate stance, the other is wrong and should be changed
with it.
"""

from __future__ import annotations


def converted_amount(amount, currency, fx_rate) -> float | None:
	"""One landed-charge line in company currency, or None if it cannot be valued.

	An empty `currency` means the figure is already in company currency -- which
	is every line stored before WP-T3, so they pass through untouched and a stray
	rate on such a line is ignored rather than applied.

	`None` is returned, never a number, when a currency is named without a usable
	rate. The caller must keep that line out of any total. Falling back to the raw
	figure would drop a 1 200 USD charge into a so'm total as 1 200, and falling
	back to zero would make the charge free; both read as CHEAP and both hand the
	tender to the wrong vendor, which is the failure this rule exists to prevent.
	"""
	amt = float(amount or 0)
	if not currency:
		return round(amt, 2)
	rate = float(fx_rate or 0)
	if rate <= 0:
		return None
	return round(amt * rate, 2)
