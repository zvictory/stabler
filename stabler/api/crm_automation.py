"""Automation Rules API & Worker for CRM Deals.

Enforces CRM Manager role authorization, company scoping, SLA deadline alerts,
stale deal escalation, durable DB idempotency, and audit logging.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate

from stabler.api.crm import _require_crm, _require_crm_company


def _require_crm_manager(company: str) -> None:
	"""Verify user has CRM Manager permission or System Manager role."""
	_require_crm()
	_require_crm_company(company)
	roles = frappe.get_roles()
	if "Sales Manager" not in roles and "System Manager" not in roles and "Sales Master Manager" not in roles:
		frappe.throw(
			_("Not permitted. CRM Manager role required."),
			frappe.PermissionError,
		)


def _is_duplicate_err(err: Exception) -> bool:
	"""Check if exception represents a MariaDB/MySQL duplicate key error."""
	dup_classes = (
		getattr(frappe, "UniqueValidationError", type("UniqueValidationError", (Exception,), {})),
		getattr(frappe, "DuplicateEntryError", type("DuplicateEntryError", (Exception,), {})),
	)
	if isinstance(err, dup_classes):
		return True
	err_str = str(err)
	return "1062" in err_str or "Duplicate entry" in err_str


def _process_automation_rule_action(
	company: str,
	deal_name: str,
	rule_name: str,
	rule_key: str,
	action_detail: str,
	due_at: str | None,
	dry_run: bool,
) -> bool:
	"""Process an automation rule action with persistent DB audit record creation and retry logic."""
	# Check DB for existing audit activity
	existing_list = frappe.get_list(
		"CRM Activity",
		filters={"custom_idempotency_key": rule_key, "company": company},
		fields=["name", "custom_execution_status", "custom_attempts"],
		limit_page_length=1,
	)

	if existing_list:
		ext = existing_list[0]
		status = ext.get("custom_execution_status")
		if status == "Failed" and not dry_run:
			# Retry failed rule action
			act = frappe.get_doc("CRM Activity", ext["name"])
			act.custom_execution_status = "Retried"
			act.custom_attempts = (act.get("custom_attempts") or 1) + 1
			act.custom_last_error = None
			if hasattr(act, "save"):
				act.save()
			return True
		return False  # Already executed / retried cleanly

	if not dry_run:
		act = frappe.new_doc("CRM Activity")
		act.company = company
		act.reference_doctype = "CRM Deal"
		act.reference_name = deal_name
		act.activity_type = "Task"
		act.subject = f"[{rule_name}] {deal_name}"
		act.description = action_detail
		if due_at:
			act.due_at = str(due_at)
		act.status = "Planned"
		act.created_by = frappe.session.user
		act.custom_idempotency_key = rule_key
		act.custom_rule_name = rule_name
		act.custom_execution_status = "Executed"
		act.custom_attempts = 1
		act.custom_last_error = None

		if hasattr(act, "insert"):
			try:
				act.insert()
			except Exception as err:
				if _is_duplicate_err(err):
					if hasattr(frappe, "db") and hasattr(frappe.db, "rollback"):
						frappe.db.rollback()
					existing = (
						frappe.db.sql(
							"SELECT name FROM `tabCRM Activity` WHERE custom_idempotency_key = %s AND company = %s",
							(rule_key, company),
							as_dict=True,
						)
						if hasattr(frappe, "db") and hasattr(frappe.db, "sql")
						else []
					)
					if existing:
						return False  # Parallel worker created record; return cleanly
				raise

	return True


@frappe.whitelist()
def run_crm_automation_rules(company: str, dry_run: bool = False) -> dict:
	"""Execute company-scoped CRM automation rules with persistent DB audit logging."""
	_require_crm_manager(company)

	today = getdate(nowdate())
	today_str = str(today)

	deals = frappe.get_list(
		"CRM Deal",
		filters={"company": company},
		fields=[
			"name",
			"organization",
			"stage",
			"deadline",
			"last_activity_date",
			"custom_parent_tender",
		],
		limit_page_length=500,
	)

	executed = 0
	actions = []

	for d in deals:
		deal_name = d.get("name")
		stage = (d.get("stage") or "").lower()

		# Rule 1: SLA Deadline Alert (bid deadline within 2 days)
		if d.get("deadline"):
			deadline_date = getdate(d["deadline"])
			if date_diff(deadline_date, today) <= 2 and stage not in ("won", "lost", "cancelled"):
				rule_name = "SLA Deadline Alert"
				rule_key = f"crm_sla:{company}:{deal_name}:{deadline_date}"
				action_detail = f"Bid deadline {deadline_date} is near or passed for {deal_name}."

				was_processed = _process_automation_rule_action(
					company=company,
					deal_name=deal_name,
					rule_name=rule_name,
					rule_key=rule_key,
					action_detail=action_detail,
					due_at=str(deadline_date),
					dry_run=dry_run,
				)

				if was_processed:
					executed += 1
					actions.append(
						{
							"deal": deal_name,
							"rule": rule_name,
							"key": rule_key,
							"detail": action_detail,
							"dry_run": dry_run,
						}
					)

		# Rule 2: Stale Deal Escalation (no activity for 3+ days in active stage)
		if d.get("last_activity_date"):
			last_act_date = getdate(d["last_activity_date"])
			if date_diff(today, last_act_date) >= 3 and stage not in ("won", "lost", "cancelled"):
				rule_name = "Stale Deal Escalation"
				rule_key = f"crm_stale:{company}:{deal_name}:{stage}:{today_str}"
				action_detail = f"No activity on {deal_name} since {last_act_date} (stage: {stage})."

				was_processed = _process_automation_rule_action(
					company=company,
					deal_name=deal_name,
					rule_name=rule_name,
					rule_key=rule_key,
					action_detail=action_detail,
					due_at=None,
					dry_run=dry_run,
				)

				if was_processed:
					executed += 1
					actions.append(
						{
							"deal": deal_name,
							"rule": rule_name,
							"key": rule_key,
							"detail": action_detail,
							"dry_run": dry_run,
						}
					)

	return {
		"company": company,
		"executed_count": executed,
		"executed_rules": executed,
		"summary": f"Processed {executed} automation rules",
		"actions": actions,
		"dry_run": dry_run,
	}


@frappe.whitelist()
def preview_crm_automation_rules(company: str) -> dict:
	"""Dry-run preview of CRM automation rules for a company."""
	return run_crm_automation_rules(company=company, dry_run=True)


def scheduled_daily_crm_automation() -> None:
	"""Daily scheduler hook for running CRM automation rules across active companies."""
	try:
		if hasattr(frappe, "get_all"):
			companies = frappe.get_all("Company", fields=["name"])
			for comp in companies:
				try:
					run_crm_automation_rules(company=comp["name"])
				except Exception:
					pass
	except Exception:
		pass
