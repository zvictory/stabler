"""Compliance API for Stabler — Uzbekistan plumbing.

Admin-only endpoints aggregating EHF / 1C / Asl Belgisi / ARCA / CBU
status & logs. Mirrors the gate in stabler/api/admin.py.
"""

from __future__ import annotations

import datetime
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe
from frappe import _

from stabler.integrations.ehf import submit as ehf_submit
from stabler.tasks.cbu_rate_refresh import fetch_and_store


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_admin_or_warehouse() -> None:
	roles = set(frappe.get_roles())
	if not roles & {"System Manager", "Stock Manager", "Stock User", "Warehouse User"}:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def refresh_cbu_rates() -> dict:
	"""Manual trigger for the daily CBU refresh — Admin-only."""
	_require_admin()
	return fetch_and_store()


@frappe.whitelist()
def list_exchange_rates(days: int = 30) -> list[dict]:
	"""Return the last N days of UZS exchange rates for USD/EUR/RUB.

	Shape: [{date: "YYYY-MM-DD", USD: 12500.0, EUR: 13800.0, RUB: 140.5}, ...]
	Sorted by date descending; missing currencies for a given date are
	left out of that day's dict.
	"""
	_require_admin()

	try:
		days = max(1, min(int(days), 365))
	except (TypeError, ValueError):
		days = 30

	since = datetime.date.today() - datetime.timedelta(days=days)
	rows = frappe.db.sql(
		"""
		SELECT date, from_currency, exchange_rate
		FROM `tabCurrency Exchange`
		WHERE to_currency = 'UZS'
		  AND from_currency IN ('USD', 'EUR', 'RUB')
		  AND date >= %s
		ORDER BY date DESC
		""",
		(since,),
		as_dict=True,
	)

	by_date: dict[str, dict] = {}
	for row in rows:
		key = row["date"].isoformat() if isinstance(row["date"], datetime.date) else str(row["date"])
		bucket = by_date.setdefault(key, {"date": key})
		bucket[row["from_currency"]] = float(row["exchange_rate"])

	return sorted(by_date.values(), key=lambda d: d["date"], reverse=True)


# ---------------------------------------------------------------------------
# EHF (Elektron Hisob-Faktura)
# ---------------------------------------------------------------------------

_EHF_STATUSES = ("Pending", "Submitted", "Accepted", "Rejected", "Error")


@frappe.whitelist()
def list_ehf_submissions(
	status: str | None = None,
	reference_invoice: str | None = None,
	limit: int = 50,
) -> list[dict]:
	_require_admin()
	try:
		limit = max(1, min(int(limit), 500))
	except (TypeError, ValueError):
		limit = 50

	filters: dict = {}
	if status and status in _EHF_STATUSES:
		filters["soliq_status"] = status
	if reference_invoice:
		filters["reference_invoice"] = reference_invoice

	rows = frappe.get_all(
		"EHF Submission",
		filters=filters,
		fields=[
			"name",
			"reference_invoice",
			"soliq_status",
			"soliq_uuid",
			"submitted_at",
			"retry_count",
			"error_message",
			"creation",
		],
		order_by="creation desc",
		limit=limit,
	)
	return rows


@frappe.whitelist()
def get_ehf_payload(name: str) -> dict:
	_require_admin()
	doc = frappe.get_doc("EHF Submission", name)
	payload = None
	if doc.payload_json:
		try:
			payload = json.loads(doc.payload_json)
		except json.JSONDecodeError:
			payload = doc.payload_json
	return {
		"name": doc.name,
		"reference_invoice": doc.reference_invoice,
		"soliq_status": doc.soliq_status,
		"soliq_uuid": doc.soliq_uuid,
		"submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None,
		"retry_count": doc.retry_count,
		"error_message": doc.error_message,
		"payload": payload,
		"signature": doc.signature,
	}


@frappe.whitelist()
def retry_ehf(name: str) -> dict:
	_require_admin()
	return ehf_submit.retry(name)


# ---------------------------------------------------------------------------
# 1C:Enterprise sync log
# ---------------------------------------------------------------------------

