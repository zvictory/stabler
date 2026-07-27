"""Daily GL Integrity scan scheduler task.

Runs the integrity scan daily for all companies and emails Accounts Managers
if any anomalies are found.
"""

from __future__ import annotations

import frappe

from stabler.api.compliance import gl_integrity_scan


def nightly_scan() -> None:
	companies = frappe.get_all("Company", pluck="name")
	for company in companies:
		# Run scan as Administrator to bypass whitelisted role checks
		res = gl_integrity_scan(company)
		total_anomalies = sum(res.values())
		if total_anomalies > 0:
			# Find Accounts Manager email addresses
			recipients = frappe.db.sql(
				"""
				SELECT DISTINCT parent
				FROM `tabHas Role`
				WHERE role = 'Accounts Manager'
				""",
				pluck=True,
			)
			if not recipients:
				# Fallback to system managers
				recipients = frappe.db.sql(
					"""
					SELECT DISTINCT parent
					FROM `tabHas Role`
					WHERE role = 'System Manager'
					""",
					pluck=True,
				)

			if recipients:
				subject = f"[{company}] GL Integrity Anomaly Alert: {total_anomalies} issues found"
				body = f"""
				<p>Hello,</p>
				<p>The nightly GL Integrity Scan for company <strong>{company}</strong> has detected <strong>{total_anomalies}</strong> anomalies.</p>
				<ul>
					<li><strong>1:1 Foreign Postings (D2-style):</strong> {res.get("d2_postings", 0)}</li>
					<li><strong>Multi-Currency Parties:</strong> {res.get("multi_currency_parties", 0)}</li>
					<li><strong>Off-CBU Currency Exchange Docs:</strong> {res.get("off_cbu_docs", 0)}</li>
					<li><strong>Wrong Account Type Party Postings:</strong> {res.get("wrong_account_type_postings", 0)}</li>
				</ul>
				<p>Please review these issues on the Admin &rarr; Compliance page in the Stabler app.</p>
				<p>Best regards,<br>Stabler System Monitor</p>
				"""
				try:
					frappe.sendmail(
						recipients=recipients,
						subject=subject,
						message=body,
					)
				except frappe.OutgoingEmailError:
					msg = f"Failed to send GL integrity alert email: outgoing email account not set up. Anomalies found: {res}"
					frappe.log_error(message=msg, title="GL Integrity Email Error")
