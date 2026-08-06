"""Uzum Bank (Apelsin) merchant webhook — check / create / confirm / reverse / status.

Uzum posts JSON over HTTPS with HTTP Basic auth (merchant username/password)
and distinguishes the operation either by a body field (`operation` / `method`)
or by the trailing URL segment. Because Uzum issues the exact field names and
checkout deep-link per merchant, the wire-field mapping here is config-driven
(uzum_* keys) so it can be aligned to your cabinet without code changes.

Endpoint: POST /api/method/stabler.integrations.uzpay.uzum.merchant_endpoint
  (also reachable as .../uzum.merchant_endpoint/check etc. if Uzum routes by path)

Config (site_config.json):
  uzum_service_id          service id
  uzum_merchant_username    Basic-auth username
  uzum_merchant_password    Basic-auth password
  uzum_order_field          body field carrying our order id   (default "orderId")
  uzum_transid_field        body field carrying Uzum's tx id   (default "transId")
  uzum_amount_field         body field carrying the amount     (default "amount")
  uzum_amount_in_tiyin      1 if the amount arrives in tiyin   (default 1)
  uzum_checkout_template    deep-link template with {service_id}{order_id}{amount}{amount_tiyin}
"""

from __future__ import annotations

import base64
import binascii
import hmac

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import flt

from stabler.integrations.uzpay import common as C

OK = "OK"
FAILED = "FAILED"

# error codes
E_OK = 0
E_AUTH = 401
E_NO_ORDER = 10
E_BAD_AMOUNT = 11
E_NO_TX = 12
E_NOT_PAYABLE = 13


class UzumError(Exception):
	def __init__(self, code: int, message: str):
		super().__init__(message)
		self.code = code
		self.message = message


def _f(key: str, default: str) -> str:
	return C.conf(key, default)


def _check_auth() -> None:
	header = frappe.get_request_header("Authorization") or ""
	if not header.startswith("Basic "):
		raise UzumError(E_AUTH, "Unauthorized")
	try:
		decoded = base64.b64decode(header[6:]).decode("utf-8")
	except binascii.Error, UnicodeDecodeError:
		raise UzumError(E_AUTH, "Unauthorized")
	user, _, pwd = decoded.partition(":")
	user_ok = hmac.compare_digest(user, C.require_conf("uzum_merchant_username"))
	pwd_ok = hmac.compare_digest(pwd, C.require_conf("uzum_merchant_password"))
	if not (user_ok and pwd_ok):
		raise UzumError(E_AUTH, "Unauthorized")


def _order_id(body: dict) -> str:
	params = body.get("params") if isinstance(body.get("params"), dict) else {}
	field = _f("uzum_order_field", "orderId")
	return str(body.get(field) or params.get(field) or "").strip()


def _trans_id(body: dict) -> str:
	field = _f("uzum_transid_field", "transId")
	return str(body.get(field) or "").strip()


def _amount_uzs(body: dict) -> float:
	field = _f("uzum_amount_field", "amount")
	raw = flt(body.get(field) or 0)
	if C.conf("uzum_amount_in_tiyin", 1):
		return C.from_tiyin(raw)
	return raw


def _session(body: dict, *, for_update: bool = False):
	doc = C.get_session_by_order(_order_id(body), for_update=for_update)
	if not doc or doc.provider != "Uzum Bank":
		raise UzumError(E_NO_ORDER, "Order not found")
	return doc


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------
def _check(body: dict) -> dict:
	doc = _session(body)
	if doc.status == "Paid":
		raise UzumError(E_NOT_PAYABLE, "Already paid")
	if doc.status != "Pending" or C.is_expired(doc):
		raise UzumError(E_NOT_PAYABLE, "Order not payable")
	if _order_has_amount(body) and round(_amount_uzs(body), 2) != round(flt(doc.amount), 2):
		raise UzumError(E_BAD_AMOUNT, "Incorrect amount")
	return {"orderId": doc.order_id, "amount": C.to_tiyin(doc.amount)}


def _order_has_amount(body: dict) -> bool:
	field = _f("uzum_amount_field", "amount")
	params = body.get("params") if isinstance(body.get("params"), dict) else {}
	return field in body or field in params


def _create(body: dict) -> dict:
	doc = _session(body, for_update=True)
	if doc.status == "Paid":
		raise UzumError(E_NOT_PAYABLE, "Already paid")
	if doc.status != "Pending" or C.is_expired(doc):
		raise UzumError(E_NOT_PAYABLE, "Order not payable")
	if round(_amount_uzs(body), 2) != round(flt(doc.amount), 2):
		raise UzumError(E_BAD_AMOUNT, "Incorrect amount")

	doc.provider_trans_id = _trans_id(body) or doc.provider_trans_id
	doc.provider_state = 1
	doc.create_time_ms = C.epoch_ms()
	C.log_to_session(doc, "Uzum.create", body)
	doc.save(ignore_permissions=True)
	return {"transId": doc.provider_trans_id, "orderId": doc.order_id, "status": "CREATED"}


