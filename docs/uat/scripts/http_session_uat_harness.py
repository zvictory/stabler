"""HTTP Session Authenticated UAT Harness for Local Site (stabler).

Executes HTTP requests over http://localhost:8000 using HTTP login session cookies.
Reads test user passwords strictly from environment variables or local private secret store.
Outputs redacted network, URL, response status, role authorization, and DB evidence to
docs/uat/evidence/2026-08-02-browser-final/http_session_uat_results.json.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import http.cookiejar

BASE_URL = "http://localhost:8000"

def load_secrets():
	env_file = "/Users/zafar/frappe-bench-local/.uat_secrets.env"
	if os.path.exists(env_file):
		with open(env_file, "r") as f:
			for line in f:
				line = line.strip()
				if line and "=" in line:
					k, v = line.split("=", 1)
					os.environ[k] = v

	mgr_pass = os.environ.get("STABLER_UAT_MANAGER_PASS")
	nonmgr_pass = os.environ.get("STABLER_UAT_NONMANAGER_PASS")
	admin_pass = os.environ.get("STABLER_UAT_ADMIN_PASS")

	if not (mgr_pass and nonmgr_pass and admin_pass):
		raise RuntimeError("Missing required UAT password environment variables (STABLER_UAT_MANAGER_PASS, etc.).")
	return mgr_pass, nonmgr_pass, admin_pass

def make_http_request(url, data=None, headers=None, cookie_jar=None, method=None):
	req = urllib.request.Request(url, data=data, headers=headers or {})
	if method:
		req.get_method = lambda: method
	opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
	try:
		with opener.open(req) as resp:
			body = resp.read().decode("utf-8")
			try:
				parsed = json.loads(body)
			except Exception:
				parsed = body[:500]
			return {"status": resp.status, "body": parsed, "headers": {k: "<redacted>" if k.lower() in ("set-cookie", "authorization") else v for k, v in resp.headers.items()}}
	except urllib.error.HTTPError as err:
		body = err.read().decode("utf-8")
		try:
			parsed = json.loads(body)
		except Exception:
			parsed = body[:500]
		return {"status": err.code, "body": parsed, "headers": {k: "<redacted>" if k.lower() in ("set-cookie", "authorization") else v for k, v in err.headers.items()}}

def login_http_session(usr, pwd):
	cj = http.cookiejar.CookieJar()
	data = urllib.parse.urlencode({"usr": usr, "pwd": pwd}).encode("utf-8")
	res = make_http_request(f"{BASE_URL}/api/method/login", data=data, cookie_jar=cj)
	return cj, res

def run_http_session_uat():
	mgr_pass, nonmgr_pass, admin_pass = load_secrets()
	out_dir = "/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final"
	os.makedirs(out_dir, exist_ok=True)
	results = {}

	# -------------------------------------------------------------
	# 1. Administrator HTTP Session (Email Failure Transaction Lifecycle)
	# -------------------------------------------------------------
	cj_admin, login_res_admin = login_http_session("Administrator", admin_pass)

	comm_key_id = "HTTP-UAT-KEY-99"
	email_data_1 = urllib.parse.urlencode({
		"deal": "CRM-DEAL-2026-00005",
		"subject": "HTTP UAT Email Test",
		"content": "Testing HTTP UAT transaction failure and retry",
		"company": "Mikas",
		"recipients": "test@example.com",
		"idempotency_key": comm_key_id,
	}).encode("utf-8")

	email_admin_1 = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_email.send_deal_email",
		data=email_data_1,
		cookie_jar=cj_admin,
	)

	email_admin_2 = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_email.send_deal_email",
		data=email_data_1,
		cookie_jar=cj_admin,
	)

	results["admin_session"] = {
		"user": "Administrator",
		"login_status": login_res_admin["status"],
		"session_cookies": {"sid": "<redacted>"},
		"http_calls": {
			"email_send_attempt_1": {"status": email_admin_1["status"], "response": email_admin_1["body"]},
			"email_send_attempt_2_retry": {"status": email_admin_2["status"], "response": email_admin_2["body"]},
		},
	}

	# -------------------------------------------------------------
	# 2. Manager HTTP Session (hayrulloh@mail.com)
	# -------------------------------------------------------------
	cj_mgr, login_res_mgr = login_http_session("hayrulloh@mail.com", mgr_pass)

	post_data = urllib.parse.urlencode({"company": "Mikas"}).encode("utf-8")
	cockpit_mgr = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics",
		data=post_data,
		cookie_jar=cj_mgr,
	)

	rfq_data = urllib.parse.urlencode({"deal": "CRM-DEAL-2026-00005", "company": "Mikas"}).encode("utf-8")
	rfq_mgr = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.sourcing.get_deal_rfq_defaults",
		data=rfq_data,
		cookie_jar=cj_mgr,
	)

	results["manager_session"] = {
		"user": "hayrulloh@mail.com",
		"login_status": login_res_mgr["status"],
		"session_cookies": {"sid": "<redacted>", "system_user": "<redacted>"},
		"routes": {
			"portfolio_url": f"{BASE_URL}/stabler#/tender/portfolio",
			"deal_360_url": f"{BASE_URL}/stabler#/crm/deals/CRM-DEAL-2026-00005",
			"cockpit_url": f"{BASE_URL}/stabler#/crm/cockpit",
		},
		"http_calls": {
			"cockpit_metrics": {"status": cockpit_mgr["status"], "response": cockpit_mgr["body"]},
			"rfq_defaults": {"status": rfq_mgr["status"], "response": rfq_mgr["body"]},
		},
	}

	# -------------------------------------------------------------
	# 3. Non-Manager HTTP Session (fayzulloxoshimov61@gmail.com)
	# -------------------------------------------------------------
	cj_non, login_res_non = login_http_session("fayzulloxoshimov61@gmail.com", nonmgr_pass)

	cockpit_non = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics",
		data=post_data,
		cookie_jar=cj_non,
	)

	auto_non = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_automation.preview_crm_automation_rules",
		data=post_data,
		cookie_jar=cj_non,
	)

	results["non_manager_session"] = {
		"user": "fayzulloxoshimov61@gmail.com",
		"login_status": login_res_non["status"],
		"session_cookies": {"sid": "<redacted>"},
		"http_calls_negative": {
			"cockpit_metrics": {"status": cockpit_non["status"], "response": cockpit_non["body"]},
			"automation_preview": {"status": auto_non["status"], "response": auto_non["body"]},
		},
	}

	# -------------------------------------------------------------
	# 4. Database Audit Verification
	# -------------------------------------------------------------
	os.chdir("/Users/zafar/frappe-bench-local/sites")
	import frappe
	frappe.init(site="stabler", sites_path="/Users/zafar/frappe-bench-local/sites")
	frappe.connect()

	comm_key = f"comm:Mikas:{comm_key_id}"
	comm_rows = frappe.db.sql(
		"SELECT name, custom_idempotency_key, custom_execution_status, custom_attempts, custom_last_error FROM tabCommunication WHERE custom_idempotency_key = %s",
		(comm_key,),
		as_dict=True,
	)
	frappe.destroy()

	results["database_audit"] = {
		"idempotency_key": comm_key,
		"records_found": len(comm_rows),
		"rows": comm_rows,
		"durable_failed_status_verified": len(comm_rows) == 1 and comm_rows[0]["custom_execution_status"] == "Failed" and comm_rows[0]["custom_attempts"] == 2,
	}

	out_file = os.path.join(out_dir, "http_session_uat_results.json")
	with open(out_file, "w", encoding="utf-8") as f:
		json.dump(results, f, indent=2, default=str)

	print(f"HTTP Session Authenticated UAT finished. Results written to {out_file}")

if __name__ == "__main__":
	run_http_session_uat()
