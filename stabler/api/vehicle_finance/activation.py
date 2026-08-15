"""Activation gates and document plan — pure, shared by preview and activate.

Every account/item/tax template comes from Vehicle Finance Settings; "the
first leaf account" (the legacy anti-pattern) is never selected. A failing
gate names the missing/misconfigured field.
"""

from __future__ import annotations

SETTINGS_FIELDS_BY_DIRECTION: dict[str, list[str]] = {
	"Disposition": [
		"disposition_receivable_account",
		"disposition_deferred_income_account",
		"disposition_income_account",
		"disposition_fee_item",
	],
	"Acquisition": [
		"acquisition_payable_account",
		"acquisition_deferred_cost_account",
		"acquisition_realised_cost_account",
		"acquisition_fee_item",
	],
}

DOCUMENTS_BY_DIRECTION: dict[str, list[dict]] = {
	"Disposition": [
		{"doctype": "Delivery Note", "purpose": "Stock truth — consumes the Serial No"},
		{"doctype": "Sales Invoice", "purpose": "Receivable: vehicle line, deferred markup line, fee line"},
	],
	"Acquisition": [
		{"doctype": "Purchase Receipt", "purpose": "Stock truth — receives the Serial No"},
		{"doctype": "Purchase Invoice", "purpose": "Payable: vehicle line, deferred markup line, fee line"},
	],
}


def check_activation_gates(
	agreement: dict,
	settings: dict,
	*,
	configured_records: dict[str, dict] | None = None,
	schedule_rows_total: float | None = None,
	precision: int = 2,
) -> list[dict]:
	"""Return the five activation checks with pass/fail and a field-naming
	message. `configured_records` maps settings field → {"company": ...} for
	the ownership check; `schedule_rows_total` is the active version's row sum.
	"""
	checks: list[dict] = []

	policy_ok = bool(settings.get("accounting_policy_approved"))
	checks.append(
		{
			"name": "accounting_policy_approved",
			"passed": policy_ok,
			"message": ""
			if policy_ok
			else "Vehicle Finance Settings.accounting_policy_approved is not set for this company.",
		}
	)

	missing = [
		field
		for field in SETTINGS_FIELDS_BY_DIRECTION.get(agreement.get("direction"), [])
		if not settings.get(field)
	]
	checks.append(
		{
			"name": "required_configuration",
			"passed": not missing,
			"message": ""
			if not missing
			else "Vehicle Finance Settings is missing: " + ", ".join(missing) + ".",
		}
	)

	foreign: list[str] = []
	if configured_records:
		for field, record in configured_records.items():
			if record and record.get("company") and record["company"] != agreement.get("company"):
				foreign.append(field)
	checks.append(
		{
			"name": "records_belong_to_company",
			"passed": not foreign,
			"message": ""
			if not foreign
			else "Configured records belong to another company: " + ", ".join(foreign) + ".",
		}
	)

	invariant_messages: list[str] = []
	total = round(float(agreement.get("total_contract_price") or 0), precision)
	component_sum = round(
		float(agreement.get("cash_price") or 0)
		+ float(agreement.get("disclosed_markup") or 0)
		+ float(agreement.get("approved_fees") or 0)
		+ float(agreement.get("tax_amount") or 0),
		precision,
	)
	if total <= 0:
		invariant_messages.append("total_contract_price must be greater than zero.")
	if component_sum != total:
		invariant_messages.append(
			"Contract components sum to {0} but total_contract_price is {1}.".format(component_sum, total)
		)
	if round(float(agreement.get("down_payment") or 0), precision) > total:
		invariant_messages.append("Down payment exceeds the total contract price.")
	if round(float(agreement.get("financed_amount") or 0), precision) < 0:
		invariant_messages.append("Financed amount is negative.")
	if schedule_rows_total is not None and round(float(schedule_rows_total), precision) != total:
		invariant_messages.append(
			"Active schedule rows sum to {0} but the agreement total is {1}.".format(
				round(float(schedule_rows_total), precision), total
			)
		)
	if not agreement.get("vehicle_unit"):
		invariant_messages.append("Vehicle Unit is required.")
	checks.append(
		{
			"name": "agreement_invariants",
			"passed": not invariant_messages,
			"message": " ".join(invariant_messages),
		}
	)

	return checks


def planned_documents(agreement: dict) -> list[dict]:
	"""The document set activation would create — used by the preview screen."""
	plan = DOCUMENTS_BY_DIRECTION.get(agreement.get("direction"), [])
	if agreement.get("settlement_mode") == "Cash":
		return [dict(d, purpose=d["purpose"] + " (single cash-settlement payment schedule)") for d in plan]
	return list(plan)
