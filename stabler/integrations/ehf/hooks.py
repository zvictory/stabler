"""doc_events glue for EHF.

We funnel through this module rather than wiring submit_for_invoice
directly into hooks.py so the hook entry point can apply policy
(short-circuit on cancellations, skip when EHF is disabled per company,
etc.) without bloating submit.py with frappe.flags lookups.
"""

from __future__ import annotations

import frappe

from stabler.integrations._gates import ehf_can_submit


def _configured() -> bool:
	"""Ask what `sign()` asks, before making the job instead of after."""
	return ehf_can_submit(
		eimzo_endpoint=getattr(frappe.conf, "eimzo_endpoint", None),
		stub_signature=getattr(frappe.conf, "ehf_stub_signature", None),
	)


def enqueue_ehf_submit(doc, method=None):  # Frappe signature
	if not doc or doc.docstatus != 1:
		return
	if not _configured():
		# The policy this module's docstring has always claimed to apply, finally
		# applied. Measured on prod 2026-08-28: `eimzo_endpoint` and
		# `ehf_stub_signature` unset on all eight tenants, and anjan carrying
		# 8576 EHF Submission rows since 2026-05-30 — every one status Error,
		# every one "EIMZO endpoint not configured", none ever successful, 481 in
		# the last week alone. `submit_for_invoice` catches the failure and
		# writes it onto the submission rather than the log, which is why three
		# months of it went unseen.
		return
	frappe.enqueue(
		"stabler.integrations.ehf.submit.submit_for_invoice",
		queue="long",
		name=doc.name,
		now=False,
	)
