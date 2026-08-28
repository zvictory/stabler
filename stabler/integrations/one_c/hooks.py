"""1C outbound hook wrappers.

These thin wrappers exist so hooks.py can reference a stable target while
the underlying push() signature can evolve. Each enqueues the actual push
on the long queue so doc submission never blocks on a remote 1C call.
"""

from __future__ import annotations

import frappe

from stabler.integrations._gates import one_c_can_push


def _configured() -> bool:
	"""Read the same three values `push()` reads, before making the job."""
	mode = (
		frappe.db.get_single_value("Stabler Settings", "onec_mode")
		if frappe.db.exists("DocType", "Stabler Settings")
		else "file"
	)
	return one_c_can_push(
		mode,
		outbox=getattr(frappe.conf, "onec_outbox", None),
		rest_endpoint=getattr(frappe.conf, "onec_rest_endpoint", None),
	)


def enqueue_push(doc, method=None) -> None:
	if getattr(doc, "docstatus", 0) != 1:
		return
	if not _configured():
		# The "am I configured" question used to be asked inside push(), one
		# worker later. Measured on prod 2026-08-28: `onec_outbox` and
		# `onec_rest_endpoint` are unset on all eight tenants, and `1C Sync Log`
		# does not exist as a table on any of them — so every one of those jobs
		# ran, found nothing to write to, and could not even record that it had.
		# Meanwhile `long` is one queue for the whole bench, and frappe refuses
		# every new enqueue at 650.
		return
	frappe.enqueue(
		"stabler.integrations.one_c.outbound.push",
		queue="long",
		doctype=doc.doctype,
		name=doc.name,
	)


def hourly_sync() -> None:
	"""Run inbound file-drop scan, and REST poll if mode=rest."""
	try:
		from stabler.integrations.one_c.file_drop import scan

		scan()
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"1C file_drop scan: {exc}")

	mode = (
		frappe.db.get_single_value("Stabler Settings", "onec_mode")
		if frappe.db.exists("DocType", "Stabler Settings")
		else "file"
	)
	if mode == "rest":
		try:
			from stabler.integrations.one_c.rest import poll

			poll()
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), f"1C rest poll: {exc}")
