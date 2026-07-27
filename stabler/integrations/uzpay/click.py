"""Click Merchant (SHOP API) webhook — Prepare + Complete.

Click posts form-encoded requests to a single endpoint and distinguishes the
stage by `action` (0 = Prepare, 1 = Complete). Each request carries an MD5
`sign_string` we re-derive with the merchant SECRET_KEY.

  Prepare  (action 0): validate order + amount, reserve the transaction
  Complete (action 1): money captured -> finalize the POS invoice

Endpoint: POST /api/method/stabler.integrations.uzpay.click.merchant_endpoint

Config (site_config.json):
  click_service_id        service id
  click_merchant_id       merchant id (for the pay link)
  click_secret_key        SECRET_KEY used in the MD5 signature
  click_merchant_user_id  merchant user id (for the pay link)
"""

from __future__ import annotations

import hashlib
import hmac

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import flt

from stabler.integrations.uzpay import common as C

# Click response error codes
OK = 0
ERR_SIGN = -1
ERR_AMOUNT = -2
ERR_ACTION = -3
ERR_ALREADY_PAID = -4
ERR_NO_ORDER = -5
ERR_NO_TX = -6
ERR_CANCELLED = -9


def _form() -> dict:
	# Click sends application/x-www-form-urlencoded; values arrive as strings,
	# which is exactly what the MD5 signature needs.
	return dict(frappe.local.form_dict)


def _secret() -> str:
	return C.require_conf("click_secret_key")


def _verify_prepare_sign(f: dict) -> bool:
	raw = (
		f.get("click_trans_id", "")
		+ f.get("service_id", "")
		+ _secret()
		+ f.get("merchant_trans_id", "")
		+ f.get("amount", "")
		+ f.get("action", "")
		+ f.get("sign_time", "")
	)
	expected = hashlib.md5(raw.encode("utf-8")).hexdigest()
	provided = (f.get("sign_string") or "").lower()
	return hmac.compare_digest(expected, provided)


def _verify_complete_sign(f: dict) -> bool:
	raw = (
		f.get("click_trans_id", "")
		+ f.get("service_id", "")
		+ _secret()
		+ f.get("merchant_trans_id", "")
		+ f.get("merchant_prepare_id", "")
		+ f.get("amount", "")
		+ f.get("action", "")
		+ f.get("sign_time", "")
	)
	expected = hashlib.md5(raw.encode("utf-8")).hexdigest()
	provided = (f.get("sign_string") or "").lower()
	return hmac.compare_digest(expected, provided)


def _err(f: dict, code: int, note: str, **extra) -> dict:
	out = {
		"click_trans_id": f.get("click_trans_id"),
		"merchant_trans_id": f.get("merchant_trans_id"),
		"error": code,
		"error_note": note,
	}
	out.update(extra)
	return out


def _prepare(f: dict) -> dict:
	if not _verify_prepare_sign(f):
		return _err(f, ERR_SIGN, "SIGN CHECK FAILED")

	doc = C.get_session_by_order((f.get("merchant_trans_id") or "").strip(), for_update=True)
	if not doc or doc.provider != "Click":
		return _err(f, ERR_NO_ORDER, "Order not found")
	if doc.status == "Paid":
		return _err(f, ERR_ALREADY_PAID, "Already paid")
	if doc.status in ("Cancelled", "Failed", "Expired") or C.is_expired(doc):
		return _err(f, ERR_CANCELLED, "Transaction cancelled")
	if flt(f.get("amount")) != flt(doc.amount):
		return _err(f, ERR_AMOUNT, "Incorrect parameter amount")

	doc.provider_trans_id = (f.get("click_trans_id") or "").strip()
	doc.provider_state = 1
	doc.create_time_ms = C.epoch_ms()
	C.log_to_session(doc, "Click.Prepare", f)
	doc.save(ignore_permissions=True)

	# We use click_trans_id as the merchant_prepare_id and echo it on Complete.
	return _err(
		f,
		OK,
		"Success",
		merchant_prepare_id=doc.provider_trans_id,
	)


def _complete(f: dict) -> dict:
	if not _verify_complete_sign(f):
		return _err(f, ERR_SIGN, "SIGN CHECK FAILED")

	doc = C.get_session_by_order((f.get("merchant_trans_id") or "").strip(), for_update=True)
	if not doc or doc.provider != "Click":
		return _err(f, ERR_NO_ORDER, "Order not found")

	click_trans_id = (f.get("click_trans_id") or "").strip()
	prepare_id = (f.get("merchant_prepare_id") or "").strip()
	if doc.provider_trans_id != click_trans_id or prepare_id != doc.provider_trans_id:
		return _err(f, ERR_NO_TX, "Transaction does not exist")

	# Idempotent: already finalized.
	if doc.status == "Paid":
		return _err(f, OK, "Success", merchant_confirm_id=doc.sales_invoice)

	# Click signalled a capture failure / cancellation on its side.
	if int(f.get("error") or 0) < 0:
		C.log_to_session(doc, "Click.Complete(cancel)", f)
		C.mark_cancelled(doc, state=-1)
		return _err(f, ERR_CANCELLED, "Transaction cancelled")

	if flt(f.get("amount")) != flt(doc.amount):
		return _err(f, ERR_AMOUNT, "Incorrect parameter amount")

	C.log_to_session(doc, "Click.Complete", f)
	invoice = C.finalize_session_to_invoice(doc, provider_trans_id=click_trans_id, state=2)
	return _err(f, OK, "Success", merchant_confirm_id=invoice)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=600, seconds=60)
def merchant_endpoint() -> dict:
	frappe.local.response["type"] = "json"
	f = _form()
	try:
		action = (f.get("action") or "").strip()
		if action == "0":
			result = _prepare(f)
		elif action == "1":
			result = _complete(f)
		else:
			result = _err(f, ERR_ACTION, "Action not found")
		frappe.db.commit()
		return result
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "uzpay.click: unhandled")
		return _err(f, ERR_NO_TX, f"Internal error: {e}")


# ---------------------------------------------------------------------------
# checkout link / QR (called from the POS API, not the webhook)
# ---------------------------------------------------------------------------
def build_checkout_url(doc) -> str:
	from urllib.parse import urlencode

	query = urlencode(
		{
			"service_id": C.require_conf("click_service_id"),
			"merchant_id": C.require_conf("click_merchant_id"),
			"amount": f"{flt(doc.amount):.2f}",
			"transaction_param": doc.order_id,
		}
	)
	return f"{C.CLICK_PAY_BASE}?{query}"
