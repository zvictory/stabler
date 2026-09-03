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


def line_value(amount, amount_original, currency, fx_rate) -> tuple[float, bool]:
	"""One landed-charge line in company currency, plus whether it could be valued.

	Returns ``(company_amount, unvalued)``. This is the ONE rule; both readers of a
	stored landed line -- `api._landed.parse_landed_charges` (quotation estimates,
	and the PO board's own total) and `api.tender._parse_landed` (the PO editor) --
	go through it, because until ADR-605's review they disagreed: one kept the
	stored figure on an unusable rate and the other dropped the line, so the same
	Purchase Order showed two landed totals depending on which screen asked.

	A line that NAMES a currency is valued only from `amount_original` at its own
	rate. `amount` is never a fallback for it: that number is company currency by
	construction, and re-labelling it as USD is not a smaller error than dropping
	it -- it is the ADR-605 defect with the sign reversed.

	`unvalued` is True, and the amount 0.0, when the line names a currency and
	either the rate is unusable OR nothing was typed in that currency while a
	company-currency figure is sitting in `amount`. Both cases mean the line cannot
	be valued; the caller must keep it out of every total AND say so on screen,
	because a total that silently shrinks reads as CHEAP and hands the tender to
	the wrong vendor.

	A currency line with nothing on either side is an EMPTY line, not a broken one:
	0.0, not flagged. Flagging it would park a permanent warning under every row an
	officer has only started typing.
	"""
	if not currency:
		return round(float(amount or 0), 2), False
	original = float(amount_original or 0)
	if not original:
		# Nothing typed in the named currency. If a company-currency figure is
		# sitting in `amount`, the line is a half-finished currency switch and must
		# be flagged rather than quietly valued at that figure or at zero.
		return (0.0, bool(float(amount or 0)))
	converted = converted_amount(original, currency, fx_rate)
	if converted is None:
		return 0.0, True
	return converted, False
