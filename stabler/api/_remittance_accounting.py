"""Pure remittance accounting — no Frappe, no DB.

Three items, three entries: **alacak → komisyon → verecek** (ADR-006 and the
worked example at ``docs/plans/2026-08-16-remittance-operations-center.md``
lines 182-214)::

    REGISTER  Dr origin desk cash        send ccy, tendered
              Cr Deferred commission     base ccy, commission
              Cr Receiver obligation     receive ccy, base = principal

    PAYOUT    Dr Receiver obligation     receive ccy, base = principal
              Cr destination desk cash   receive ccy, base = principal
              Dr Deferred commission     base ccy, commission
              Cr Commission revenue      base ccy, commission

    REFUND    Dr Receiver obligation     receive ccy, base = principal
              Dr Deferred commission     base ccy, commission
              Cr origin desk cash        send ccy, tendered

There is no FX margin account and no FX income line anywhere (ADR-009 cut five
GL accounts to three). The margin between the cashier's rate and the market
rate is therefore not recognised — it is carried inside the valuation of a
monetary balance and surfaces at period-end FX revaluation, which is where
ADR-008 says it belongs.

Why the obligation is valued at the principal
---------------------------------------------
``tendered = principal + commission`` closes to the minor unit by construction
(``_remittance_pricing``). So an entry whose cash leg is the tendered amount and
whose commission leg is the commission balances **iff** the obligation leg is
the principal. That is the whole reason the obligation is valued at principal
rather than at the market value of ``receiver_amount``: it is what makes the
entry close without a plug account.

Why the rate is derived and then verified
-----------------------------------------
The bead asks for the base value to be written directly and the rate derived
from it. Measured 2026-08-17 in ``erpnext/accounts/doctype/journal_entry``:

* ``set_amounts_in_company_currency`` (journal_entry.py:977) **overwrites** each
  row's ``debit``/``credit`` with ``*_in_account_currency * exchange_rate``. A
  base value written directly does not survive validation. The rate is the only
  lever ERPNext leaves.
* ``validate_multi_currency`` (journal_entry.py:955) **overwrites** each row's
  ``account_currency`` from the Account record, so the currency a caller passes
  is decoration; the account's own currency governs and must be checked.
* ``set_exchange_rate`` refetches the rate of the day whenever the supplied rate
  is blank **or exactly 1**, unless ``flags.ignore_exchange_rate`` is set. That
  is the ADR-008 trap, and the flag is how it is closed.

So the achievable form of "write the base, derive the rate" is: compute the
intended base value, derive the rate from it, then **assert** that
``round(amount * rate)`` reproduces that base value exactly. A rate that cannot
reproduce it raises rather than posting an entry that drifts a minor unit.

Which leg absorbs the plug
--------------------------
A row whose account currency equals the company currency has no free rate —
ERPNext pins it to 1. The plug therefore has to sit on a leg that still has a
rate to derive:

===========================  ==========================================
Case                         Plug
===========================  ==========================================
receive ccy != base ccy      obligation leg (base = tendered - commission)
receive == base, send != base cash leg (base = obligation + commission)
receive == base == send      none; the triple must already close in base
===========================  ==========================================
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Journal Entry Account.exchange_rate carries 9 decimals, and so does the
#: Remittance Transfer field that freezes it. Deriving at a finer precision than
#: the column stores would round on the way to the database.
RATE_PRECISION = 9


class AccountingError(ValueError):
	"""Refuse to post rather than post an entry that does not close."""


def _d(value: object, label: str) -> Decimal:
	"""Coerce to Decimal; raise rather than invent a number."""
	if isinstance(value, Decimal):
		return value
	try:
		# str() first: Decimal(0.1) would carry the binary tail into the cent.
		return Decimal(str(value).strip())
	except (InvalidOperation, TypeError, ValueError):
		raise AccountingError(f"{label} is not a number: {value!r}") from None


def _quantize(value: Decimal, precision: int) -> Decimal:
	"""Round to `precision` decimal places (ROUND_HALF_UP)."""
	quantum = Decimal(10) ** -precision
	return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _precision(value: object, label: str) -> int:
	try:
		places = int(value)
	except (TypeError, ValueError):
		raise AccountingError(f"{label} is not a whole number: {value!r}") from None
	if places < 0:
		raise AccountingError(f"{label} cannot be negative: {value!r}")
	return places


def derive_rate(
	*,
	base_amount: object,
	account_amount: object,
	base_precision: object = 2,
	rate_precision: int = RATE_PRECISION,
) -> Decimal:
	"""The exchange rate that reproduces `base_amount` from `account_amount`.

	Derived from the base value, never multiplied into it — and then verified,
	because ERPNext recomputes the base from this rate and would otherwise post
	an entry a minor unit away from the one that was calculated.

	The check demands a *margin*, not just equality: the exact product must sit
	clear of the half-minor-unit rounding boundary. ERPNext redoes this
	multiplication in binary floats, and a product sitting exactly on the
	boundary would round one way here and the other way there. A margin of one
	tenth of a minor unit is ~9 orders of magnitude wider than float error at
	these amounts, so agreeing here means agreeing there.

	It can only fail on amounts large enough that one rate ulp steps over the
	base currency's minor unit (``account_amount`` above roughly
	``10 ** (rate_precision - base_precision - 1)``). It raises there instead of
	silently drifting.
	"""
	base = _d(base_amount, "base_amount")
	amount = _d(account_amount, "account_amount")
	places = _precision(base_precision, "base_precision")

	if amount == 0:
		raise AccountingError("Cannot derive an exchange rate from a zero amount.")

	rate = _quantize(base / amount, rate_precision)
	drift = abs(amount * rate - base)
	minor = Decimal(10) ** -places
	if drift >= minor * Decimal("0.4"):
		raise AccountingError(
			f"Exchange rate {rate} on {amount} lands {drift} away from {base}. "
			f"The amount is too large for {rate_precision} rate decimals to hold the minor unit."
		)
	return rate


def base_values(
	*,
	principal: object,
	commission: object,
	tendered: object,
	receiver_amount: object,
	send_to_base: object,
	send_is_base: bool,
	receive_is_base: bool,
	base_precision: object = 2,
) -> dict:
	"""The three base amounts, anchored so the entry closes to the minor unit.

	`send_to_base` is the market rate frozen at register. It is ignored when the
	send currency already is the base currency, and it is only the *starting*
	anchor: when the receive currency is the base currency ERPNext pins the
	obligation's rate to 1, so the obligation is worth exactly `receiver_amount`
	and the cash leg carries the difference instead. That difference is the FX
	margin, which ADR-009 forbids recognising as income; it stays inside the cash
	account's base valuation and is picked up by period-end FX revaluation.
	"""
	places = _precision(base_precision, "base_precision")
	principal_d = _d(principal, "principal")
	commission_d = _d(commission, "commission")
	tendered_d = _d(tendered, "tendered")
	receiver_d = _d(receiver_amount, "receiver_amount")

	if principal_d <= 0:
		raise AccountingError(f"principal must be positive, got {principal_d}.")
	if commission_d < 0:
		raise AccountingError(f"commission cannot be negative, got {commission_d}.")
	if receiver_d <= 0:
		raise AccountingError(f"receiver_amount must be positive, got {receiver_d}.")
	if principal_d + commission_d != tendered_d:
		raise AccountingError(
			f"The stored triple does not close: {principal_d} + {commission_d} != {tendered_d}. "
			"Price the transfer through _remittance_pricing and store what it returns."
		)

	rate = Decimal(1) if send_is_base else _d(send_to_base, "send_to_base")
	if rate <= 0:
		raise AccountingError(f"send_to_base must be positive, got {rate}.")

	commission_base = _quantize(commission_d * rate, places)

	if not receive_is_base:
		cash_base = _quantize(tendered_d * rate, places)
		obligation_base = cash_base - commission_base
	elif not send_is_base:
		obligation_base = _quantize(receiver_d, places)
		cash_base = obligation_base + commission_base
	else:
		obligation_base = _quantize(receiver_d, places)
		cash_base = _quantize(tendered_d, places)
		if obligation_base + commission_base != cash_base:
			raise AccountingError(
				f"Send, receive and base are one currency, so no leg has a free rate: the "
				f"obligation ({obligation_base}) plus commission ({commission_base}) must equal "
				f"the tendered amount ({cash_base}). Check receiver_amount — in a same-currency "
				"transfer it has to be the principal."
			)

	if obligation_base <= 0:
		raise AccountingError(
			f"The obligation would be worth {obligation_base} in base currency. "
			"The commission cannot be worth more than the whole transfer."
		)

	return {
		"cash_base": cash_base,
		"commission_base": commission_base,
		"obligation_base": obligation_base,
		"base_precision": places,
	}


def _leg(
	*,
	account: str,
	currency: str,
	amount: Decimal,
	base: Decimal,
	rate: Decimal,
	debit: bool,
	remark: str,
) -> dict:
	side = "debit" if debit else "credit"
	other = "credit" if debit else "debit"
	return {
		"account": account,
		"account_currency": currency,
		"exchange_rate": rate,
		f"{side}_in_account_currency": amount,
		side: base,
		f"{other}_in_account_currency": Decimal(0),
		other: Decimal(0),
		"user_remark": remark,
	}


def _rate_for(base: Decimal, amount: Decimal, is_base: bool, places: int) -> Decimal:
	"""1 for a base-currency leg — ERPNext pins it there — else derived."""
	if is_base:
		return Decimal(1)
	return derive_rate(base_amount=base, account_amount=amount, base_precision=places)


def register_legs(
	*,
	amounts: dict,
	accounts: dict,
	tendered: object,
	receiver_amount: object,
	send_currency: str,
	receive_currency: str,
	base_currency: str,
	remark: str = "",
) -> dict:
	"""The three register legs, plus the obligation rate to freeze on the transfer.

	`accounts` names ``origin_cash``, ``deferred_commission`` and ``obligation``.
	`amounts` is what `base_values` returned.
	"""
	places = amounts["base_precision"]
	tendered_d = _d(tendered, "tendered")
	receiver_d = _d(receiver_amount, "receiver_amount")

	obligation_rate = _rate_for(
		amounts["obligation_base"], receiver_d, receive_currency == base_currency, places
	)
	cash_rate = _rate_for(amounts["cash_base"], tendered_d, send_currency == base_currency, places)

	legs = [
		_leg(
			account=accounts["origin_cash"],
			currency=send_currency,
			amount=tendered_d,
			base=amounts["cash_base"],
			rate=cash_rate,
			debit=True,
			remark=remark,
		)
	]
	# A free transfer (pct 0, or a commission that rounds away) still closes; it
	# just has nothing to defer, and a zero-amount row would only be noise.
	if amounts["commission_base"] > 0:
		legs.append(
			_leg(
				account=accounts["deferred_commission"],
				currency=base_currency,
				amount=amounts["commission_base"],
				base=amounts["commission_base"],
				rate=Decimal(1),
				debit=False,
				remark=remark,
			)
		)
	legs.append(
		_leg(
			account=accounts["obligation"],
			currency=receive_currency,
			amount=receiver_d,
			base=amounts["obligation_base"],
			rate=obligation_rate,
			debit=False,
			remark=remark,
		)
	)

	_assert_closes(legs, places, "register")
	return {"legs": legs, "register_base_rate": obligation_rate}


def payout_legs(
	*,
	amounts: dict,
	accounts: dict,
	receiver_amount: object,
	register_base_rate: object,
	receive_currency: str,
	base_currency: str,
	remark: str = "",
) -> dict:
	"""Obligation out, destination cash out, commission earned.

	`register_base_rate` is the rate frozen at register (ADR-008). It is used
	verbatim — never refetched — and the obligation's base value is reproduced
	from it, so the obligation closes at exactly zero in both currencies no
	matter what the market did in between.
	"""
	places = amounts["base_precision"]
	receiver_d = _d(receiver_amount, "receiver_amount")
	frozen = _d(register_base_rate, "register_base_rate")
	if frozen <= 0:
		raise AccountingError(f"register_base_rate must be positive, got {frozen}.")

	obligation_base = _quantize(receiver_d * frozen, places)
	if obligation_base != amounts["obligation_base"]:
		raise AccountingError(
			f"The frozen rate {frozen} values the obligation at {obligation_base}, but it was "
			f"opened at {amounts['obligation_base']}. Paying out would leave a residue."
		)

	legs = [
		_leg(
			account=accounts["obligation"],
			currency=receive_currency,
			amount=receiver_d,
			base=obligation_base,
			rate=frozen,
			debit=True,
			remark=remark,
		),
		_leg(
			account=accounts["destination_cash"],
			currency=receive_currency,
			amount=receiver_d,
			base=obligation_base,
			rate=frozen,
			debit=False,
			remark=remark,
		),
	]
	if amounts["commission_base"] > 0:
		legs.extend(
			[
				_leg(
					account=accounts["deferred_commission"],
					currency=base_currency,
					amount=amounts["commission_base"],
					base=amounts["commission_base"],
					rate=Decimal(1),
					debit=True,
					remark=remark,
				),
				_leg(
					account=accounts["commission_income"],
					currency=base_currency,
					amount=amounts["commission_base"],
					base=amounts["commission_base"],
					rate=Decimal(1),
					debit=False,
					remark=remark,
				),
			]
		)

	_assert_closes(legs, places, "payout")
	return {"legs": legs}


def refund_legs(
	*,
	amounts: dict,
	accounts: dict,
	tendered: object,
	receiver_amount: object,
	register_base_rate: object,
	send_currency: str,
	receive_currency: str,
	base_currency: str,
	remark: str = "",
) -> dict:
	"""Obligation and deferred commission out, the whole tendered amount back.

	The customer gets back exactly what was put on the counter — the commission
	is refunded too, because it was never earned. Same frozen rate as payout.
	"""
	places = amounts["base_precision"]
	tendered_d = _d(tendered, "tendered")
	receiver_d = _d(receiver_amount, "receiver_amount")
	frozen = _d(register_base_rate, "register_base_rate")

	obligation_base = _quantize(receiver_d * frozen, places)
	if obligation_base != amounts["obligation_base"]:
		raise AccountingError(
			f"The frozen rate {frozen} values the obligation at {obligation_base}, but it was "
			f"opened at {amounts['obligation_base']}. Refunding would leave a residue."
		)

	cash_rate = _rate_for(amounts["cash_base"], tendered_d, send_currency == base_currency, places)

	legs = [
		_leg(
			account=accounts["obligation"],
			currency=receive_currency,
			amount=receiver_d,
			base=obligation_base,
			rate=frozen,
			debit=True,
			remark=remark,
		),
		_leg(
			account=accounts["origin_cash"],
			currency=send_currency,
			amount=tendered_d,
			base=amounts["cash_base"],
			rate=cash_rate,
			debit=False,
			remark=remark,
		),
	]
	if amounts["commission_base"] > 0:
		legs.insert(
			1,
			_leg(
				account=accounts["deferred_commission"],
				currency=base_currency,
				amount=amounts["commission_base"],
				base=amounts["commission_base"],
				rate=Decimal(1),
				debit=True,
				remark=remark,
			),
		)

	_assert_closes(legs, places, "refund")
	return {"legs": legs}


def _assert_closes(legs: list, places: int, stage: str) -> None:
	"""Cross-currency entries balance in BASE only, never per currency.

	Also re-derives each base value the way ERPNext will (amount * rate), so a
	leg that would be silently revalued on validation fails here instead.
	"""
	debit = Decimal(0)
	credit = Decimal(0)
	for leg in legs:
		rate = leg["exchange_rate"]
		for side in ("debit", "credit"):
			amount = leg[f"{side}_in_account_currency"]
			stated = leg[side]
			if _quantize(amount * rate, places) != stated:
				raise AccountingError(
					f"{stage}: {leg['account']} states {stated} in base but ERPNext will post "
					f"{_quantize(amount * rate, places)} ({amount} * {rate})."
				)
		debit += leg["debit"]
		credit += leg["credit"]

	if debit != credit:
		raise AccountingError(
			f"{stage} entry does not close in base currency: debit {debit} != credit {credit}."
		)
