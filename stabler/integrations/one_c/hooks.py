"""1C outbound hook wrappers.

These thin wrappers exist so hooks.py can reference a stable target while
the underlying push() signature can evolve. Each enqueues the actual push
on the long queue so doc submission never blocks on a remote 1C call.
"""

from __future__ import annotations

import frappe


def enqueue_push(doc, method=None) -> None:
	if getattr(doc, "docstatus", 0) != 1:
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
