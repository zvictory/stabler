"""The scrap log's arithmetic. No frappe import on purpose, same as `_downtime`.

Why this exists, measured on anjan 2026-08-27, read-only. Unlike the stop log's
zeros, the numbers here are not empty — the floor already does this work, by hand:

    Scrap warehouses that already exist        2
      `Yaroqsiz mahsulotlar ombori - A`        opened 2026-05-02; 23 items,
                                               1 555 units, $719 on hand
      `Ishlab chiqarish yaroqsiz mahsulotlar ombori - A`
                                               opened 2026-07-12, used ONCE, $5.62
    Stock moved to scrap, all time             25 entries, 35 037 units, $3 941
    People doing it, by hand, in the Desk      3 (21 + 3 + 1 entries, latest 2026-08-22)
    How                                        Material Transfer into the scrap
                                               warehouse, then Material Issue to
                                               write it off; the reason survives
                                               only as a free-text Uzbek paragraph
                                               in `remarks`
    Value lands on                             `Stock Adjustment - A` ($3 849),
                                               `Oshxona sarfi - A`, `Salary - A`
    `process_loss_qty` on Work Order / Stock Entry   0 / 0
    `BOM Scrap Item` rows                      0
    Company currency / valuation               USD / FIFO, negative stock OFF

So the factory already reconciles scrap with the stock ledger. Nothing here
invents a flow; it gives the existing one a keyboard and a reason code. That is
also why the record writes a **draft** Material Transfer and never submits it:
the three people doing this today submit in the Desk, and an operator who could
submit stock movement from a kiosk would be a new authority, not a faster one.

There is no seed catalogue in this module. The reason list already exists and is
already seeded, translated and tested: `_downtime.SEED_REASONS` carries a `kind`
of `Downtime` / `Loss` / `Both`, seven of its rows are `Loss`, and
`manufacturing.list_stop_reasons(company, "Loss")` already returns them. A second
catalogue would fork a translated list for nothing.
"""

from __future__ import annotations

#: Quantities are compared after rounding to this many decimals. Stock UOMs here
#: are kg and pieces, and the failure being avoided is narrow but real: an
#: operator scrapping everything the order still holds types the number the screen
#: showed them, and a subtraction carried out in binary floats can leave that
#: number a 1e-15 hair above the ceiling. Refusing it would be arithmetically
#: correct and, to the person holding the bucket, nonsense.
_PLACES = 6


def _as_qty(value) -> float | None:
	"""A quantity, or None when the input is not one.

	None rather than 0.0: a blank field and a typed zero are different mistakes
	and get different messages. `_downtime._as_datetime` returns None for the
	same reason.
	"""
	if value is None:
		return None
	if isinstance(value, bool):
		return None
	if isinstance(value, (int, float)):
		return float(value)
	text = str(value).strip()
	if not text:
		return None
	try:
		return float(text)
	except ValueError:
		return None


def available_to_scrap(transferred_qty, consumed_qty, already_scrapped_qty=0) -> float:
	"""How much of one material this Work Order still has standing in WIP.

	`transferred_qty - consumed_qty` is ERPNext's own bookkeeping on
	`Work Order Item`: what was carried into the WIP warehouse for this order,
	less what has been written off against it. `already_scrapped_qty` is this
	log's own subtraction and it is the one ERPNext cannot make.

	The reason it cannot: the draft this log writes is a plain **Material
	Transfer**, not a `Material Transfer for Manufacture`. A plain transfer moves
	the stock and touches no Work Order field at all — deliberately, because a
	`for Manufacture` entry would increment `transferred_qty` and tell ERPNext
	that *more* material had arrived in WIP, which is the exact opposite of what
	happened. So the scrapped kilograms leave the warehouse without leaving
	`transferred_qty - consumed_qty`, and two scrap records for 5 kg each against
	6 kg of stock would each pass on their own. The second one would then fail on
	negative stock at submit — in the Desk, days later, in front of accounting,
	who cannot know what the right number was.

	Never negative. A floor whose books already disagree with itself should be
	told "there is nothing left to scrap", not handed a negative ceiling that
	makes every quantity look too large.
	"""
	transferred = _as_qty(transferred_qty) or 0.0
	consumed = _as_qty(consumed_qty) or 0.0
	scrapped = _as_qty(already_scrapped_qty) or 0.0
	return max(0.0, round(transferred - consumed - scrapped, _PLACES))


def validate_scrap(qty, available) -> tuple[bool, str]:
	"""Whether this quantity may be recorded, and why not.

	Returns a reason key rather than a sentence, the same contract as
	`_downtime.validate_stop`: the kiosk shows it under the field, the API throws
	it, and the wording lives in one place next to the doctype.
	"""
	amount = _as_qty(qty)
	if amount is None:
		return False, "missing_qty"
	amount = round(amount, _PLACES)
	if amount == 0:
		# The double-tap, and the mirror of `zero_length` on a stop. Recorded, it
		# adds a row to "how often do we lose product" while adding nothing to
		# "how much" — the shape that makes a frequency figure quietly wrong.
		return False, "zero_qty"
	if amount < 0:
		# Not merely invalid: a negative quantity on a Material Transfer reverses
		# it. The draft would carry stock *into* the line from the scrap
		# warehouse, and the record filed as a loss would read, in the ledger, as
		# a gain.
		return False, "negative_qty"
	ceiling = round(_as_qty(available) or 0.0, _PLACES)
	if ceiling <= 0:
		# Distinct from `more_than_wip_holds` because the fix is different: there
		# is nothing to correct on this form, the material was never carried into
		# WIP for this order (or has already been written off).
		return False, "nothing_in_wip"
	if amount > ceiling:
		return False, "more_than_wip_holds"
	return True, ""