_ONEC_DIRECTIONS = ("In", "Out")
_ONEC_STATUSES = ("Pending", "OK", "Error")
_ONEC_OBJECT_TYPES = (
	"Customer",
	"Item",
	"PriceList",
	"Warehouse",
	"SalesInvoice",
	"PaymentEntry",
	"StockEntry",
)


@frappe.whitelist()
def list_onec_logs(
	direction: str | None = None,
	status: str | None = None,
	object_type: str | None = None,
	limit: int = 100,
) -> list[dict]:
	_require_admin()
	try:
		limit = max(1, min(int(limit), 500))
	except (TypeError, ValueError):
		limit = 100

	filters: dict = {}
	if direction and direction in _ONEC_DIRECTIONS:
		filters["direction"] = direction
	if status and status in _ONEC_STATUSES:
		filters["status"] = status
	if object_type and object_type in _ONEC_OBJECT_TYPES:
		filters["object_type"] = object_type

	return frappe.get_all(
		"One C Sync Log",
		filters=filters,
		fields=[
			"name",
			"direction",
			"object_type",
			"object_name",
			"status",
			"duration_ms",
			"message",
			"creation",
		],
		order_by="creation desc",
		limit=limit,
	)


@frappe.whitelist()
def get_onec_log(name: str) -> dict:
	_require_admin()
	doc = frappe.get_doc("One C Sync Log", name)
	payload = None
	if doc.payload:
		try:
			payload = json.loads(doc.payload)
		except json.JSONDecodeError:
			payload = doc.payload
	return {
		"name": doc.name,
		"direction": doc.direction,
		"object_type": doc.object_type,
		"object_name": doc.object_name,
		"status": doc.status,
		"duration_ms": doc.duration_ms,
		"message": doc.message,
		"payload": payload,
		"creation": doc.creation.isoformat() if doc.creation else None,
	}


# ---------------------------------------------------------------------------
# Asl Belgisi (mandatory product marking)
# ---------------------------------------------------------------------------

_DEFAULT_ASL_REGEX = r"^[0-9A-Z]{8,32}$"


def _asl_regex() -> re.Pattern[str]:
	pattern = (
		frappe.db.get_single_value("Stabler Settings", "asl_code_regex")
		if frappe.db.exists("DocType", "Stabler Settings")
		else None
	) or _DEFAULT_ASL_REGEX
	try:
		return re.compile(pattern)
	except re.error:
		return re.compile(_DEFAULT_ASL_REGEX)


