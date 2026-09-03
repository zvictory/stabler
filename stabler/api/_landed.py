"""Pure Python landed cost calculation and bid ranking module.

This module is frappe-free and site-free so it can be tested standalone.
It implements the landed cost rules (IAS 2 §11 - non-recoverable taxes only),
completeness detection (K3 rule), and dual ranking (cheapest_price vs cheapest_landed).
"""

from __future__ import annotations

import json

from stabler.api._landed_charge_types import is_vat_charge_type, resolve_charge_type
from stabler.stabler.tender_landed_math import line_value


def _charge_rows(raw_charges) -> list[dict]:
	"""Decode a stored/posted landed payload into a list of dicts. Shared by both shapes.

	Anything that is not a list of dicts is an empty set of charges, not an error:
	this runs on stored data that predates the field and on hand-edited JSON, and a
	read must render what it finds rather than throw on it.
	"""
	if not raw_charges:
		return []
	if isinstance(raw_charges, str):
		try:
			charges = json.loads(raw_charges)
		except (ValueError, TypeError):
			return []
	elif isinstance(raw_charges, list):
		charges = raw_charges
	else:
		return []
	if not isinstance(charges, list):
		return []
	return [c for c in charges if isinstance(c, dict)]


def raw_charge_line(c: dict) -> dict:
	"""RAW SHAPE -- one line exactly as the officer left it. The only shape ever stored.

	Sanitisation only: types, trimming, an upper-cased currency code. Nothing here
	values anything, and in particular `amount` is passed through untouched.

	ADR-605 second review, P0. `parse_landed_charges` used to be BOTH the reader and
	the write normaliser, so `update_quotation_landed` persisted its output: a
	half-finished currency switch (USD picked on a line already holding 3 200 000
	so'm) was written back as `amount: 0.0, amount_original: 0.0`, and on the next
	read that is an EMPTY line -- 0.0, unflagged. The officer's figure was destroyed
	and every warning went quiet, in the very response the save returned. A write
	path may not store a figure it derived; it stores what it was given, and the
	reader derives again every time.
	"""
	currency = str(c.get("currency") or "").strip().upper()
	original = c.get("amount_original")
	charge_type = str(c.get("charge_type") or c.get("account") or "").strip()
	return {
		"charge_type": charge_type or "General",
		"description": str(c.get("description") or ""),
		# The company-currency figure AS GIVEN. On a line that names a currency this
		# is normally 0 (the officer types into the currency box instead) -- but when
		# it is not, that figure is the whole evidence the line is half-switched, and
		# losing it is the defect this shape exists to prevent.
		"amount": float(c.get("amount") or c.get("base_amount") or 0.0),
		# Kept as None on a line with no currency so the two boxes cannot be confused
		# for one another, and NOT coerced to 0.0 on a currency line -- "nothing typed
		# yet" and "typed zero" read the same downstream, and only the first is a
		# half-switch waiting to be finished.
		"amount_original": float(original) if (currency and original is not None) else None,
		"currency": currency,
		"fx_rate": float(c.get("fx_rate") or 0.0),
		# Provenance, not arithmetic: WHICH day's quote the rate is.
		"rate_date": str(c.get("rate_date") or "").strip()[:10],
		"is_recoverable_vat": bool(c.get("is_recoverable_vat")),
	}


def sanitize_charge_lines(raw_charges) -> list[dict]:
	"""Every line of a payload in the RAW shape -- the whole job of a write path.

	`update_quotation_landed` calls this and nothing else before storing. It is
	deliberately NOT `parse_landed_charges`: see `raw_charge_line`.
	"""
	return [raw_charge_line(c) for c in _charge_rows(raw_charges)]


