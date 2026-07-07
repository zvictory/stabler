"""Hourly UZEX etender poller → idempotent CRM Deal upsert (WP-302).

Discovers lots via ``client.list_trades`` and folds them onto CRM Deals keyed by
``custom_uzex_lot_no`` (the UNIQUE display_no from v39) — so a second run over
the same lots creates ZERO duplicate Deals. Mirrors ``tasks/cbu_rate_refresh``:
frappe-free network in ``integrations/uzex``, a single commit at the end of the
job (never per-row, never in a request handler).

Resilience (CBU stale-rate pattern): if a lot type's fetch fails the error is
logged and the loop moves on — those lots keep their old ``custom_uzex_last_synced``
so the SPA can flag them stale; the poller never crashes the scheduler.

Ingestion is keyword-gated (``frappe.conf.uzex_keywords``) so an unfiltered site
does not flood CRM with every public tender: a NEW lot becomes a Deal only when
its name matches a keyword; already-tracked Deals are refreshed regardless.

Registered under scheduler_events["hourly"] in stabler/hooks.py.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import now_datetime

from stabler.integrations.uzex import client

_PORTAL = "etender"


def _config_list(key: str) -> list:
	val = getattr(frappe.conf, key, None)
	if not val:
		return []
	return list(val) if isinstance(val, (list, tuple)) else [val]


def _apply_fields(doc, norm: dict, status_raw: str | None) -> None:
	"""Write the custom_uzex_* values + last_synced onto a Deal doc."""
	doc.custom_uzex_lot_no = norm["lot_no"]
	doc.custom_uzex_portal = _PORTAL
	if status_raw is not None:
		doc.custom_uzex_status = status_raw
	if norm.get("deadline"):
		doc.custom_uzex_deadline = norm["deadline"]
	if norm.get("start_price") is not None:
		doc.custom_uzex_start_price = norm["start_price"]
	if norm.get("customer_org"):
		doc.custom_uzex_customer_org = norm["customer_org"]
	doc.custom_uzex_last_synced = now_datetime()


def _upsert_deal(norm: dict, status_raw: str | None) -> str:
	"""Create or update the CRM Deal for one lot. Returns 'created'/'updated'."""
	existing = frappe.db.get_value("CRM Deal", {"custom_uzex_lot_no": norm["lot_no"]}, "name")
	if existing:
		doc = frappe.get_doc("CRM Deal", existing)
		_apply_fields(doc, norm, status_raw)
		doc.save(ignore_permissions=True)
		return "updated"

	doc = frappe.new_doc("CRM Deal")
	# organization = the buyer org (UZEX "seller"); fall back to the lot title.
	doc.organization = norm.get("customer_org") or norm.get("name") or norm["lot_no"]
	if norm.get("currency"):
		doc.currency = norm["currency"]
	_apply_fields(doc, norm, status_raw)
	doc.insert(ignore_permissions=True)
	return "created"


def fetch_and_store() -> dict[str, Any]:
	"""Hourly entry point. Returns a summary dict for logs."""
	if not frappe.db.exists("DocType", "CRM Deal"):
		return {"status": "skipped", "reason": "CRM Deal doctype missing"}
	if not frappe.db.has_column("CRM Deal", "custom_uzex_lot_no"):
		# v39 not migrated yet — do nothing rather than error.
		return {"status": "skipped", "reason": "custom_uzex_lot_no column missing (run migrate)"}

	keywords = _config_list("uzex_keywords")
	type_ids = _config_list("uzex_type_ids") or list(client.UZEX_TYPE_IDS)
	cap = int(getattr(frappe.conf, "uzex_poll_cap", 50) or 50)

	created = updated = seen = 0
	errors: list[str] = []

	for type_id in type_ids:
		try:
			rows = client.list_trades(int(type_id), 1, cap)
		except Exception as exc:  # noqa: BLE001 — isolate one lot type's failure
			errors.append(f"type {type_id}: {exc}")
			frappe.log_error(
				title="UZEX poll: list_trades failed",
				message=f"type_id={type_id}\n{frappe.get_traceback()}",
			)
			continue

		for row in rows:
			norm = client.parse_trade_row(row)
			if not norm["lot_no"]:
				continue
			seen += 1
			tracked = frappe.db.exists("CRM Deal", {"custom_uzex_lot_no": norm["lot_no"]})
			# Flood guard: a brand-new lot is ingested only when it matches a
			# configured keyword; tracked lots always refresh.
			if not tracked and not client.matches_keywords(norm["name"], keywords):
				continue

			status_raw = None
			try:
				detail = client.get_trade(norm["lot_id"])
				status_raw = client.status_from_detail(detail)
			except Exception:  # noqa: BLE001 — detail is best-effort; list data still upserts
				pass

			try:
				result = _upsert_deal(norm, status_raw)
				created += result == "created"
				updated += result == "updated"
			except Exception as exc:  # noqa: BLE001 — one bad row must not abort the batch
				errors.append(f"lot {norm['lot_no']}: {exc}")
				frappe.log_error(
					title="UZEX poll: deal upsert failed",
					message=f"lot_no={norm['lot_no']}\n{frappe.get_traceback()}",
				)

	frappe.db.commit()
	summary = {
		"status": "ok" if not errors else "partial",
		"seen": seen,
		"created": created,
		"updated": updated,
		"errors": errors,
	}
	print(f"[stabler.tasks.uzex_poll] {summary}")
	return summary
