"""Pure, frappe-free helpers for the imports automation hooks.

Kept import-free of frappe so the money math and the run/skip decisions can be
unit-tested without a live bench (see stabler/tests/test_container_arrival_hook.py).
``hooks.py`` is the thin frappe-facing orchestration layer that reads/writes
documents and delegates every calculation and decision to this module.
"""

from __future__ import annotations

# Iran-arrival advance is 70% of the container's goods value (the 30% deposit
# was paid up front at PO stage). See Django signals.py:581.
ADVANCE_PCT = 0.70

# Expense-only service item for cross-border trucking Purchase Invoices. Created
# by patch v43 (and defensively by the hook). ERPNext rejects item-less PIs, so
# the transport cost is booked as a single non-stock service line.
XBORDER_ITEM_CODE = "Cross-Border Transport"

# Single expense-only service item for Import Expense Purchase Invoices (all
# non-transport categories). Created by patch v45. One shared Item keeps the
# chart simple; the expense category + description ride on the PI line so the
# detail is preserved. (Transport-category expenses are billed by the truck
# CROSSED_BORDER hook via the 3-tier lookup, not here — see resolve_transport_source.)
IMPORT_SERVICE_ITEM_CODE = "Import Service"

# Import Expense categories whose bill is owned by the truck border-crossing hook
# (tier 1/2 of the transport lookup), so the generic on_update PI must NOT create
# a duplicate for them.
_TRUCK_OWNED_CATEGORIES = ("Transport",)


def should_run_automation(in_migration: bool, imports_enabled: bool) -> bool:
	"""M6 guard: imports hooks run only outside ETL and only for imports-on companies."""
	if in_migration:
		return False
	return bool(imports_enabled)


def wants_advance_pe(old_status, new_status) -> bool:
	"""True on the transition INTO ARRIVED_AT_IRAN (not on a re-save that keeps it)."""
	return bool(new_status == "ARRIVED_AT_IRAN" and old_status != new_status)


def wants_transport_pi(old_status, new_status) -> bool:
	"""True on the transition INTO CROSSED_BORDER."""
	return bool(new_status == "CROSSED_BORDER" and old_status != new_status)


def advance_reference_no(container_name: str) -> str:
	"""Idempotency marker stored on the advance Payment Entry's reference_no."""
	return f"70PCT-{container_name}"


def transport_reference_no(truck_name: str) -> str:
	"""Idempotency marker stored on the transport Purchase Invoice's bill_no."""
	return f"XBORDER-{truck_name}"


def import_expense_reference_no(expense_name: str) -> str:
	"""Idempotency marker stored on the Import Expense Purchase Invoice's bill_no."""
	return f"IMPEXP-{expense_name}"


def expense_status(amount, bank_payment, cash_payment) -> str:
	"""Pending / Partial / Paid from bank+cash vs amount (Django CIExpense.clean)."""
	amt = round(float(amount or 0), 2)
	paid = round(float(bank_payment or 0) + float(cash_payment or 0), 2)
	if amt > 0 and paid >= amt:
		return "Paid"
	if paid > 0:
		return "Partial"
	return "Pending"


def wants_expense_pi(category, supplier, amount, purchase_invoice) -> bool:
	"""True when an Import Expense should spawn its own DRAFT service PI.

	Requires a supplier and a positive amount, and no PI yet. Transport-category
	expenses are billed by the truck CROSSED_BORDER hook (the 3-tier lookup), so
	they are deliberately excluded here to avoid a double bill.
	"""
	if category in _TRUCK_OWNED_CATEGORIES:
		return False
	if not supplier:
		return False
	if round(float(amount or 0), 2) <= 0:
		return False
	if (purchase_invoice or "").strip():
		return False
	return True


def resolve_transport_source(
	*, tier1_expense, tier2_expense, truck_transport_cost, truck_supplier, truck_currency
):
	"""Pure 3-tier cross-border transport cost source selection (Django signals.py:871).

	* tier 1 — ``tier1_expense``: an Import Expense (category Transport) explicitly
	  linked to this truck and not yet billed.
	* tier 2 — ``tier2_expense``: an unlinked Import Expense (category Transport)
	  matching the trucking company, not yet billed (to be auto-linked/consumed).
	* tier 3 — ``truck_transport_cost``: the truck's own flat transport cost.

	``tier1_expense`` / ``tier2_expense`` are ``{"name", "amount", "supplier",
	"currency"}`` dicts or ``None``. Returns ``{"amount", "supplier", "currency",
	"consume_expense"}`` (``consume_expense`` = the Import Expense name to stamp
	with the created PI, or ``None`` for tier 3) or ``None`` when no source has a
	positive cost.
	"""
	for exp in (tier1_expense, tier2_expense):
		if exp and round(float(exp.get("amount") or 0), 2) > 0:
			return {
				"amount": round(float(exp["amount"]), 2),
				"supplier": exp.get("supplier") or truck_supplier,
				"currency": exp.get("currency") or truck_currency or "USD",
				"consume_expense": exp.get("name"),
			}
	if truck_transport_cost and round(float(truck_transport_cost), 2) > 0:
		return {
			"amount": round(float(truck_transport_cost), 2),
			"supplier": truck_supplier,
			"currency": truck_currency or "USD",
			"consume_expense": None,
		}
	return None