def parse_landed_charges(raw_charges) -> tuple[float, list[dict], bool]:
	"""READ-ONLY derivation: the VALUED SHAPE of every line, and what they add up to.

	Returns (total_landed_amount, clean_charges_list, has_estimate).
	Tax Rule (IAS 2 §11): Recoverable VAT (a line stored under the type VAT used to
	be, or is_recoverable_vat) is NOT capitalized into landed cost.

	NOTHING PERSISTS WHAT THIS RETURNS. It is derived fresh on every read, and the
	write path stores `sanitize_charge_lines`' RAW shape instead -- see
	`raw_charge_line` for the P0 that rule exists to prevent. A valued line is the
	raw line verbatim plus three derived keys:

	  `amount`             the company-currency figure AS GIVEN (raw, never derived)
	  `amount_original`    the figure as typed in the line's own `currency` (raw)
	  `company_amount`     DERIVED: what the line is worth in company currency
	  `capitalized_amount` DERIVED: `company_amount` unless VAT or unvalued
	  `unvalued`           DERIVED: whether it could be valued at all
	  `charge_type_canonical` DERIVED: ADR-606's one list (`_landed_charge_types`)
	  `charge_type_unmapped`  DERIVED: the text that list did not recognise
	  `charge_type_is_vat`    DERIVED: whether the STORED spelling is a VAT alias
	  `is_recoverable_vat_stored` DERIVED: the flag AS STORED, before the forcing

	ADR-606. `charge_type` itself is left EXACTLY as stored -- "Freight", "VAT",
	"Local Delivery" -- and the canonical key sits beside it, because this is a
	read: rewriting the stored string here would put a derivation where the
	evidence was, which is the mistake `raw_charge_line` above exists to prevent.

	`amount` and `company_amount` are deliberately two keys and not one. They differ
	on exactly the lines that matter -- a currency line, where the officer types into
	the currency box and `amount` stays 0, and a half-switched line, where `amount`
	still holds the so'm figure and `company_amount` is 0 because nothing can value
	it. Collapsing them is how the first review's P0 was written.

	`tender._parse_landed` (the PO editor) keeps the older convention where the
	returned `amount` IS the derived figure; seven call sites and `api.lcv` sum it.
	Aligning the two is a separate change, not this one. Both go through
	`line_value`, so they cannot disagree about what a line is worth.

	Whether a line can be valued at all is `tender_landed_math.line_value`'s single
	rule, shared with `tender._parse_landed` so one Purchase Order cannot show two
	landed totals depending on which screen asked. An `unvalued` line is kept out of
	the total, never added at its raw number (1 200 USD entering a so'm total as
	1 200) and never as a bare zero: both read as CHEAP and hand the tender to the
	wrong vendor.

	Unlike `save_po_landed_charges` the write path does not REFUSE such a line -- a
	pre-win estimate is typed by one officer under deadline and must be saveable
	half-finished -- so the flag is what the editor, the comparison table, the award
	snapshot and the pre-win bid estimate all use to name the gap.
	"""
	rows = _charge_rows(raw_charges)
	if not rows:
		return 0.0, [], False

	total = 0.0
	clean_charges = []
	for c in rows:
		raw = raw_charge_line(c)
		charge_type = raw["charge_type"]
		# ADR-606: VAT stopped being a type and became the flag, so the alias
		# table is what recognises a legacy VAT line now -- and it forces the flag
		# rather than merely renaming the line, or recoverable input tax would
		# start capitalizing into the landed cost of the goods.
		canonical, unmapped = resolve_charge_type(charge_type)
		stored_is_vat = is_vat_charge_type(charge_type)
		is_vat = raw["is_recoverable_vat"] or stored_is_vat
		# One rule, stated once, shared with `tender._parse_landed` — see
		# `tender_landed_math.line_value`. A PO customs line reaches this function
		# with a stored amount and no currency, and keeps the figure the ГТД
		# declares; a currency line is valued only from what was typed IN that
		# currency, never from the company-currency figure beside it.
		company_amount, unvalued = line_value(
			raw["amount"], raw["amount_original"], raw["currency"], raw["fx_rate"]
		)

		capitalized_amount = 0.0 if (is_vat or unvalued) else company_amount
		total += capitalized_amount

		# VALUED SHAPE = the raw line, untouched, PLUS what it is worth. The two are
		# kept apart on purpose: `amount` is always the figure the officer gave and
		# `company_amount` always the derived one, so no consumer can read one for
		# the other and no writer can store a derivation by accident.
		clean_charges.append(
			dict(
				raw,
				is_recoverable_vat=is_vat,
				# ADR-606: which of the nine types this line is, and -- when the
				# stored string was none of them -- the words it was written in,
				# so the editor can keep them instead of showing a bare "Other".
				charge_type_canonical=canonical,
				charge_type_unmapped=unmapped,
				# Whether the STORED spelling is one of the VAT aliases -- not
				# whether this line is recoverable, which `is_recoverable_vat`
				# above already says. The editor needs the difference: clearing
				# the checkbox on a line still spelled "VAT" is an edit this
				# function would undo on the next read, so the editor answers it
				# by moving the stored type as well. It may not work that out
				# for itself without keeping a copy of the alias table, which is
				# the duplication ADR-606 exists to remove -- so the fact is
				# stated here, where the table lives.
				charge_type_is_vat=stored_is_vat,
				# The flag AS STORED, beside the merged one above. The editor
				# sends this back on a line it did not edit, or a save made for
				# an unrelated reason persists the alias table's verdict into
				# the evidence field: a row stored `{"charge_type": "VAT",
				# "is_recoverable_vat": false}` comes back true and stays true.
				is_recoverable_vat_stored=raw["is_recoverable_vat"],
				# 0.0 on an unvalued line is not a figure, it is the absence of one;
				# `unvalued` is what says so. Nothing may sum it without reading that.
				company_amount=company_amount,
				capitalized_amount=capitalized_amount,
				unvalued=unvalued,
			)
		)

	return round(total, 6), clean_charges, True


