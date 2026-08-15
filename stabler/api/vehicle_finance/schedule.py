"""Deterministic schedule builder — the single source of schedule truth.

``build_schedule`` is a pure function used by BOTH the preview endpoint and the
persisting path, so a preview can never differ from what is saved. It raises
``ValueError`` on every rejected input; callers wrap it in ``frappe.throw``.

Row 0 is the down payment (or the complete cash-settlement row) and is part of
the schedule total. The final row absorbs the currency-precision rounding
residual — never any other row. Precision comes from Currency/company metadata
via the ``currency_precision`` argument, never a hardcoded 2.
"""

from __future__ import annotations

from frappe.utils import add_months, flt, getdate

ROW_0_TYPES = ("Down Payment", "Cash Settlement")


def build_schedule(
	*,
	total: float,
	down_payment: float,
	currency_precision: int,
	plan_type: str,
	agreement_date: str,
	first_installment_date: str | None = None,
	installment_count: int | None = None,
	balloon_amount: float = 0,
	custom_rows: list[dict] | None = None,
	settlement_mode: str = "Installment",
) -> list[dict]:
	"""Return the validated schedule rows as plain dicts.

	Equal Monthly generates rows 1..n at ``add_months(first_installment_date,
	i - 1)`` plus an optional balloon final row; Custom validates caller-supplied
	rows instead of generating them.
	"""
	total = flt(total)
	down_payment = flt(down_payment)
	balloon_amount = flt(balloon_amount)
	precision = int(currency_precision)

	if total <= 0:
		raise ValueError("Agreement total must be greater than zero.")
	if down_payment < 0 or down_payment > total:
		raise ValueError("Down payment must be between zero and the total contract price.")
	if balloon_amount < 0:
		raise ValueError("Balloon amount cannot be negative.")

	agreement_dt = getdate(agreement_date)

	if settlement_mode == "Cash":
		return _build_cash_row(total, agreement_dt)

	if custom_rows is not None:
		return _validate_custom_rows(custom_rows, total, agreement_dt, precision)

	if plan_type != "Equal Monthly":
		raise ValueError("Unknown plan type: {0}.".format(plan_type))
	if not installment_count or int(installment_count) < 1:
		raise ValueError("Installment count must be at least 1 for an installment plan.")
	if not first_installment_date:
		raise ValueError("First installment date is required for an installment plan.")

	financed = total - down_payment - balloon_amount
	if financed < 0:
		raise ValueError("Financed amount cannot be negative.")

	rows = [_row(0, agreement_dt, down_payment, "Down Payment")]
	first_dt = getdate(first_installment_date)
	if first_dt < agreement_dt:
		raise ValueError("A due date cannot be before the agreement date.")
	per_installment = flt(financed / int(installment_count), precision)
	for i in range(1, int(installment_count) + 1):
		rows.append(
			_row(i, add_months(first_dt, i - 1), per_installment, "Installment")
		)
	if balloon_amount > 0:
		rows.append(
			_row(
				int(installment_count) + 1,
				add_months(first_dt, int(installment_count)),
				flt(balloon_amount, precision),
				"Balloon",
			)
		)
	rows[-1]["amount"] = flt(rows[-1]["amount"] + (total - flt(sum(r["amount"] for r in rows))), precision)
	return _post_validate(rows, total, agreement_dt, precision)


def _build_cash_row(total: float, agreement_dt) -> list[dict]:
	if total <= 0:
		raise ValueError("Agreement total must be greater than zero.")
	return [_row(0, agreement_dt, total, "Cash Settlement")]


def _validate_custom_rows(
	custom_rows: list[dict], total: float, agreement_dt, precision: int
) -> list[dict]:
	if not custom_rows:
		raise ValueError("A custom schedule needs at least one row.")
	rows = []
	previous_due = None
	for index, row in enumerate(custom_rows):
		amount = flt(row.get("amount"))
		if amount < 0:
			raise ValueError("Schedule row amounts cannot be negative.")
		due = getdate(row.get("due_date"))
		if due < agreement_dt:
			raise ValueError("A due date cannot be before the agreement date.")
		if previous_due is not None and due <= previous_due:
			raise ValueError("Schedule due dates must be strictly increasing.")
		previous_due = due
		sequence = int(row.get("sequence", index))
		if sequence != 0 and amount <= 0:
			raise ValueError("Schedule row amounts must be greater than zero.")
		rows.append(
			{
				"sequence": sequence,
				"due_date": due,
				"amount": amount,
				"row_type": row.get("row_type") or "Installment",
				"note": row.get("note") or "",
			}
		)
	if rows[0]["sequence"] != 0 or rows[0]["row_type"] not in ROW_0_TYPES:
		raise ValueError("Row 0 must be the down payment row, due on the agreement date.")
	if rows[0]["due_date"] != agreement_dt:
		raise ValueError("Row 0 must be due on the agreement date.")
	row_sum = flt(sum(r["amount"] for r in rows))
	if round(row_sum, precision) != round(total, precision):
		raise ValueError(
			"Schedule rows sum to {0} but the agreement total is {1}.".format(
				round(row_sum, precision), round(total, precision)
			)
		)
	return rows


def _post_validate(rows: list[dict], total: float, agreement_dt, precision: int) -> list[dict]:
	row_sum = flt(sum(r["amount"] for r in rows))
	if round(row_sum, precision) != round(total, precision):
		raise ValueError(
			"Schedule rows sum to {0} but the agreement total is {1}.".format(
				round(row_sum, precision), round(total, precision)
			)
		)
	previous_due = None
	for row in rows:
		if previous_due is not None and row["due_date"] <= previous_due:
			raise ValueError("Schedule due dates must be strictly increasing.")
		previous_due = row["due_date"]
	return rows


def _row(sequence: int, due_date, amount, row_type: str) -> dict:
	return {
		"sequence": sequence,
		"due_date": due_date,
		"amount": flt(amount),
		"row_type": row_type,
		"note": "",
	}
