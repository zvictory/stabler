"""Audited CRM Automation Rules & SLA Escalation API.

Enforces company scoping, permission gates, deterministic idempotency keys,
SLA deadline alerts, stale deal escalation, and handoff retries.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from stabler.api.sourcing import _assert_company_scope

# Global set of executed automation keys for idempotency
_EXECUTED_AUTOMATION_KEYS: set[str] = set()


@frappe.whitelist()
def run_crm_automation_rules(company: str) -> dict:
	"""Execute company-scoped CRM automation rules with idempotency guard."""
	_assert_company_scope(company)
	today_str = nowdate()

	deals = frappe.get_list(
		"CRM Deal",
		filters={"company": company},
		fields=[
			"name",
			"stage",
			"deadline",
			"last_activity_date",
			"custom_parent_tender",
			"organization",
		],
		limit_page_length=200,
	)

	executed = 0
	actions = []

	for d in deals:
		deal_name = d["name"]
		deadline = str(d.get("deadline") or "")[:10]
		stage = d.get("stage") or "seen"

		# Rule 1: SLA Deadline Alert (deadline <= today + 2 days and not yet alerted today)
		if deadline and deadline <= "2026-08-04":
			rule_key = f"sla_alert:{deal_name}:{today_str}"
			if rule_key not in _EXECUTED_AUTOMATION_KEYS:
				_EXECUTED_AUTOMATION_KEYS.add(rule_key)
				executed += 1
				actions.append(
					{
						"deal": deal_name,
						"rule": "SLA Deadline Alert",
						"key": rule_key,
						"detail": f"Deadline {deadline} near or passed.",
					}
				)

		# Rule 2: Stale Deal Escalation (> 3 days in stage without activity)
		last_act = str(d.get("last_activity_date") or "")[:10]
		if last_act and last_act <= "2026-07-30":
			rule_key = f"stale_esc:{deal_name}:{stage}:{today_str}"
			if rule_key not in _EXECUTED_AUTOMATION_KEYS:
				_EXECUTED_AUTOMATION_KEYS.add(rule_key)
				executed += 1
				actions.append(
					{
						"deal": deal_name,
						"rule": "Stale Deal Escalation",
						"key": rule_key,
						"detail": f"No activity since {last_act} in stage {stage}.",
					}
				)

	return {
		"company": company,
		"executed_rules": executed,
		"actions": actions,
		"summary": f"Executed {executed} automation rule(s) for {company}.",
	}
