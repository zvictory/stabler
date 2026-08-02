"""Live Authenticated UAT execution script on bench site stabler.
"""

import json
import os
import frappe

def run():
	output = {}

	# 1. Admin Session Verification (Administrator)
	frappe.set_user("Administrator")
	roles_admin = frappe.get_roles("Administrator")

	from stabler.api import crm_analytics, sourcing, crm_email, crm_automation

	try:
		email_res_admin = crm_email.send_deal_email(
			deal="CRM-DEAL-2026-00005",
			subject="UAT Email Test [CRM-DEAL-2026-00005]",
			content="Live UAT email content",
			company="Mikas",
			recipients="test@example.com",
			idempotency_key="UAT-20260802-KEY1",
		)
		email_status_admin = "200 OK"
	except Exception as err:
		email_res_admin = str(err)
		email_status_admin = "ERROR"

	output["admin_session"] = {
		"user": "Administrator",
		"roles": roles_admin,
		"send_email": {"status": email_status_admin, "data": email_res_admin},
	}

	# 2. Manager Role Verification (hayrulloh@mail.com)
	frappe.set_user("hayrulloh@mail.com")
	roles_manager = frappe.get_roles("hayrulloh@mail.com")

	try:
		cockpit_res = crm_analytics.get_manager_cockpit_metrics(company="Mikas")
		cockpit_status = "200 OK"
	except Exception as err:
		cockpit_res = str(err)
		cockpit_status = "ERROR"

	try:
		rfq_defaults = sourcing.get_deal_rfq_defaults(deal="CRM-DEAL-2026-00005", company="Mikas")
		rfq_status = "200 OK"
	except Exception as err:
		rfq_defaults = str(err)
		rfq_status = "ERROR"

	try:
		auto_preview = crm_automation.preview_crm_automation_rules(company="Mikas")
		auto_status = "200 OK"
	except Exception as err:
		auto_preview = str(err)
		auto_status = "ERROR"

	output["manager_session"] = {
		"user": "hayrulloh@mail.com",
		"roles": roles_manager,
		"cockpit_metrics": {"status": cockpit_status, "data": cockpit_res},
		"rfq_defaults": {"status": rfq_status, "data": rfq_defaults},
		"automation_preview": {"status": auto_status, "data": auto_preview},
	}

	# 3. Non-Manager Role Verification (fayzulloxoshimov61@gmail.com)
	frappe.set_user("fayzulloxoshimov61@gmail.com")
	roles_non_manager = frappe.get_roles("fayzulloxoshimov61@gmail.com")

	cockpit_neg = None
	try:
		crm_analytics.get_manager_cockpit_metrics(company="Mikas")
		cockpit_neg_status = "200 OK (UNEXPECTED)"
	except frappe.PermissionError as err:
		cockpit_neg_status = "403 PermissionError (REJECTED AS EXPECTED)"
		cockpit_neg = str(err)
	except Exception as err:
		cockpit_neg_status = f"ERROR ({err})"
		cockpit_neg = str(err)

	auto_neg = None
	try:
		crm_automation.preview_crm_automation_rules(company="Mikas")
		auto_neg_status = "200 OK (UNEXPECTED)"
	except frappe.PermissionError as err:
		auto_neg_status = "403 PermissionError (REJECTED AS EXPECTED)"
		auto_neg = str(err)
	except Exception as err:
		auto_neg_status = f"ERROR ({err})"
		auto_neg = str(err)

	output["non_manager_session"] = {
		"user": "fayzulloxoshimov61@gmail.com",
		"roles": roles_non_manager,
		"cockpit_metrics_negative": {"status": cockpit_neg_status, "error": cockpit_neg},
		"automation_preview_negative": {"status": auto_neg_status, "error": auto_neg},
	}

	# Write evidence JSON file
	out_dir = "/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-final-hardening"
	os.makedirs(out_dir, exist_ok=True)
	out_file = os.path.join(out_dir, "live_authenticated_uat_results.json")
	with open(out_file, "w", encoding="utf-8") as f:
		json.dump(output, f, indent=2, default=str)

	print(f"UAT completed successfully. Written to {out_file}")

if __name__ == "__main__":
	run()
