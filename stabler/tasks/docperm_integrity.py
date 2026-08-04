"""Daily Custom DocPerm shadowing scan.

Detects the failure mode behind the 2026-08-03/04 incident: a ``Custom DocPerm``
row inserted directly (instead of via ``frappe.permissions.add_permission()``)
makes a doctype's entire standard ``DocPerm`` set inert, silently stripping every
standard role of read/report.

Reports only — it never repairs. Automatic repair would re-open deliberate admin
restrictions, so a human decides. Repair is available as
``stabler.api.permissions.repair_shadowed_docperms``.
"""

from __future__ import annotations

import frappe

from stabler.api.permissions import detect_shadowed_doctypes


def nightly_scan() -> None:
	findings = detect_shadowed_doctypes()
	if not findings:
		return

	lines = []
	for f in findings:
		roles = ", ".join(
			f"{m['role']} (permlevel {m['permlevel']})" for m in f["missing"]
		)
		lines.append(f"<li><strong>{f['doctype']}</strong>: {roles}</li>")
	details = "".join(lines)

	summary = f"{len(findings)} doctype(s) with shadowed permissions: " + ", ".join(
		f["doctype"] for f in findings
	)
	# Always leave a trace, even when outgoing email is not configured.
	frappe.log_error(message=summary, title="Custom DocPerm Shadowing Detected")

	recipients = frappe.db.sql(
		"""
		SELECT DISTINCT parent
		FROM `tabHas Role`
		WHERE role = 'System Manager'
		""",
		pluck=True,
	)
	if not recipients:
		return

	subject = f"[{frappe.local.site}] Permission drift: {len(findings)} doctype(s) shadowed"
	body = f"""
	<p>Hello,</p>
	<p>The nightly permission scan found doctypes whose <code>Custom DocPerm</code>
	rows shadow the standard permission set. Every role listed below has silently
	lost read and/or report access.</p>
	<ul>{details}</ul>
	<p>Cause: permissions were written directly into <code>Custom DocPerm</code>
	instead of via <code>frappe.permissions.add_permission()</code>, which copies
	the full standard set first.</p>
	<p>Repair with
	<code>bench --site {frappe.local.site} execute
	stabler.api.permissions.repair_shadowed_docperms</code> after confirming none
	of these restrictions were intentional.</p>
	<p>Best regards,<br>Stabler System Monitor</p>
	"""
	try:
		frappe.sendmail(recipients=recipients, subject=subject, message=body)
	except frappe.OutgoingEmailError:
		frappe.log_error(
			message=f"Failed to send permission drift alert: outgoing email not set up. {summary}",
			title="DocPerm Integrity Email Error",
		)
