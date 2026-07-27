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

from stabler.integrations.uzex import _status, client, telegram

_PORTAL = "etender"


def _notify(user: str | None, subject: str, deal_name: str) -> bool:
	"""Insert a Notification Log for `user`, deduped by (deal, subject).

	Returns True when a new notification was created. A re-run with the same
	status/deadline produces the same subject → already exists → no duplicate.
	"""
	if not user:
		return False
	if frappe.db.exists("Notification Log", {"document_name": deal_name, "subject": subject}):
		return False
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"subject": subject,
			"for_user": user,
			"type": "Alert",
			"document_type": "CRM Deal",
			"document_name": deal_name,
		}
	).insert(ignore_permissions=True)
	return True


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


def _maybe_set_terminal_status(doc, status_id, status_name: str | None) -> None:
	"""Fold a terminal portal outcome (won/lost) onto the Deal's pipeline status.

	Only moves the deal to a terminal CRM Deal Status that actually exists; an
	open (pending) lot is never forced backwards, so the human pipeline stays in
	control until the portal declares a result.
	"""
	result = _status.map_result(status_id, status_name)
	if not _status.is_terminal(result):
		return
	target = _status.deal_status_for(result)
	if target and doc.get("status") != target and frappe.db.exists("CRM Deal Status", target):
		doc.status = target


def _upsert_deal(norm: dict, status_raw, status_id, status_name) -> dict:
	"""Create or update the CRM Deal for one lot.

	Returns {action, deal, owner, changed} where ``changed`` is True when the raw
	portal status differs from what we last stored (the Deal row is the dedupe
	ledger for status-change notifications).
	"""
	existing = frappe.db.get_value("CRM Deal", {"custom_uzex_lot_no": norm["lot_no"]}, "name")
	if existing:
		doc = frappe.get_doc("CRM Deal", existing)
		old_status = doc.get("custom_uzex_status")
		_apply_fields(doc, norm, status_raw)
		_maybe_set_terminal_status(doc, status_id, status_name)
		doc.save(ignore_permissions=True)
		return {"action": "updated", "deal": doc.name, "owner": doc.get("deal_owner"),
		        "changed": bool(status_raw) and status_raw != old_status}

	doc = frappe.new_doc("CRM Deal")
	# organization = the buyer org (UZEX "seller"); fall back to the lot title.
	doc.organization = norm.get("customer_org") or norm.get("name") or norm["lot_no"]
	if norm.get("currency"):
		doc.currency = norm["currency"]
	_apply_fields(doc, norm, status_raw)
	_maybe_set_terminal_status(doc, status_id, status_name)
	doc.insert(ignore_permissions=True)
	# A brand-new tracked lot is itself a change worth surfacing.
	return {"action": "created", "deal": doc.name, "owner": doc.get("deal_owner"),
	        "changed": bool(status_raw)}


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

	created = updated = seen = notified = 0
	errors: list[str] = []
	now = now_datetime()

	for type_id in type_ids:
		try:
			rows = client.list_trades(int(type_id), 1, cap)
		except Exception as exc:  # isolate one lot type's failure
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

			status_raw = status_id = status_name = None
			try:
				detail = client.get_trade(norm["lot_id"])
				status_raw = client.status_from_detail(detail)
				status_id = detail.get("status_id")
				status_name = detail.get("status_name")
			except Exception:  # detail is best-effort; list data still upserts
				pass

			try:
				res = _upsert_deal(norm, status_raw, status_id, status_name)
				created += res["action"] == "created"
				updated += res["action"] == "updated"
				# New lot → Telegram card (once per lot: 'created' fires once).
				if res["action"] == "created":
					try:
						if telegram.send_new_lot(norm, res["deal"]):
							notified += 1
					except Exception:  # Telegram is best-effort
						frappe.log_error(
							title="UZEX poll: telegram send failed",
							message=f"lot_no={norm['lot_no']}\n{frappe.get_traceback()}",
						)
				# Status-change notification — deduped by the Deal row (old != new)
				# and by (deal, subject) inside _notify.
				if res["changed"] and status_raw:
					if _notify(res["owner"], f"UZEX {norm['lot_no']}: {status_raw}", res["deal"]):
						notified += 1
				# Deadline < 48h alert — deduped by the deadline in the subject.
				if _status.is_deadline_soon(norm.get("deadline"), now):
					subj = f"UZEX {norm['lot_no']}: deadline {norm['deadline']}"
					if _notify(res["owner"], subj, res["deal"]):
						notified += 1
			except Exception as exc:  # one bad row must not abort the batch
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
		"notified": notified,
		"errors": errors,
	}
	print(f"[stabler.tasks.uzex_poll] {summary}")
	return summary
