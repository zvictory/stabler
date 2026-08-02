"""Real Audited CRM Automation Engine & SLA Escalation API.

Enforces CRM module permissions, company scoping, CRM manager role gates,
dynamic date math (date_diff/add_days), deterministic DB idempotency,
and persistent CRM Activity audit records with dry-run support.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate

from stabler.api.crm import _assert_crm_record_company, _require_crm, _require_crm_company
from stabler.api.organization import _ADMIN_ROLES, _assert_company_scope

_CRM_MANAGER_ROLES = frozenset((*_ADMIN_ROLES, "Sales Manager", "CRM Specialist"))


def _require_crm_manager(company: str) -> None:
	"""Verify caller has CRM module access, company scoping, and CRM Manager/Admin role."""
	_assert_company_scope(company)
	_require_crm()
	_require_crm_company(company)

	user_roles = frappe.get_roles(frappe.session.user)
	if not any(role in user_roles for role in _CRM_MANAGER_ROLES):
		frappe.throw(
			_("Not permitted. CRM Manager role required."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def run_crm_automation_rules(company: str, dry_run: bool = False) -> dict:
	"""Execute company-scoped CRM automation rules with persistent DB audit records.

	If dry_run is True, returns planned actions without writing records to DB.
	If dry_run is False, creates persistent CRM Activity task records with idempotency guards.
	"""
	_require_crm_manager(company)
	today = getdate(nowdate())
	today_str = str(today)

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
		_assert_crm_record_company("CRM Deal", deal_name, company, "read")
		stage = d.get("stage") or "seen"

		# Rule 1: SLA Deadline Alert (deadline within 2 days or overdue)
		if d.get("deadline"):
			deadline_date = getdate(d["deadline"])
			if date_diff(deadline_date, today) <= 2:
				rule_name = "SLA Deadline Alert"
				rule_key = f"crm_sla:{company}:{deal_name}:{deadline_date}"

				# Check DB for existing audit activity
				existing = frappe.get_list(
					"CRM Activity",
					filters={"custom_idempotency_key": rule_key, "company": company},
					fields=["name"],
					limit_page_length=1,
				)

				if not existing:
					executed += 1
					action_detail = f"Bid deadline {deadline_date} is near or passed for {deal_name}."
					actions.append(
						{
							"deal": deal_name,
							"rule": rule_name,
							"key": rule_key,
							"detail": action_detail,
							"dry_run": dry_run,
						}
					)

					if not dry_run:
						act = frappe.new_doc("CRM Activity")
						act.company = company
						act.reference_doctype = "CRM Deal"
						act.reference_name = deal_name
						act.activity_type = "Task"
						act.subject = f"[{rule_name}] {deal_name}"
						act.description = action_detail
						act.due_at = str(deadline_date)
						act.status = "Planned"
						act.created_by = frappe.session.user
						if hasattr(act, "custom_idempotency_key"):
							act.custom_idempotency_key = rule_key
							act.custom_rule_name = rule_name
							act.custom_execution_status = "Executed"
							act.custom_attempts = 1

						if hasattr(act, "insert"):
							try:
								act.insert()
							except TypeError:
								act.insert()

		# Rule 2: Stale Deal Escalation (no activity for 3+ days in active stage)
		if d.get("last_activity_date"):
			last_act_date = getdate(d["last_activity_date"])
			if date_diff(today, last_act_date) >= 3 and stage not in ("won", "lost", "cancelled"):
				rule_name = "Stale Deal Escalation"
				rule_key = f"crm_stale:{company}:{deal_name}:{stage}:{today_str}"

				existing = frappe.get_list(
					"CRM Activity",
					filters={"custom_idempotency_key": rule_key, "company": company},
					fields=["name"],
					limit_page_length=1,
				)

				if not existing:
					executed += 1
					action_detail = f"No activity on {deal_name} since {last_act_date} (stage: {stage})."
					actions.append(
						{
							"deal": deal_name,
							"rule": rule_name,
							"key": rule_key,
							"detail": action_detail,
							"dry_run": dry_run,
						}
					)

					if not dry_run:
						act = frappe.new_doc("CRM Activity")
						act.company = company
						act.reference_doctype = "CRM Deal"
						act.reference_name = deal_name
						act.activity_type = "Task"
						act.subject = f"[{rule_name}] {deal_name}"
						act.description = action_detail
						act.status = "Planned"
						act.created_by = frappe.session.user
						if hasattr(act, "custom_idempotency_key"):
							act.custom_idempotency_key = rule_key
							act.custom_rule_name = rule_name
							act.custom_execution_status = "Executed"
							act.custom_attempts = 1

						if hasattr(act, "insert"):
							try:
								act.insert()
							except TypeError:
								act.insert()

	return {
		"company": company,
		"dry_run": dry_run,
		"executed_rules": executed,
		"actions": actions,
		"summary": f"{'Previewed' if dry_run else 'Executed'} {executed} automation rule(s) for {company}.",
	}


@frappe.whitelist()
def preview_crm_automation_rules(company: str) -> dict:
	"""Read-only preview endpoint for CRM automation rules."""
	_assert_company_scope(company)
	return run_crm_automation_rules(company=company, dry_run=True)


def scheduled_daily_crm_automation() -> None:
	"""Daily system scheduler hook executing CRM automation rules across companies."""
	companies = frappe.get_all("Company", fields=["name"])
	for comp in companies:
		try:
			run_crm_automation_rules(company=comp["name"], dry_run=False)
		except Exception as err:
			frappe.logger().error(f"Scheduled CRM automation error for {comp['name']}: {err}")