def _verify_with_asl_endpoint(code: str) -> tuple[bool, str]:
	endpoint = getattr(frappe.conf, "asl_endpoint", None)
	if not endpoint:
		return True, "no asl_endpoint configured; accepting locally"

	body = json.dumps({"code": code}).encode("utf-8")
	req = Request(
		endpoint,
		data=body,
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	token = getattr(frappe.conf, "asl_token", None)
	if token:
		req.add_header("Authorization", f"Bearer {token}")
	try:
		with urlopen(req, timeout=10) as resp:
			data = json.loads(resp.read().decode("utf-8") or "{}")
	except HTTPError as e:
		return False, f"HTTP {e.code}: {e.reason}"
	except URLError as e:
		return False, f"unreachable: {e.reason}"
	except json.JSONDecodeError:
		return False, "bad response from Asl endpoint"
	if data.get("valid"):
		return True, data.get("message", "verified")
	return False, data.get("message", "rejected by Asl endpoint")


@frappe.whitelist()
def scan_asl_code(parent: str, row_name: str, code: str) -> dict:
	"""Validate and record an Asl Belgisi code on a Stock Entry Detail row.

	Returns {ok, message}. On success, the row's asl_belgisi_code is set
	and persisted. The Stock Entry doc is NOT submitted/recomputed.
	"""
	_require_admin_or_warehouse()
	code = (code or "").strip()
	if not code:
		frappe.throw(_("Code is required"))

	if not _asl_regex().match(code):
		return {"ok": False, "message": _("Code does not match expected format")}

	ok, msg = _verify_with_asl_endpoint(code)
	if not ok:
		return {"ok": False, "message": msg}

	parent_doc = frappe.get_doc("Stock Entry", parent)
	target = next((row for row in parent_doc.items if row.name == row_name), None)
	if target is None:
		frappe.throw(_("Row not found on this Stock Entry"))

	item_flag = frappe.db.get_value("Item", target.item_code, "asl_belgisi_enabled")
	if not item_flag:
		return {"ok": False, "message": _("Item does not require Asl Belgisi")}

	frappe.db.set_value("Stock Entry Detail", row_name, "asl_belgisi_code", code)
	frappe.db.commit()
	return {"ok": True, "message": msg or _("Scanned")}


@frappe.whitelist()
def list_asl_stock_entries(limit: int = 50) -> list[dict]:
	"""List Stock Entries containing items that require Asl Belgisi.

	Returns one row per Stock Entry with scan progress
	(scanned / required). Sorted by most-recently-modified.
	"""
	_require_admin_or_warehouse()
	try:
		limit = max(1, min(int(limit), 200))
	except (TypeError, ValueError):
		limit = 50

	if not frappe.db.has_column("Item", "asl_belgisi_enabled"):
		return []

	rows = frappe.db.sql(
		"""
		SELECT
			se.name              AS stock_entry,
			se.stock_entry_type  AS stock_entry_type,
			se.docstatus         AS docstatus,
			se.posting_date      AS posting_date,
			COUNT(sed.name)                                                       AS required,
			SUM(CASE WHEN COALESCE(sed.asl_belgisi_code, '') <> '' THEN 1 ELSE 0 END) AS scanned
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry`        se   ON se.name = sed.parent
		JOIN `tabItem`               item ON item.name = sed.item_code
		WHERE item.asl_belgisi_enabled = 1
		GROUP BY se.name, se.stock_entry_type, se.docstatus, se.posting_date
		ORDER BY se.modified DESC
		LIMIT %s
		""",
		(limit,),
		as_dict=True,
	)
	return rows or []


# ---------------------------------------------------------------------------
# ARCA payment webhook events
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_arca_events(processed: str | None = None, limit: int = 100) -> list[dict]:
	_require_admin()
	try:
		limit = max(1, min(int(limit), 500))
	except (TypeError, ValueError):
		limit = 100

	filters: dict = {}
	if processed in ("0", "1", 0, 1, False, True):
		filters["processed"] = 1 if str(processed) == "1" else 0

	return frappe.get_all(
		"ARCA Payment Event",
		filters=filters,
		fields=[
			"name",
			"arca_transaction_id",
			"sales_invoice",
			"amount",
			"processed",
			"payment_entry",
			"received_at",
			"creation",
		],
		order_by="creation desc",
		limit=limit,
	)


@frappe.whitelist()
def get_arca_event(name: str) -> dict:
	_require_admin()
	doc = frappe.get_doc("ARCA Payment Event", name)
	payload = None
	if doc.payload:
		try:
			payload = json.loads(doc.payload)
		except json.JSONDecodeError:
			payload = doc.payload
	return {
		"name": doc.name,
		"arca_transaction_id": doc.arca_transaction_id,
		"sales_invoice": doc.sales_invoice,
		"amount": float(doc.amount) if doc.amount else 0.0,
		"processed": bool(doc.processed),
		"payment_entry": doc.payment_entry,
		"received_at": doc.received_at.isoformat() if doc.received_at else None,
		"payload": payload,
	}


@frappe.whitelist()
def get_asl_stock_entry_rows(stock_entry: str) -> list[dict]:
	"""Return the rows of a Stock Entry that require Asl Belgisi scans."""
	_require_admin_or_warehouse()
	if not frappe.db.has_column("Stock Entry Detail", "asl_belgisi_code"):
		return []
	return frappe.db.sql(
		"""
		SELECT
			sed.name              AS row_name,
			sed.item_code         AS item_code,
			sed.item_name         AS item_name,
			sed.qty               AS qty,
			sed.asl_belgisi_code  AS asl_belgisi_code
		FROM `tabStock Entry Detail` sed
		JOIN `tabItem`               item ON item.name = sed.item_code
		WHERE sed.parent = %s
		  AND item.asl_belgisi_enabled = 1
		ORDER BY sed.idx
		""",
		(stock_entry,),
		as_dict=True,
	) or []
