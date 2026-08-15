"""Pure allocation, reversal and FX helpers for the Vehicle Finance engine.

One allocator serves preview, collection and supplier payment, so the UI can
never display a different allocation than the one saved — the same guarantee
the legacy ``installment.collect_payment`` gives with its shared allocator.

No frappe imports here: these functions are deterministic money maths and are
unit-tested bench-free. Callers wrap ``ValueError`` in ``frappe.throw``.
"""

from __future__ import annotations


def _r(value, precision: int) -> float:
	return round(float(value or 0), precision)


def _outstanding(row: dict, precision: int) -> float:
	return _r(_r(row.get("amount"), precision) - _r(row.get("paid"), precision), precision)


def allocate(
	rows: list[dict],
	amount: float,
	*,
	override_rows: list[str] | None = None,
	precision: int = 2,
) -> list[dict]:
	"""FIFO-allocate `amount` across open schedule rows.

	`rows` carry {row_name, sequence, due_date, amount, paid}. Row 0 (the down
	payment) has the earliest due date (the agreement date), so plain
	(due_date, sequence) ordering settles it first — a cashier can never skip
	an overdue row, and allocation continues into future rows once earlier rows
	are settled.

	`override_rows` reorders/restricts the target rows; the CALLER must have
	verified the fifo_override capability, the Settings flag and the reason.
	"""
	amount = _r(amount, precision)
	if amount <= 0:
		raise ValueError("Allocation amount must be greater than zero.")
	if not rows:
		raise ValueError("There are no schedule rows to allocate against.")

	if override_rows is not None:
		by_name = {r.get("row_name"): r for r in rows}
		ordered: list[dict] = []
		for name in override_rows:
			if name not in by_name:
				raise ValueError(f"Unknown schedule row in override: {name}.")
			ordered.append(by_name[name])
	else:
		ordered = sorted(rows, key=lambda r: (str(r.get("due_date")), int(r.get("sequence") or 0)))

	allocations: list[dict] = []
	remaining = amount
	for row in ordered:
		if remaining <= 0:
			break
		before = _outstanding(row, precision)
		if before <= 0:
			if override_rows is not None:
				raise ValueError(f"Override targets a fully settled row ({row.get('row_name')}).")
			continue
		applied = _r(min(remaining, before), precision)
		allocations.append(
			{
				"row_name": row.get("row_name"),
				"sequence": int(row.get("sequence") or 0),
				"due_date": str(row.get("due_date")),
				"outstanding_before": before,
				"allocated": applied,
				"outstanding_after": _r(before - applied, precision),
			}
		)
		remaining = _r(remaining - applied, precision)

	allocated_total = _r(sum(a["allocated"] for a in allocations), precision)
	if allocated_total != amount:
		raise ValueError(
			"Allocation totals {0} but the payment amount is {1}.".format(allocated_total, amount)
		)
	return allocations


def reversal_plan(applications: list[dict]) -> list[dict]:
	"""Order reversal Payment Applications newest-covered-first.

	Mirrors the legacy ``_reverse_allocations`` order (restore later-due rows
	first). Input: [{name, row_name, sequence, due_date, allocated_amount}].
	"""
	return sorted(
		applications,
		key=lambda a: (str(a.get("due_date")), int(a.get("sequence") or 0)),
		reverse=True,
	)


def compute_payment_fx(
	*,
	amount: float,
	party_currency: str,
	bank_currency: str,
	to_base_rates: dict[str, float],
	payment_type: str,
) -> dict:
	"""FX-safe Payment Entry amounts and rates.

	`to_base_rates` maps each currency to its multiplier against the company
	base currency (the CBU lookup the money module uses). ERPNext semantics:
	paid_amount is in the PAID-FROM account's currency, received_amount in the
	paid-to account's currency, and received = paid * source / target where
	source/target are the account currencies against base.
	"""
	amount = float(amount)
	source = float(to_base_rates.get(party_currency, 1.0) or 1.0)
	target = float(to_base_rates.get(bank_currency, 1.0) or 1.0)
	if party_currency == bank_currency:
		return {
			"needs_exchange": False,
			"paid_amount": amount,
			"received_amount": amount,
			"source_exchange_rate": 1.0,
			"target_exchange_rate": 1.0,
		}
	if not source or not target:
		raise ValueError("An exchange rate is required between the account currencies.")
	# ERPNext: source_exchange_rate is the PAID-FROM currency against base.
	# The conversion itself is symmetric: X bank = amount party * party/base
	# ÷ bank/base. Only the paid/received placement and the rate fields
	# follow the direction.
	converted = amount * source / target
	if payment_type == "Receive":
		paid, received = amount, converted
		source_rate, target_rate = source, target
	else:
		paid, received = converted, amount
		source_rate, target_rate = target, source
	return {
		"needs_exchange": True,
		"paid_amount": round(paid, 9),
		"received_amount": round(received, 9),
		"source_exchange_rate": source_rate,
		"target_exchange_rate": target_rate,
	}
