"""doc_events glue for Didox (not wired — manual send only).

Unlike ``ehf/hooks.py``, this is intentionally NOT registered on
`Sales Invoice.on_submit` in `stabler/hooks.py`. The user chose a manual
"Send to Didox" button in the SPA (accounting reviews before sending),
so this function exists for future use if automatic submission is ever
requested, but nothing currently calls it.

If wired later, it should enqueue prepare_for_invoice() only — send_signed()
cannot run here because signing happens in the browser via the user's own
E-IMZO key and requires a round trip through stabler.api.edo.didox_send.
"""

from __future__ import annotations

import frappe


def enqueue_didox_submit(doc, method=None):  # Frappe signature
	if not doc or doc.docstatus != 1:
		return
	frappe.enqueue(
		"stabler.integrations.didox.submit.prepare_for_invoice",
		queue="long",
		name=doc.name,
		now=False,
	)


# Cap per scheduler tick so one slow/large batch cannot monopolise the worker
# or spin against a flapping Didox endpoint. Sent rows that miss a tick are
# simply picked up on the next hourly run — see stabler/hooks.py scheduler_events.
_SYNC_BATCH_LIMIT = 50


def sync_pending_statuses():
	"""Poll every still-open ЭСФ and fold Didox's answer back onto the row.

	Registered under ``scheduler_events["hourly"]`` in ``stabler/hooks.py``.
	Only ``Sent`` submissions that carry a ``didox_doc_id`` have a live remote
	state to poll — Draft/Signed never left our side, Accepted/Rejected are
	terminal, Error is a local send failure. Each row is polled independently so
	one endpoint failure (recorded as ``status=Error`` by ``client.poll_status``)
	does not abort the rest of the batch.
	"""
	from stabler.integrations.didox import client

	if not getattr(frappe.conf, "didox_endpoint", None):
		# No endpoint configured (e.g. sites without Didox) — nothing to poll.
		return

	pending = frappe.get_all(
		"Didox Submission",
		filters={"status": "Sent", "didox_doc_id": ["is", "set"]},
		pluck="name",
		order_by="submitted_at asc",
		limit=_SYNC_BATCH_LIMIT,
	)

	for name in pending:
		try:
			client.poll_status(name)
		except Exception:  # isolate one bad row from the batch
			frappe.log_error(
				title="Didox status sync failed",
				message=f"submission={name}\n{frappe.get_traceback()}",
			)
