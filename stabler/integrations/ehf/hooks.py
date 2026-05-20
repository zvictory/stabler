"""doc_events glue for EHF.

We funnel through this module rather than wiring submit_for_invoice
directly into hooks.py so the hook entry point can apply policy
(short-circuit on cancellations, skip when EHF is disabled per company,
etc.) without bloating submit.py with frappe.flags lookups.
"""

from __future__ import annotations

import frappe


def enqueue_ehf_submit(doc, method=None):  # noqa: ARG001 — Frappe signature
	if not doc or doc.docstatus != 1:
		return
	frappe.enqueue(
		"stabler.integrations.ehf.submit.submit_for_invoice",
		queue="long",
		name=doc.name,
		now=False,
	)