def calculate_quotation_landed(quotation: dict) -> dict:
	"""Calculate base_landed_total for a single quotation dictionary.

	Returns updated copy with `landed_charges_total`, `base_landed_total`, and `has_landed_estimate`.
	"""
	q = dict(quotation)
	base_grand_total = float(q.get("base_grand_total") or q.get("grand_total") or 0.0)
	raw_charges = q.get("custom_landed_charges") or q.get("landed_charges")

	charges_total, clean_charges, has_estimate = parse_landed_charges(raw_charges)

	q["base_grand_total"] = base_grand_total
	q["landed_charges_total"] = charges_total
	q["base_landed_total"] = round(base_grand_total + charges_total, 6)
	q["has_landed_estimate"] = has_estimate
	# ADR-605: this quotation's total is SHORT by whatever the unvalued lines hold.
	# The K3 completeness rule cannot see it -- the estimate exists, it is just
	# incomplete -- so the flag travels with the row to whoever ranks on the total.
	q["has_unvalued_charges"] = any(c.get("unvalued") for c in clean_charges)
	q["clean_landed_charges"] = clean_charges
	return q


def rank_quotations_landed(quotations_list: list[dict]) -> dict:
	"""Rank a set of quotations for a tender lot/deal.

	Dual Ranking & Completeness Rule (K3 & K4):
	- cheapest_price: minimum sticker price (base_grand_total)
	- cheapest_landed: minimum landed total (base_landed_total) ONLY IF all quotations
	  in the set have landed cost estimates. If any quotation lacks an estimate,
	  estimate_complete is False and no cheapest_landed flag is awarded.
	"""
	if not quotations_list:
		return {
			"quotations": [],
			"cheapest_price_quote": None,
			"cheapest_landed_quote": None,
			"estimate_complete": False,
			"missing_estimates": [],
		}

	processed = [calculate_quotation_landed(q) for q in quotations_list]

	# Price ranking
	min_price_quote = min(processed, key=lambda q: q["base_grand_total"])
	min_price = min_price_quote["base_grand_total"]

	# Completeness check (K3)
	missing_estimates = [q["name"] for q in processed if not q["has_landed_estimate"] and q.get("name")]
	estimate_complete = len(missing_estimates) == 0 and len(processed) > 0

	min_landed_quote = None
	min_landed = 0.0
	if estimate_complete:
		min_landed_quote = min(processed, key=lambda q: q["base_landed_total"])
		min_landed = min_landed_quote["base_landed_total"]

	ranked = []
	for q in processed:
		is_cheapest_price = (q.get("name") == min_price_quote.get("name")) if min_price_quote else False
		is_cheapest_landed = (
			estimate_complete and min_landed_quote and q.get("name") == min_landed_quote.get("name")
		)

		price_delta = round(q["base_grand_total"] - min_price, 2)
		price_pct = round((price_delta / min_price * 100.0), 2) if min_price > 0 else 0.0

		if estimate_complete:
			landed_delta = round(q["base_landed_total"] - min_landed, 2)
			landed_pct = round((landed_delta / min_landed * 100.0), 2) if min_landed > 0 else 0.0
		else:
			landed_delta = 0.0
			landed_pct = 0.0

		q_copy = dict(q)
		q_copy.update(
			{
				"is_cheapest_price": is_cheapest_price,
				"is_cheapest_landed": is_cheapest_landed,
				"price_delta": price_delta,
				"price_pct": price_pct,
				"landed_delta": landed_delta,
				"landed_pct": landed_pct,
			}
		)
		ranked.append(q_copy)

	return {
		"quotations": ranked,
		"cheapest_price_quote": min_price_quote.get("name") if min_price_quote else None,
		"cheapest_landed_quote": min_landed_quote.get("name") if min_landed_quote else None,
		"estimate_complete": estimate_complete,
		"missing_estimates": missing_estimates,
	}
