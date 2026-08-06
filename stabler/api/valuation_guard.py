"""Valuation poisoning shields (COGS defence).

Stock valuation was poisoned twice, through two different doors:

  * A vendor bill row carried the *amount* in the *rate* field: item R099 on
    ACC-PINV-2026-01802-1 was billed at base_rate 20 000 USD while sibling rows
    of the same item on the same document sat at 1.65 USD — a 12 121x error.
    Submitted with update_stock=1 it went straight into the stock ledger and
    from there into five downstream production entries.
  * A sales return row carried `incoming_rate` in *transaction* currency:
    ACC-SINV-2026-01514 item S187 had incoming_rate 1300 (the UZS price) where
    the field is defined in *company* currency (0.11 USD). The multiple was the
    document's own exchange rate. It built a FIFO layer at 1300 USD/unit.
    ACC-SINV-2026-01420 — same day, same item, same 1300 / 0.11 — was never
    poisoned because its incoming_rate was 0.

Both ran for weeks unnoticed, so `stabler.tasks.repost_queue_alert` watches the
outcome as well.

Opt-in per company via `enable_valuation_guard` on Stabler Company Modules
(OFF by default), so a tenant that does not want these checks is unaffected.
Every threshold is a Stabler Settings field, never a constant here.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

_GATE_FIELD = "enable_valuation_guard"


def guard_enabled(company: str | None) -> bool:
	"""True when this company opted into the valuation guards.

	Reads the child row directly instead of going through `module_map_for()`:
	that helper *creates and commits* a missing row, which is not acceptable
	inside a validate hook that fires on every save across all tenants. Any
	failure (pre-migrate site, missing column) resolves to OFF — the guards
	must never be the reason a save breaks.
	"""
	if not company:
		return False
	try:
		val = frappe.db.get_value(
			"Stabler Company Modules",
			{"parent": "Stabler Settings", "parenttype": "Stabler Settings", "company": company},
			_GATE_FIELD,
		)
	except Exception:
		return False
	return bool(int(val or 0))


def _setting(fieldname: str, default: float) -> float:
	"""Numeric Stabler Settings value, falling back to `default` when unset."""
	try:
		val = frappe.db.get_single_value("Stabler Settings", fieldname)
	except Exception:
		return default
	val = flt(val)
	return val if val > 0 else default


# ----- Shield 1: vendor bill rate sanity -------------------------------------


def _min_rate_per_item(doc) -> dict:
	"""Lowest positive base_rate per item_code inside this document.

	This is the intra-document evidence: when the same item appears at 1.65 and
	at 20 000 on one bill, no purchase history is needed to know which one is
	the typo.
	"""
	mins: dict = {}
	for row in doc.get("items") or []:
		rate = flt(getattr(row, "base_rate", 0))
		item_code = getattr(row, "item_code", None)
		if not item_code or rate <= 0:
			continue
		if item_code not in mins or rate < mins[item_code]:
			mins[item_code] = rate
	return mins


def _trailing_avg_base_rate(doc, item_code: str, lookback_days: int):
	"""Average submitted purchase base_rate for this item over the window.

	Returns None when there is no history at all — a first purchase must never
	be blocked, there is nothing to compare it against.
	"""
	posting_date = getdate(getattr(doc, "posting_date", None) or today())
	rows = frappe.db.sql(
		"""
		select pii.base_rate
		from `tabPurchase Invoice Item` pii
		inner join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus = 1
		  and pi.company = %(company)s
		  and pi.posting_date >= %(from_date)s
		  and pi.posting_date <= %(to_date)s
		  and pi.name != %(name)s
		  and pii.item_code = %(item_code)s
		  and pii.base_rate > 0
		""",
		{
			"company": getattr(doc, "company", None),
			"from_date": add_days(posting_date, -abs(int(lookback_days))),
			"to_date": posting_date,
			"name": getattr(doc, "name", None) or "",
			"item_code": item_code,
		},
	)
	rates = [flt(r[0]) for r in rows if flt(r[0]) > 0]
	if not rates:
		return None
	return sum(rates) / len(rates)


def check_purchase_invoice_rates(doc, method=None) -> None:
	"""Shield 1 — block a vendor bill whose rate looks like a mistyped amount."""
	if not guard_enabled(getattr(doc, "company", None)):
		return

	multiple = _setting("valuation_guard_purchase_rate_multiple", 50.0)
	if multiple <= 1:
		return
	lookback_days = int(_setting("valuation_guard_lookback_days", 90.0))

	siblings = _min_rate_per_item(doc)
	offences = []
	for idx, row in enumerate(doc.get("items") or [], start=1):
		rate = flt(getattr(row, "base_rate", 0))
		item_code = getattr(row, "item_code", None)
		if not item_code or rate <= 0:
			continue

		sibling = flt(siblings.get(item_code))
		if sibling > 0 and rate > sibling * multiple:
			offences.append(
				_(
					"Row {0} ({1}): rate {2} is {3}x the rate {4} used for the same item elsewhere on this document."
				).format(idx, item_code, rate, round(rate / sibling), sibling)
			)
			continue

		avg = _trailing_avg_base_rate(doc, item_code, lookback_days)
		if avg is None or avg <= 0:
			# First purchase of this item — no baseline, stay silent.
			continue
		if rate > avg * multiple:
			offences.append(
				_("Row {0} ({1}): rate {2} is {3}x the {4}-day average purchase rate {5}.").format(
					idx, item_code, rate, round(rate / avg), lookback_days, round(avg, 4)
				)
			)

	if offences:
		frappe.throw(
			"<br>".join(offences)
			+ "<br><br>"
			+ _("Check whether the line amount was entered into the rate field."),
			title=_("Valuation Guard"),
		)


# ----- Shield 2: incoming_rate unit sanity -----------------------------------


def check_incoming_rate_currency(doc, method=None) -> None:
	"""Shield 2 — `incoming_rate` is a COMPANY-currency field.

	Writing the transaction-currency price there mints a FIFO layer at the
	exchange rate's worth of value per unit. Applies to Sales Invoice and
	Delivery Note; Stock Entry Detail has no `incoming_rate` field, its
	valuation door is Shield 3.
	"""
	if not guard_enabled(getattr(doc, "company", None)):
		return

	multiple = _setting("valuation_guard_incoming_rate_multiple", 100.0)
	if multiple <= 1:
		return
	conversion_rate = flt(getattr(doc, "conversion_rate", 0))

	offences = []
	for idx, row in enumerate(doc.get("items") or [], start=1):
		incoming = flt(getattr(row, "incoming_rate", 0))
		base = flt(getattr(row, "base_rate", 0))
		if incoming <= 0 or base <= 0:
			continue
		ratio = incoming / base
		if ratio <= multiple:
			continue

		item_code = getattr(row, "item_code", None)
		# A ratio that IS the exchange rate is not a suspicion, it is a diagnosis.
		if conversion_rate > 1 and abs(ratio - conversion_rate) <= conversion_rate * 0.1:
			offences.append(
				_(
					"Row {0} ({1}): incoming rate {2} is {3}x the company-currency rate {4}, which is this document's exchange rate — the transaction-currency price was entered into a company-currency field. Enter {4}."
				).format(idx, item_code, incoming, round(ratio), base)
			)
		else:
			offences.append(
				_(
					"Row {0} ({1}): incoming rate {2} is {3}x the company-currency rate {4}. Incoming rate must be in company currency."
				).format(idx, item_code, incoming, round(ratio), base)
			)

	if offences:
		frappe.throw("<br>".join(offences), title=_("Valuation Guard"))


# ----- Shield 3: stock entry valuation sanity --------------------------------


def _bin_valuation_rate(item_code: str, warehouse: str) -> float:
	"""What this warehouse says the item is currently worth (0 = never valued)."""
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
	)


def assert_stock_entry_valuation_sane(se) -> None:
	"""Shield 3 — refuse a Stock Entry valued far above what the bin holds.

	This is the cut that would have stopped the vendor-bill poison propagating
	through the production chain. Deliberately does NOT touch
	`allow_zero_valuation_rate`: a bin worth 0 is the legitimate first-run case
	(see tests/test_manufacturing_kiosk.py) and is skipped here, not blocked.
	"""
	if not guard_enabled(getattr(se, "company", None)):
		return

	multiple = _setting("valuation_guard_mfg_valuation_multiple", 50.0)
	if multiple <= 1:
		return

	for idx, row in enumerate(se.get("items") or [], start=1):
		item_code = getattr(row, "item_code", None)
		warehouse = getattr(row, "s_warehouse", None) or getattr(row, "t_warehouse", None)
		if not (item_code and warehouse):
			continue
		rate = flt(getattr(row, "valuation_rate", 0)) or flt(getattr(row, "basic_rate", 0))
		if rate <= 0:
			continue
		bin_rate = _bin_valuation_rate(item_code, warehouse)
		if bin_rate <= 0:
			# Never valued yet — the allow_zero_valuation_rate case. Not our call.
			continue
		if rate > bin_rate * multiple:
			frappe.throw(
				_(
					"Row {0} ({1}): valuation rate {2} is {3}x the stock valuation {4} in {5}. Posting this would poison the cost of every item produced from it."
				).format(idx, item_code, rate, round(rate / bin_rate), bin_rate, warehouse),
				title=_("Valuation Guard"),
			)
