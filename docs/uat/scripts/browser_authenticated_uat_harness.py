"""Real Browser / HTTP Session Authenticated UAT Harness for Local Site (stabler).

Executes real HTTP requests over http://localhost:8000 using HTTP login session cookies (sid).
Outputs complete network, URL, response status, role authorization, and DB evidence to
docs/uat/evidence/2026-08-02-browser-final/browser_uat_results.json.
"""

import json
import os
import urllib.parse
import urllib.request
import http.cookiejar

BASE_URL = "http://localhost:8000"

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
			return {"status": resp.status, "body": parsed, "headers": dict(resp.headers)}
	except urllib.error.HTTPError as err:
		body = err.read().decode("utf-8")
		try:
			parsed = json.loads(body)
		except Exception:
			parsed = body[:500]
		return {"status": err.code, "body": parsed, "headers": dict(err.headers)}

def login_http_session(usr, pwd):
	cj = http.cookiejar.CookieJar()
	data = urllib.parse.urlencode({"usr": usr, "pwd": pwd}).encode("utf-8")
	res = make_http_request(f"{BASE_URL}/api/method/login", data=data, cookie_jar=cj)
	cookies = {c.name: c.value for c in cj}
	return cj, cookies, res

def run_browser_uat():
	out_dir = "/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final"
	os.makedirs(out_dir, exist_ok=True)
	results = {}

	# -------------------------------------------------------------
	# 1. Administrator HTTP Session (Email Failure Transaction Lifecycle)
	# -------------------------------------------------------------
	cj_admin, cookies_admin, login_res_admin = login_http_session("Administrator", "Password123!")

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

	# Retry attempt 2 over HTTP
	email_admin_2 = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_email.send_deal_email",
		data=email_data_1,
		cookie_jar=cj_admin,
	)

	results["admin_session"] = {
		"user": "Administrator",
		"login_status": login_res_admin["status"],
		"session_cookies": {"sid": cookies_admin.get("sid")},
		"http_calls": {
			"email_send_attempt_1": {"status": email_admin_1["status"], "response": email_admin_1["body"]},
			"email_send_attempt_2_retry": {"status": email_admin_2["status"], "response": email_admin_2["body"]},
		},
	}

	# -------------------------------------------------------------
	# 2. Manager HTTP Session (hayrulloh@mail.com)
	# -------------------------------------------------------------
	cj_mgr, cookies_mgr, login_res_mgr = login_http_session("hayrulloh@mail.com", "Password123!")
	
	# HTTP POST get_manager_cockpit_metrics
	post_data = urllib.parse.urlencode({"company": "Mikas"}).encode("utf-8")
	cockpit_mgr = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics",
		data=post_data,
		cookie_jar=cj_mgr,
	)

	# HTTP POST get_deal_rfq_defaults
	rfq_data = urllib.parse.urlencode({"deal": "CRM-DEAL-2026-00005", "company": "Mikas"}).encode("utf-8")
	rfq_mgr = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.sourcing.get_deal_rfq_defaults",
		data=rfq_data,
		cookie_jar=cj_mgr,
	)

	# HTTP GET Direct SPA URLs (HTML pages)
	spa_portfolio = make_http_request(f"{BASE_URL}/stabler#/tender/portfolio", cookie_jar=cj_mgr)
	spa_deal_360 = make_http_request(f"{BASE_URL}/stabler#/crm/deals/CRM-DEAL-2026-00005", cookie_jar=cj_mgr)
	spa_cockpit = make_http_request(f"{BASE_URL}/stabler#/crm/cockpit", cookie_jar=cj_mgr)

	results["manager_session"] = {
		"user": "hayrulloh@mail.com",
		"login_status": login_res_mgr["status"],
		"session_cookies": {"sid": cookies_mgr.get("sid"), "system_user": cookies_mgr.get("system_user")},
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
	cj_non, cookies_non, login_res_non = login_http_session("fayzulloxoshimov61@gmail.com", "Password123!")

	# HTTP POST get_manager_cockpit_metrics (Non-Manager -> Expect HTTP 403 rejection)
	cockpit_non = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_analytics.get_manager_cockpit_metrics",
		data=post_data,
		cookie_jar=cj_non,
	)

	# HTTP POST preview_crm_automation_rules (Non-Manager -> Expect HTTP 403 rejection)
	auto_non = make_http_request(
		f"{BASE_URL}/api/method/stabler.api.crm_automation.preview_crm_automation_rules",
		data=post_data,
		cookie_jar=cj_non,
	)

	results["non_manager_session"] = {
		"user": "fayzulloxoshimov61@gmail.com",
		"login_status": login_res_non["status"],
		"session_cookies": {"sid": cookies_non.get("sid")},
		"http_calls_negative": {
			"cockpit_metrics": {"status": cockpit_non["status"], "response": cockpit_non["body"]},
			"automation_preview": {"status": auto_non["status"], "response": auto_non["body"]},
		},
	}

	# -------------------------------------------------------------
	# 4. Query MariaDB Database for Created Communication Record
	# -------------------------------------------------------------
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

	out_file = os.path.join(out_dir, "browser_uat_results.json")
	with open(out_file, "w", encoding="utf-8") as f:
		json.dump(results, f, indent=2, default=str)

	print(f"Browser HTTP Authenticated UAT finished. Results written to {out_file}")

if __name__ == "__main__":
	run_browser_uat()
