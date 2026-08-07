"""Shared engine for the Uzbek POS payment gateways.

Everything provider-agnostic lives here: configuration access, the
company+mode -> provider lookup, session creation, dynamic-QR rendering, and
the "finalize a paid session into a POS Sales Invoice" routine. The per-
provider modules (payme / click / uzum) only translate each provider's wire
protocol into calls against these helpers.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime

SESSION_DT = "POS Payment Session"
PROVIDERS = ("Payme", "Click", "Uzum Bank")

# Public, well-known checkout bases.
PAYME_CHECKOUT_PROD = "https://checkout.paycom.uz"
PAYME_CHECKOUT_TEST = "https://checkout.test.paycom.uz"
CLICK_PAY_BASE = "https://my.click.uz/services/pay"


# ---------------------------------------------------------------------------
# configuration (secrets always come from site_config.json / frappe.conf)
# ---------------------------------------------------------------------------
def conf(key: str, default: Any = None) -> Any:
	return getattr(frappe.conf, key, default)


def require_conf(key: str) -> str:
	val = conf(key)
	if val in (None, ""):
		frappe.throw(_("Missing site config key: {0}").format(key))
	return str(val)


def session_ttl_minutes() -> int:
	val = frappe.db.get_single_value("Stabler Settings", "pos_session_ttl_minutes")
	try:
		return int(val) if val else 15
	except (TypeError, ValueError):
		return 15


# ---------------------------------------------------------------------------
# gateway resolution: which provider backs a (company, mode_of_payment)?
# ---------------------------------------------------------------------------
def gateway_for(company: str, mode_of_payment: str) -> str | None:
	"""Return the provider for a POS payment mode, or None if it is not an
	online gateway (i.e. a plain cash/card mode)."""
	if not (company and mode_of_payment):
		return None
	rows = frappe.get_all(
		"Stabler POS Gateway",
		filters={
			"parent": "Stabler Settings",
			"parenttype": "Stabler Settings",
			"company": company,
			"mode_of_payment": mode_of_payment,
			"enabled": 1,
		},
		fields=["provider"],
		limit=1,
	)
	return rows[0].provider if rows else None


def gateways_for_company(company: str) -> dict[str, str]:
	"""Map of mode_of_payment -> provider for a company (enabled only)."""
	rows = frappe.get_all(
		"Stabler POS Gateway",
		filters={
			"parent": "Stabler Settings",
			"parenttype": "Stabler Settings",
			"company": company,
			"enabled": 1,
		},
		fields=["mode_of_payment", "provider"],
	)
	return {r.mode_of_payment: r.provider for r in rows}


# ---------------------------------------------------------------------------
# amount helpers
# ---------------------------------------------------------------------------
def to_tiyin(amount_uzs: float) -> int:
	"""Payme/Uzum settle in tiyin (1 UZS = 100 tiyin)."""
	return round(flt(amount_uzs) * 100)


def from_tiyin(amount_tiyin: float) -> float:
	return flt(amount_tiyin) / 100.0


def epoch_ms() -> int:
	return int(datetime.now().timestamp() * 1000)


# ---------------------------------------------------------------------------
# session lifecycle
# ---------------------------------------------------------------------------
def new_order_id(provider: str) -> str:
	prefix = {"Payme": "PME", "Click": "CLK", "Uzum Bank": "UZM"}.get(provider, "POS")
	return f"{prefix}-{datetime.now():%Y%m%d}-{secrets.token_hex(5).upper()}"


def create_session(
	*,
	provider: str,
	company: str,
	pos_profile: str,
	payment_mode: str,
	amount: float,
	currency: str,
	cart: list[dict],
) -> "frappe.Document":
	doc = frappe.new_doc(SESSION_DT)
	doc.provider = provider
	doc.status = "Pending"
	doc.company = company
	doc.pos_profile = pos_profile
	doc.payment_mode = payment_mode
	doc.order_id = new_order_id(provider)
	doc.amount = flt(amount)
	doc.currency = currency
	doc.created_at = now_datetime()
	doc.expires_at = add_to_date(now_datetime(), minutes=session_ttl_minutes())
	doc.cart_snapshot = json.dumps(cart, ensure_ascii=False)
	doc.insert(ignore_permissions=True)
	return doc


def get_session_by_order(order_id: str, *, for_update: bool = False) -> "frappe.Document | None":
	name = frappe.db.get_value(SESSION_DT, {"order_id": order_id}, "name")
	if not name:
		return None
	if for_update:
		# row-lock so concurrent webhook retries serialize on this session
		frappe.db.get_value(SESSION_DT, name, "status", for_update=True)
	return frappe.get_doc(SESSION_DT, name)


def log_to_session(doc: "frappe.Document", label: str, payload: Any) -> None:
	stamp = datetime.now().isoformat(timespec="seconds")
	try:
		body = json.dumps(payload, ensure_ascii=False, default=str)
	except (TypeError, ValueError):
		body = str(payload)
	entry = f"# {stamp} {label}\n{body}\n"
	doc.payload = (doc.payload or "") + entry


def mark_cancelled(doc, *, state: int | None = None, reason: int | None = None) -> None:
	doc.status = "Cancelled"
	if state is not None:
		doc.provider_state = state
	if reason is not None:
		doc.cancel_reason = reason
	doc.cancel_time_ms = epoch_ms()
	doc.save(ignore_permissions=True)


def is_expired(doc) -> bool:
	if doc.status != "Pending":
		return False
	return bool(doc.expires_at and now_datetime() > doc.expires_at)


# ---------------------------------------------------------------------------
# finalize: paid session -> POS Sales Invoice (idempotent)
# ---------------------------------------------------------------------------
def finalize_session_to_invoice(doc, *, provider_trans_id: str, state: int | None = None) -> str:
	"""Materialize the POS Sales Invoice for a confirmed payment and mark the
	session Paid. Safe to call more than once: returns the existing invoice if
	the session is already finalized."""
	if doc.status == "Paid" and doc.sales_invoice:
		return doc.sales_invoice

	cart = json.loads(doc.cart_snapshot or "[]")
	if not cart:
		frappe.throw(_("Session {0} has no cart snapshot.").format(doc.name))

	# Build + submit a fully-paid POS invoice using the shared POS builder so
	# stock decrement, pricing and GL posting match the cash path exactly.
	from stabler.api.pos import build_paid_pos_invoice

	invoice = build_paid_pos_invoice(
		company=doc.company,
		pos_profile=doc.pos_profile,
		items=cart,
		payment_mode=doc.payment_mode,
	)

	doc.sales_invoice = invoice.name
	doc.status = "Paid"
	doc.paid_at = now_datetime()
	doc.provider_trans_id = provider_trans_id
	if state is not None:
		doc.provider_state = state
	doc.perform_time_ms = epoch_ms()
	doc.save(ignore_permissions=True)
	return invoice.name


# ---------------------------------------------------------------------------
# dynamic QR rendering (SVG, no Pillow dependency; graceful fallback)
# ---------------------------------------------------------------------------
def qr_svg_data_uri(text: str) -> str | None:
	"""Render `text` as an SVG QR code and return it as a data: URI, or None
	if the qrcode package is unavailable (the SPA then shows the raw link)."""
	try:
		import qrcode
		import qrcode.image.svg

		img = qrcode.make(
			text,
			image_factory=qrcode.image.svg.SvgPathImage,
			box_size=10,
			border=2,
			error_correction=qrcode.constants.ERROR_CORRECT_M,
		)
		import io

		buf = io.BytesIO()
		img.save(buf)
		svg = buf.getvalue()
		b64 = base64.b64encode(svg).decode("ascii")
		return f"data:image/svg+xml;base64,{b64}"
	except Exception:  # QR is a convenience; never break checkout
		frappe.log_error(frappe.get_traceback(), "uzpay: QR render failed")
		return None


# ---------------------------------------------------------------------------
# raw request helpers (webhooks)
# ---------------------------------------------------------------------------
def raw_body() -> bytes:
	req = getattr(frappe, "request", None)
	if req is None:
		return b""
	return req.get_data(cache=True, as_text=False) or b""


def json_body() -> dict[str, Any]:
	try:
		return json.loads(raw_body().decode("utf-8") or "{}")
	except (UnicodeDecodeError, json.JSONDecodeError):
		return {}
