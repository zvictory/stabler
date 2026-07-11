"""Pure, frappe-free BRV customs-clearance fee math.

Ports the Django ``CustomsFeeService`` (proforma_app/services/customs_fee_service.py)
and the ``BRVSetting`` / ``CustomsFeeTier`` lookups (core/models.py) into a
bench-free module so the fee arithmetic can be unit-tested without a live site.

The clearance fee is the government-set administrative/broker fee (NOT an
ad-valorem import duty — that lives on the Customs Declaration): a BRV (Base
Reference Value, a UZS amount set by decree) multiplied by a tier factor chosen
by the CI's USD value, plus a 25%-of-BRV surcharge for out-of-hours clearance.

    fee = tier_multiplier(value_usd) x BRV  (+ 0.25 x BRV when off_hours)

All money is ``Decimal``. The frappe-facing wiring (read the BRV/tier rows,
read the CI docs_total, write the CI fields) lives in ``imports_module/hooks.py``.
"""

from __future__ import annotations

from decimal import Decimal

_OFF_HOURS_FACTOR = Decimal("0.25")


def _dec(value) -> Decimal:
	"""Coerce to Decimal via str() so floats don't leak binary noise."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value if value is not None else 0))


def effective_brv(settings_rows, on_date) -> Decimal:
	"""Return the BRV value in force on ``on_date``.

	``settings_rows`` is a list of ``{"effective_date": ..., "value_uzs": ...}``.
	Picks the row with the greatest ``effective_date`` that is ``<= on_date``
	(Django ``BRVSetting.get_effective``). Raises ``ValueError`` when no row is
	effective yet (never silently defaults — a missing BRV is a real config gap).

	``effective_date`` values and ``on_date`` must be mutually comparable
	(``datetime.date`` objects, or ISO ``yyyy-mm-dd`` strings — both sort
	correctly).
	"""
	eligible = [r for r in settings_rows if r.get("effective_date") is not None and r["effective_date"] <= on_date]
	if not eligible:
		raise ValueError(f"No BRV setting is effective on {on_date}")
	row = max(eligible, key=lambda r: r["effective_date"])
	return _dec(row.get("value_uzs"))


def tier_multiplier(tiers, value_usd) -> Decimal:
	"""Return the BRV multiplier for a CI USD value (Django ``CustomsFeeTier.get_tier``).

	``tiers`` is a list of ``{"min_value_usd", "max_value_usd", "multiplier"}``;
	``max_value_usd`` may be ``None`` for an open-ended top tier. A row matches
	when ``min <= value_usd`` and (``max is None`` or ``value_usd <= max``).
	Raises ``ValueError`` when no tier covers the value.
	"""
	value = _dec(value_usd)
	for tier in tiers:
		lo = _dec(tier.get("min_value_usd"))
		hi = tier.get("max_value_usd")
		if value < lo:
			continue
		if hi is not None and value > _dec(hi):
			continue
		return _dec(tier.get("multiplier"))
	raise ValueError(f"No customs fee tier covers value ${value}")


def customs_fee(value_usd, tiers, brv_value, off_hours: bool = False) -> dict:
	"""Full clearance-fee breakdown for a CI value.

	Returns ``{fee_uzs, multiplier, brv_value, base_fee, off_hours_surcharge}``
	(all ``Decimal``). ``brv_value`` is the resolved BRV (see ``effective_brv``);
	the tier is chosen from ``tiers`` by ``value_usd``.
	"""
	brv = _dec(brv_value)
	multiplier = tier_multiplier(tiers, value_usd)
	base_fee = multiplier * brv
	surcharge = (_OFF_HOURS_FACTOR * brv) if off_hours else Decimal("0")
	return {
		"fee_uzs": base_fee + surcharge,
		"multiplier": multiplier,
		"brv_value": brv,
		"base_fee": base_fee,
		"off_hours_surcharge": surcharge,
	}
