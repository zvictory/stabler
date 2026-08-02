"""Pure Python landed cost calculation and bid ranking module.

This module is frappe-free and site-free so it can be tested standalone.
It implements the landed cost rules (IAS 2 §11 - non-recoverable taxes only),
completeness detection (K3 rule), and dual ranking (cheapest_price vs cheapest_landed).
"""

from __future__ import annotations

import json


def parse_landed_charges(raw_charges) -> tuple[float, list[dict], bool]:
	"""Parse landed charges JSON string or list.

	Returns (total_landed_amount, clean_charges_list, has_estimate).
	Tax Rule (IAS 2 §11): Recoverable VAT (charge_type 'VAT' or is_recoverable_vat)
	is NOT capitalized into landed cost.
	"""
	if not raw_charges:
		return 0.0, [], False

	if isinstance(raw_charges, str):
		try:
			charges = json.loads(raw_charges)
		except (ValueError, TypeError):
			return 0.0, [], False
	elif isinstance(raw_charges, list):
		charges = raw_charges
	else:
		return 0.0, [], False

	if not isinstance(charges, list) or len(charges) == 0:
		return 0.0, [], False

	total = 0.0
	clean_charges = []
	for c in charges:
		if not isinstance(c, dict):
			continue
		amount = float(c.get("amount") or c.get("base_amount") or 0.0)
		charge_type = str(c.get("charge_type") or c.get("account") or "").strip()
		is_vat = bool(c.get("is_recoverable_vat")) or charge_type.upper() in ("VAT", "VALUE ADDED TAX", "НДС")

		capitalized_amount = 0.0 if is_vat else amount
		total += capitalized_amount

		clean_charges.append(
			{
				"charge_type": charge_type or "General",
				"description": str(c.get("description") or ""),
				"amount": amount,
				"is_recoverable_vat": is_vat,
				"capitalized_amount": capitalized_amount,
			}
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