def build_import_expense_pi_payload(
	*, company, supplier, currency, amount, category, description, expense_name,
	commercial_invoice=None, container=None, truck=None,
	item_code=IMPORT_SERVICE_ITEM_CODE
):
	"""Build the DRAFT service Purchase Invoice dict for a non-transport Import Expense.

	One non-stock service line (ERPNext rejects item-less PIs); the category and
	description ride on the line so the detail survives. Returns ``None`` when the
	amount is 0/empty. ``docstatus`` is never set — the PI stays a draft. The
	``custom_*`` vendor-traceability links (WP7, patch v46) back-reference the CI /
	container / truck / expense; unknown keys are harmless if the fields are absent.
	"""
	amt = round(float(amount or 0), 2)
	if amt <= 0:
		return None
	line_desc = f"{category}: {description}" if description else category
	return {
		"doctype": "Purchase Invoice",
		"company": company,
		"supplier": supplier,
		"currency": currency or "USD",
		"bill_no": import_expense_reference_no(expense_name),
		"remarks": f"Import expense {expense_name} ({category})",
		"custom_commercial_invoice": commercial_invoice,
		"custom_import_container": container,
		"custom_import_truck": truck,
		"custom_import_expense": expense_name,
		"items": [
			{
				"item_code": item_code,
				"qty": 1,
				"rate": amt,
				"amount": amt,
				"description": line_desc,
			}
		],
	}


def allocate_amount(total, weights) -> list[float]:
	"""Split ``total`` across rows in proportion to ``weights``.

	Returns a list the same length as ``weights`` summing exactly to ``total``
	(the last row absorbs rounding). Falls back to an equal split when all
	weights are zero/empty. Empty input returns ``[]``.
	"""
	n = len(weights)
	if n == 0:
		return []
	total = round(float(total), 2)
	wsum = float(sum(float(w) for w in weights))
	if wsum <= 0:
		share = round(total / n, 2)
		out = [share] * (n - 1)
		out.append(round(total - share * (n - 1), 2))
		return out
	out: list[float] = []
	running = 0.0
	for w in weights[:-1]:
		amt = round(total * float(w) / wsum, 2)
		out.append(amt)
		running += amt
	out.append(round(total - running, 2))
	return out


def build_advance_pe_payload(
	*, company, supplier, currency, total_amount, po_rows, container_name
) -> dict:
	"""Build the DRAFT Payment Entry dict for the 70% advance on Iran arrival.

	``po_rows`` is a list of ``{"purchase_order": name, "grand_total": number}``.
	70% of ``total_amount`` is allocated across the POs in proportion to
	``grand_total``; when ``po_rows`` is empty the PE carries no references (the
	caller logs a warning). ``docstatus`` is never set — the PE stays a draft.
	"""
	paid_amount = round(float(total_amount) * ADVANCE_PCT, 2)
	references = []
	if po_rows:
		weights = [float(r.get("grand_total") or 0) for r in po_rows]
		amounts = allocate_amount(paid_amount, weights)
		for r, amt in zip(po_rows, amounts, strict=True):
			references.append(
				{
					"reference_doctype": "Purchase Order",
					"reference_name": r["purchase_order"],
					"allocated_amount": amt,
				}
			)
	return {
		"doctype": "Payment Entry",
		"payment_type": "Pay",
		"company": company,
		"party_type": "Supplier",
		"party": supplier,
		"paid_amount": paid_amount,
		"received_amount": paid_amount,
		"paid_from_account_currency": currency,
		"paid_to_account_currency": currency,
		"reference_no": advance_reference_no(container_name),
		"custom_import_container": container_name,
		"references": references,
		"remarks": f"70% advance on Iran arrival for container {container_name}",
	}


def build_transport_pi_payload(
	*, company, supplier, currency, transport_cost, truck_name,
	commercial_invoice=None, import_expense=None, item_code=XBORDER_ITEM_CODE
):
	"""Build the DRAFT service Purchase Invoice dict for cross-border transport.

	One non-stock service line (ERPNext rejects item-less PIs). Returns ``None``
	when ``transport_cost`` is 0/empty so the caller can skip. ``docstatus`` is
	never set — the PI stays a draft. The ``custom_*`` vendor-traceability links
	(WP7, patch v46) back-reference the truck, its CI and — for tier 1/2 — the
	consumed Import Expense; unknown keys are harmless if the fields are absent.
	"""
	amount = round(float(transport_cost or 0), 2)
	if amount <= 0:
		return None
	return {
		"doctype": "Purchase Invoice",
		"company": company,
		"supplier": supplier,
		"currency": currency,
		"bill_no": transport_reference_no(truck_name),
		"remarks": f"Cross-border transport for truck {truck_name}",
		"custom_commercial_invoice": commercial_invoice,
		"custom_import_container": None,
		"custom_import_truck": truck_name,
		"custom_import_expense": import_expense,
		"items": [
			{
				"item_code": item_code,
				"qty": 1,
				"rate": amount,
				"amount": amount,
			}
		],
	}
