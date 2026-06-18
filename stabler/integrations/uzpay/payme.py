"""Payme (Paycom) Merchant API — JSON-RPC 2.0 webhook.

Payme Business calls this endpoint with named-parameter JSON-RPC requests over
HTTPS, authenticated with HTTP Basic ("Paycom:<merchant key>"). We implement
the full transaction state machine against a POS Payment Session:

  CheckPerformTransaction  -> may this order be paid?
  CreateTransaction        -> reserve a Payme transaction for the order
  PerformTransaction       -> money captured: finalize the POS invoice
  CancelTransaction        -> void/refund
  CheckTransaction         -> report current state
  GetStatement             -> reconcile a time range

Endpoint: POST /api/method/stabler.integrations.uzpay.payme.merchant_endpoint

Config (site_config.json):
  payme_merchant_id      cabinet merchant id (for the checkout link)
  payme_key              production merchant key (Basic-auth password)
  payme_test_key         test/sandbox key
  payme_test_mode        1 to use the test key + test checkout host
  payme_account_field    account field configured in the cabinet (default "order_id")
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import frappe
from frappe.rate_limiter import rate_limit

from stabler.integrations.uzpay import common as C

# Payme JSON-RPC error codes
ERR_AUTH = -32504
ERR_PARSE = -32700
ERR_METHOD = -32601
ERR_INVALID_AMOUNT = -31001
ERR_ACCOUNT = -31050  # order not found / invalid account
ERR_CANT_PERFORM = -31008
ERR_TX_NOT_FOUND = -31003
ERR_CANT_CANCEL = -31007


class PaymeError(Exception):
	def __init__(self, code: int, message: str, data: Any = None):
		super().__init__(message)
		self.code = code
		self.message = message
		self.data = data


def _msg(text_en: str) -> dict:
	return {"ru": text_en, "uz": text_en, "en": text_en}


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
def _merchant_key() -> str:
	if C.conf("payme_test_mode"):
		return C.require_conf("payme_test_key")
	return C.require_conf("payme_key")


def _check_auth() -> None:
	header = frappe.get_request_header("Authorization") or ""
	if not header.startswith("Basic "):
		raise PaymeError(ERR_AUTH, "Insufficient privilege to perform this method.")
	try:
		decoded = base64.b64decode(header[6:]).decode("utf-8")
	except (binascii.Error, UnicodeDecodeError):
		raise PaymeError(ERR_AUTH, "Insufficient privilege to perform this method.")
	_, _, password = decoded.partition(":")
	if not password or password != _merchant_key():
		raise PaymeError(ERR_AUTH, "Insufficient privilege to perform this method.")


def _account_field() -> str:
	return C.conf("payme_account_field", "order_id")


def _session_from_account(params: dict, *, for_update: bool = False):
	account = params.get("account") or {}
	order_id = (account.get(_account_field()) or "").strip()
	if not order_id:
		raise PaymeError(ERR_ACCOUNT, "Order not found.", data=_account_field())
	doc = C.get_session_by_order(order_id, for_update=for_update)
	if not doc or doc.provider != "Payme":
		raise PaymeError(ERR_ACCOUNT, "Order not found.", data=_account_field())
	return doc


def _validate_amount(doc, params: dict) -> None:
	expected = C.to_tiyin(doc.amount)
	if int(params.get("amount") or 0) != expected:
		raise PaymeError(ERR_INVALID_AMOUNT, "Incorrect amount.", data="amount")


# ---------------------------------------------------------------------------
# methods
# ---------------------------------------------------------------------------
def _check_perform(params: dict) -> dict:
	doc = _session_from_account(params)
	_validate_amount(doc, params)
	if C.is_expired(doc):
		raise PaymeError(ERR_ACCOUNT, "Order expired.", data=_account_field())
	if doc.status not in ("Pending",):
		# already paid or cancelled — not available for a new transaction
		raise PaymeError(ERR_CANT_PERFORM, "Order is not available for payment.")
	return {"allow": True}


def _create_transaction(params: dict) -> dict:
	doc = _session_from_account(params, for_update=True)
	_validate_amount(doc, params)
	tx_id = (params.get("id") or "").strip()

	if doc.provider_trans_id:
		# idempotent replay of the same transaction
		if doc.provider_trans_id == tx_id and doc.provider_state == 1:
			return {
				"create_time": int(doc.create_time_ms or 0),
				"transaction": doc.name,
				"state": 1,
			}
		# a different Payme transaction already owns this order
		raise PaymeError(ERR_CANT_PERFORM, "Another transaction is in progress for this order.")

	if C.is_expired(doc):
		raise PaymeError(ERR_ACCOUNT, "Order expired.", data=_account_field())
	if doc.status != "Pending":
		raise PaymeError(ERR_CANT_PERFORM, "Order is not available for payment.")

	doc.provider_trans_id = tx_id
	doc.provider_state = 1
	doc.create_time_ms = int(params.get("time") or C.epoch_ms())
	C.log_to_session(doc, "CreateTransaction", params)
	doc.save(ignore_permissions=True)
	return {"create_time": int(doc.create_time_ms or 0), "transaction": doc.name, "state": 1}


def _find_by_tx(tx_id: str, *, for_update: bool = False):
	name = frappe.db.get_value(
		C.SESSION_DT, {"provider_trans_id": tx_id, "provider": "Payme"}, "name"
	)
	if not name:
		raise PaymeError(ERR_TX_NOT_FOUND, "Transaction not found.")
	if for_update:
		frappe.db.get_value(C.SESSION_DT, name, "status", for_update=True)
	return frappe.get_doc(C.SESSION_DT, name)


def _perform_transaction(params: dict) -> dict:
	doc = _find_by_tx((params.get("id") or "").strip(), for_update=True)
	if doc.provider_state == 2:
		return {
			"transaction": doc.name,
			"perform_time": int(doc.perform_time_ms or 0),
			"state": 2,
		}
	if doc.provider_state != 1:
		raise PaymeError(ERR_CANT_PERFORM, "Transaction cannot be performed.")

	C.log_to_session(doc, "PerformTransaction", params)
	C.finalize_session_to_invoice(doc, provider_trans_id=doc.provider_trans_id, state=2)
	return {
		"transaction": doc.name,
		"perform_time": int(doc.perform_time_ms or C.epoch_ms()),
		"state": 2,
	}


def _cancel_transaction(params: dict) -> dict:
	doc = _find_by_tx((params.get("id") or "").strip(), for_update=True)
	reason = params.get("reason")

	if doc.provider_state in (-1, -2):
		return {
			"transaction": doc.name,
			"cancel_time": int(doc.cancel_time_ms or 0),
			"state": doc.provider_state,
		}

	if doc.provider_state == 2:
		# performed -> refund: reverse the linked invoice if possible
		_reverse_invoice(doc)
		new_state = -2
	else:
		new_state = -1

	C.log_to_session(doc, "CancelTransaction", params)
	C.mark_cancelled(doc, state=new_state, reason=int(reason) if reason is not None else None)
	return {
		"transaction": doc.name,
		"cancel_time": int(doc.cancel_time_ms or 0),
		"state": new_state,
	}


def _reverse_invoice(doc) -> None:
	if not doc.sales_invoice:
		return
	try:
		inv = frappe.get_doc("Sales Invoice", doc.sales_invoice)
		if inv.docstatus == 1:
			inv.cancel()
	except Exception:  # noqa: BLE001
		frappe.log_error(frappe.get_traceback(), "uzpay.payme: invoice reversal failed")


def _check_transaction(params: dict) -> dict:
	doc = _find_by_tx((params.get("id") or "").strip())
	return {
		"create_time": int(doc.create_time_ms or 0),
		"perform_time": int(doc.perform_time_ms or 0),
		"cancel_time": int(doc.cancel_time_ms or 0),
		"transaction": doc.name,
		"state": int(doc.provider_state or 0),
		"reason": int(doc.cancel_reason) if doc.cancel_reason else None,
	}


def _get_statement(params: dict) -> dict:
	frm = int(params.get("from") or 0)
	to = int(params.get("to") or 0)
	rows = frappe.get_all(
		C.SESSION_DT,
		filters={
			"provider": "Payme",
			"provider_trans_id": ["is", "set"],
			"create_time_ms": ["between", [frm, to]],
		},
		fields=[
			"name", "order_id", "amount", "provider_trans_id", "provider_state",
			"create_time_ms", "perform_time_ms", "cancel_time_ms", "cancel_reason",
		],
	)
	transactions = []
	for r in rows:
		transactions.append(
			{
				"id": r.provider_trans_id,
				"time": int(r.create_time_ms or 0),
				"amount": C.to_tiyin(r.amount),
				"account": {_account_field(): r.order_id},
				"create_time": int(r.create_time_ms or 0),
				"perform_time": int(r.perform_time_ms or 0),
				"cancel_time": int(r.cancel_time_ms or 0),
				"transaction": r.name,
				"state": int(r.provider_state or 0),
				"reason": int(r.cancel_reason) if r.cancel_reason else None,
			}
		)
	return {"transactions": transactions}


_DISPATCH = {
	"CheckPerformTransaction": _check_perform,
	"CreateTransaction": _create_transaction,
	"PerformTransaction": _perform_transaction,
	"CancelTransaction": _cancel_transaction,
	"CheckTransaction": _check_transaction,
	"GetStatement": _get_statement,
}


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
@rate_limit(limit=600, seconds=60)
def merchant_endpoint() -> dict:
	frappe.local.response["type"] = "json"
	body = C.json_body()
	req_id = body.get("id")
	try:
		_check_auth()
		method = body.get("method")
		handler = _DISPATCH.get(method)
		if not handler:
			raise PaymeError(ERR_METHOD, f"Method not found: {method}")
		params = body.get("params") or {}
		result = handler(params)
		frappe.db.commit()
		return {"jsonrpc": "2.0", "id": req_id, "result": result}
	except PaymeError as e:
		frappe.db.rollback()
		err = {"code": e.code, "message": _msg(e.message)}
		if e.data is not None:
			err["data"] = e.data
		return {"jsonrpc": "2.0", "id": req_id, "error": err}
	except Exception as e:  # noqa: BLE001
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "uzpay.payme: unhandled")
		return {
			"jsonrpc": "2.0",
			"id": req_id,
			"error": {"code": -32400, "message": _msg(str(e))},
		}


# ---------------------------------------------------------------------------
# checkout link / QR (called from the POS API, not the webhook)
# ---------------------------------------------------------------------------
def build_checkout_url(doc) -> str:
	merchant = C.require_conf("payme_merchant_id")
	field = _account_field()
	params = f"m={merchant};ac.{field}={doc.order_id};a={C.to_tiyin(doc.amount)};l=uz"
	encoded = base64.b64encode(params.encode("utf-8")).decode("ascii")
	base = C.PAYME_CHECKOUT_TEST if C.conf("payme_test_mode") else C.PAYME_CHECKOUT_PROD
	return f"{base}/{encoded}"
