"""Pure, frappe-free Landed Cost Voucher aggregation (critique M8 + audit §3).

Builds the LCV taxes rows from the Container Cost Lines of a GRN's Commercial
Invoice. The frappe-facing wiring (fetch cost lines, resolve the FX rate for the
GRN completion date, resolve the expense account from Stabler Settings, insert
the DRAFT LCV) lives in ``imports_module/hooks.py``; the aggregation, currency
conversion and exclusion rules live here so they can be unit-tested.

Correctness decisions carried over from the 2026-07-03 GRN gap analysis, fixing
the known bugs in the Django ``create_landed_cost_for_grn`` that must NOT be
replicated:

* **Customs Clearance Fee — full amount, never divided per container.** Cost
  lines are summed as-is; there is no per-container division.
* **No VAT capitalization.** Any component whose name contains "VAT" is
  excluded (import VAT is a recoverable input credit — IAS 2 forbids
  capitalizing it into inventory).
* **No product / CIF freight double-capitalization.** Goods value and the CIF
  freight already embedded in the supplier PI are not cost components by design
  (the Container Cost Line doctype has no such component).
* Distribution is by **Qty** (per-kg), not Amount — frozen-meat landed costs are
  weight-driven and every item is in Kg.
* Expense account is a single configurable account (Stabler Settings), never the
  hardcoded "Stock Adjustment - MSA".
"""

from __future__ import annotations


def is_vat_component(component) -> bool:
	"""True for any VAT component (excluded from the landed-cost build)."""
	return "vat" in str(component or "").lower()


def is_uzbekistan_customs_duty(component) -> bool:
	"""True for the Uzbekistan import-duty cost component (superseded by a GTD).

	Only the Uzbek duty is replaced by a cleared customs declaration — Iran-side
	duty stays a real landed cost, so it is deliberately not matched here.
	"""
	c = str(component or "").lower()
	return "uzbek" in c and "customs duty" in c


def apply_gtd_customs_precedence(components, gtd_duty, gtd_excise, gtd_present) -> tuple[dict, list[str]]:
	"""Let a cleared customs declaration (GTD) supersede cost-line Uzbek duty.

	When an Approved + cleared GTD exists for the CI, its ``duty_amount`` and
	``excise_amount`` (already in UZS = company currency) REPLACE any
	"Uzbekistan Customs Duty" component aggregated from the Container Cost Lines,
	so the two sources are never double-counted. VAT is never added from either
	source (recoverable input credit — see ``aggregate_components``).

	Returns ``(new_components, warnings)``. A warning is emitted when BOTH a
	cost-line Uzbek duty AND a cleared GTD were present (the GTD won; the operator
	should confirm the cost line was not meant as a separate charge).
	"""
	warnings: list[str] = []
	if not gtd_present:
		return dict(components), warnings

	out: dict[str, float] = {}
	had_cost_line_duty = False
	for comp, amt in components.items():
		if is_uzbekistan_customs_duty(comp):
			had_cost_line_duty = True
			continue  # superseded by the GTD
		out[comp] = amt

	duty = round(float(gtd_duty or 0), 2)
	excise = round(float(gtd_excise or 0), 2)
	if duty > 0:
		out["Uzbekistan Customs Duty"] = round(out.get("Uzbekistan Customs Duty", 0.0) + duty, 2)
	if excise > 0:
		out["Uzbekistan Excise"] = round(out.get("Uzbekistan Excise", 0.0) + excise, 2)

	if had_cost_line_duty:
		warnings.append(
			"Both a Uzbekistan Customs Duty cost line and a cleared customs declaration "
			"were present; the declaration's duty/excise took precedence and the cost-line "
			"duty was dropped to avoid double counting."
		)
	return out, warnings


def line_company_amount(currency, amount, usd_rate, company_currency) -> float:
	"""Amount of one cost line in company currency.

	Lines already in the company currency pass through untouched; everything else
	(USD) is converted with ``usd_rate`` (the rate for the GRN completion date,
	fetched frappe-side and passed in as an argument).
	"""
	amt = float(amount or 0)
	if (currency or company_currency) == company_currency:
		return round(amt, 2)
	return round(amt * float(usd_rate or 0), 2)


def unconsumed(cost_lines) -> list[dict]:
	"""Cost lines eligible for a (new) LCV: included and not yet vouchered.

	Enables the multi-LCV / late-cost flow — a line consumed by an earlier LCV
	carries a non-empty ``lcv_ref`` and is skipped so an additional LCV only
	picks up the delta.
	"""
	out = []
	for ln in cost_lines:
		if not ln.get("include_in_landed_cost"):
			continue
		if (ln.get("lcv_ref") or "").strip():
			continue
		out.append(ln)
	return out


def aggregate_components(cost_lines, usd_rate, company_currency) -> dict:
	"""Aggregate eligible cost lines into ``{component: company_amount}`` (>0).

	Excludes VAT components; sums full amounts (no clearance-fee division).
	"""
	agg: dict[str, float] = {}
	for ln in unconsumed(cost_lines):
		comp = ln.get("cost_component") or "Other"
		if is_vat_component(comp):
			continue
		amt = line_company_amount(ln.get("currency"), ln.get("amount"), usd_rate, company_currency)
		if amt == 0:
			continue
		agg[comp] = round(agg.get(comp, 0.0) + amt, 2)
	return {k: v for k, v in agg.items() if v > 0}


def build_lcv_payload(*, company, purchase_receipts, components, expense_account, distribute_based_on="Qty"):
	"""Build the DRAFT Landed Cost Voucher dict.

	``purchase_receipts`` is a list of submitted PR names; ``components`` is the
	``{component: amount}`` map from ``aggregate_components``. Returns ``None``
	when there is nothing to voucher (no PRs or no costs). ``docstatus`` is never
	set — the accountant reviews and submits (valuation repost caution).
	"""
	if not purchase_receipts or not components:
		return None
	return {
		"doctype": "Landed Cost Voucher",
		"company": company,
		"distribute_charges_based_on": distribute_based_on,
		"purchase_receipts": [
			{"receipt_document_type": "Purchase Receipt", "receipt_document": pr} for pr in purchase_receipts
		],
		"taxes": [
			{"expense_account": expense_account, "description": comp, "amount": amt}
			for comp, amt in components.items()
		],
	}
