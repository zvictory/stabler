"""Pre-declaration customs cost estimate from HS (TN VED) rates (WP-I13, pure).

Estimates boj / excise / import VAT BEFORE the GTD exists, from the declared
(bank) value and a per-HS-code rate table. The GTD remains authoritative once
cleared (the LCV uses GTD figures); this is a planning number.

Model (matches the MSA agreement): the customs value is the DECLARED value —
the bank/official portion — optionally scaled onto items proportionally, plus
the transport bank portion (CIF logic). VAT base = customs value + duty +
excise; VAT is never part of landed cost (recoverable input VAT).
"""

from __future__ import annotations


def _amt(v) -> float:
	try:
		return float(v or 0)
	except TypeError, ValueError:
		return 0.0


def scale_to_declared(items, declared_total) -> list[dict]:
	"""Scale item amounts proportionally so they sum to the declared value."""
	rows = [dict(i or {}) for i in items or []]
	total = sum(_amt(r.get("amount")) for r in rows)
	dec = _amt(declared_total)
	k = (dec / total) if total > 0 and dec > 0 else (1.0 if dec <= 0 else 0.0)
	for r in rows:
		r["declared_amount"] = round(_amt(r.get("amount")) * k, 2) if total > 0 else 0.0
	return rows


def estimate(items, rates_by_hs, transport_bank=0, default_vat_pct=12.0) -> dict:
	"""Full estimate. ``items`` = [{hs_code, amount, declared_amount?}];
	``rates_by_hs`` = {hs_code: {duty_pct, excise_pct, vat_pct}}.

	Transport (bank leg) joins the customs value but carries no own HS duty —
	it inflates the ad-valorem base proportionally via the VAT base and is
	dutied at 0 here (duty on freight is embedded in goods rates in practice).
	"""
	rows = []
	unrated = []
	duty = excise = 0.0
	declared_goods = 0.0
	for it in items or []:
		r = dict(it or {})
		base = _amt(r.get("declared_amount", r.get("amount")))
		declared_goods += base
		rate = (rates_by_hs or {}).get((r.get("hs_code") or "").strip())
		if not rate:
			unrated.append(r.get("hs_code") or "(none)")
			r.update({"duty": 0.0, "excise": 0.0, "rated": False})
		else:
			d = round(base * _amt(rate.get("duty_pct")) / 100.0, 2)
			e = round(base * _amt(rate.get("excise_pct")) / 100.0, 2)
			duty += d
			excise += e
			r.update({"duty": d, "excise": e, "rated": True})
		r["declared_amount"] = round(base, 2)
		rows.append(r)

	customs_value = round(declared_goods + _amt(transport_bank), 2)
	vat_base = round(customs_value + duty + excise, 2)
	vat = round(vat_base * _amt(default_vat_pct) / 100.0, 2)
	return {
		"rows": rows,
		"unrated_hs_codes": sorted(set(unrated)),
		"customs_value": customs_value,
		"transport_bank": round(_amt(transport_bank), 2),
		"duty_total": round(duty, 2),
		"excise_total": round(excise, 2),
		"vat_base": vat_base,
		"vat_total": vat,
		# landed-cost'a binen kısım (KDV hariç)
		"capitalized_total": round(duty + excise, 2),
		"payable_to_customs": round(duty + excise + vat, 2),
	}