def _find_by_tx(body: dict, *, for_update: bool = False):
	tx = _trans_id(body)
	name = frappe.db.get_value(C.SESSION_DT, {"provider_trans_id": tx, "provider": "Uzum Bank"}, "name")
	if not name:
		raise UzumError(E_NO_TX, "Transaction not found")
	if for_update:
		frappe.db.get_value(C.SESSION_DT, name, "status", for_update=True)
	return frappe.get_doc(C.SESSION_DT, name)


def _confirm(body: dict) -> dict:
	doc = _find_by_tx(body, for_update=True)
	if doc.status == "Paid":
		return {"transId": doc.provider_trans_id, "status": "CONFIRMED", "invoice": doc.sales_invoice}
	if doc.provider_state != 1:
		raise UzumError(E_NOT_PAYABLE, "Transaction not confirmable")
	C.log_to_session(doc, "Uzum.confirm", body)
	invoice = C.finalize_session_to_invoice(doc, provider_trans_id=doc.provider_trans_id, state=2)
	return {"transId": doc.provider_trans_id, "status": "CONFIRMED", "invoice": invoice}


def _reverse(body: dict) -> dict:
	doc = _find_by_tx(body, for_update=True)
	if doc.status == "Cancelled":
		return {"transId": doc.provider_trans_id, "status": "REVERSED"}
	if doc.status == "Paid" and doc.sales_invoice:
		try:
			inv = frappe.get_doc("Sales Invoice", doc.sales_invoice)
			if inv.docstatus == 1:
				inv.cancel()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "uzpay.uzum: reversal failed")
	C.log_to_session(doc, "Uzum.reverse", body)
	C.mark_cancelled(doc, state=-2)
	return {"transId": doc.provider_trans_id, "status": "REVERSED"}


def _status(body: dict) -> dict:
	doc = _find_by_tx(body)
	mapping = {1: "CREATED", 2: "CONFIRMED", -1: "REVERSED", -2: "REVERSED"}
	return {
		"transId": doc.provider_trans_id,
		"orderId": doc.order_id,
		"status": mapping.get(int(doc.provider_state or 0), "UNKNOWN"),
		"sessionStatus": doc.status,
	}


_DISPATCH = {
	"check": _check,
	"create": _create,
	"confirm": _confirm,
	"reverse": _reverse,
	"status": _status,
}


def _operation(body: dict) -> str:
	op = (body.get("operation") or body.get("method") or "").strip().lower()
	if op:
		return op
	# fall back to trailing path segment, e.g. .../merchant_endpoint/confirm
	path = (frappe.local.request.path if getattr(frappe.local, "request", None) else "") or ""
	tail = path.rstrip("/").rsplit("/", 1)[-1].lower()
	return tail if tail in _DISPATCH else ""


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
@rate_limit(limit=600, seconds=60)
def merchant_endpoint() -> dict:
	frappe.local.response["type"] = "json"
	body = C.json_body()
	envelope = {
		"serviceId": C.conf("uzum_service_id"),
		"timestamp": C.epoch_ms(),
	}
	try:
		_check_auth()
		handler = _DISPATCH.get(_operation(body))
		if not handler:
			raise UzumError(E_NO_TX, "Unknown operation")
		data = handler(body)
		frappe.db.commit()
		return {**envelope, "status": OK, "errorCode": E_OK, "data": data}
	except UzumError as e:
		frappe.db.rollback()
		return {**envelope, "status": FAILED, "errorCode": e.code, "errorMessage": e.message}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "uzpay.uzum: unhandled")
		return {**envelope, "status": FAILED, "errorCode": -1, "errorMessage": str(e)}


# ---------------------------------------------------------------------------
# checkout link / QR (called from the POS API, not the webhook)
# ---------------------------------------------------------------------------
def build_checkout_url(doc) -> str:
	template = C.conf(
		"uzum_checkout_template",
		"https://www.uzumbank.uz/open-service?serviceId={service_id}&orderId={order_id}&amount={amount_tiyin}",
	)
	return template.format(
		service_id=C.require_conf("uzum_service_id"),
		order_id=doc.order_id,
		amount=f"{flt(doc.amount):.2f}",
		amount_tiyin=C.to_tiyin(doc.amount),
	)
