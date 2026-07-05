"""Retail POS API — shop-warehouse checkout using ERPNext POS Sales Invoice."""

from __future__ import annotations

import frappe
from stabler.api.approvals import _assert_company_scope
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._common import _require_company
from stabler.api.sales import _lookup_item_price, _resolve_price_list


def _validation_error(message: str) -> None:
	raise frappe.ValidationError(message)


def _normalize_cart_items(items) -> list[dict]:
	if isinstance(items, str):
		items = frappe.parse_json(items) or []
	if not isinstance(items, list) or not items:
		_validation_error("Cart is empty.")

	merged: dict[str, float] = {}
	for raw in items:
		if not isinstance(raw, dict):
			_validation_error("Invalid cart line.")
		item_code = (raw.get("item_code") or "").strip()
		qty = flt(raw.get("qty"))
		if not item_code:
			_validation_error("Item code is required.")
		if qty <= 0:
			_validation_error(f"Quantity must be greater than zero for {item_code}.")
		merged[item_code] = flt(merged.get(item_code, 0) + qty)

	return [{"item_code": item_code, "qty": qty} for item_code, qty in merged.items()]


def _assert_cart_available(items: list[dict], availability: dict[str, float]) -> None:
	for item in items:
		item_code = item["item_code"]
		requested = flt(item["qty"])
		available = flt(availability.get(item_code, 0))
		if requested > available:
			_validation_error(
				f"Insufficient shop stock for {item_code}. Available: {available}, requested: {requested}.",
			)


def _pos_profile_doc(company: str, pos_profile: str):
	_require_company(company)
	if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
		frappe.throw(_("Unknown POS Profile: {0}").format(pos_profile or ""), frappe.DoesNotExistError)
	doc = frappe.get_doc("POS Profile", pos_profile)
	if doc.company != company:
		frappe.throw(_("POS Profile belongs to a different company."), frappe.PermissionError)
	# Entitlement gate (multi-tenant): _require_company only checks existence.
	# Verify the caller is actually allowed this company, and — when the POS
	# Profile restricts users via `tabPOS Profile User` — that the caller is a
	# member. Admins / unrestricted users (empty allowed list) bypass, mirroring
	# the company-match-only path used by list_pos_profiles for unrestricted
	# profiles.
	from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

	user = frappe.session.user
	is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
	if not is_admin:
		allowed = _user_allowed_companies(user)
		if allowed and company not in allowed:
			frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
		# If the profile has an explicit user list, the caller must be on it.
		has_user_list = frappe.db.exists("POS Profile User", {"parent": pos_profile})
		if has_user_list and not frappe.db.exists(
			"POS Profile User", {"parent": pos_profile, "user": user}
		):
			frappe.throw(_("You are not assigned to this POS Profile."), frappe.PermissionError)
	if doc.disabled:
		frappe.throw(_("POS Profile is disabled."), frappe.ValidationError)
	if not doc.customer:
		frappe.throw(_("POS Profile must define a walk-in customer."), frappe.ValidationError)
	if not doc.warehouse:
		frappe.throw(_("POS Profile must define a shop warehouse."), frappe.ValidationError)
	if not doc.payments:
		frappe.throw(_("POS Profile must define at least one payment mode."), frappe.ValidationError)
	return doc


def _payment_account(mode_of_payment: str, company: str) -> str:
	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not account:
		frappe.throw(
			_("Mode of Payment {0} has no default account for company {1}.").format(mode_of_payment, company),
			frappe.ValidationError,
		)
	return account


def _profile_payload(doc) -> dict:
	from stabler.integrations.uzpay.common import gateways_for_company

	gateways = gateways_for_company(doc.company)
	payments = []
	default_mode = ""
	for row in doc.payments:
		mode = row.mode_of_payment
		if not mode:
			continue
		payments.append(
			{
				"mode_of_payment": mode,
				"default": int(row.default or 0),
				"account": _payment_account(mode, doc.company),
				# Provider name when this mode is an online QR gateway, else None.
				"gateway": gateways.get(mode),
			}
		)
		if row.default and not default_mode:
			default_mode = mode
	if not default_mode and payments:
		default_mode = payments[0]["mode_of_payment"]

	return {
		"name": doc.name,
		"company": doc.company,
		"customer": doc.customer,
		"warehouse": doc.warehouse,
		"selling_price_list": doc.selling_price_list or "",
		"currency": doc.currency or frappe.db.get_value("Company", doc.company, "default_currency") or "",
		"payments": payments,
		"default_payment_mode": default_mode,
	}


def _rate_for_item(item_code: str, price_list: str | None, stock_uom: str | None) -> tuple[float, str | None, bool]:
	if price_list:
		hit = _lookup_item_price(item_code, price_list, uom=stock_uom)
		if hit:
			return flt(hit["price_list_rate"]), hit["currency"], False
	doc = frappe.get_doc("Item", item_code)
	return flt(doc.standard_rate or doc.valuation_rate or 0), None, True


@frappe.whitelist()
def list_pos_profiles(company: str):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	user = frappe.session.user
	return frappe.db.sql(
		"""
		SELECT p.name, p.customer, p.warehouse, p.selling_price_list, p.currency
		FROM `tabPOS Profile` p
		WHERE p.company = %(company)s
		  AND COALESCE(p.disabled, 0) = 0
		  AND (
		    NOT EXISTS (
		      SELECT 1 FROM `tabPOS Profile User` u
		      WHERE u.parent = p.name
		    )
		    OR EXISTS (
		      SELECT 1 FROM `tabPOS Profile User` u
		      WHERE u.parent = p.name AND u.user = %(user)s
		    )
		  )
		ORDER BY p.name ASC
		""",
		{"company": company, "user": user},
		as_dict=True,
	)


@frappe.whitelist()
def pos_bootstrap(company: str, pos_profile: str):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	return _profile_payload(_pos_profile_doc(company, pos_profile))


@frappe.whitelist()
def search_pos_items(company: str, pos_profile: str, search: str = "", limit: int = 20):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	profile = _pos_profile_doc(company, pos_profile)
	price_list = profile.selling_price_list or _resolve_price_list(profile.customer)
	params = {
		"warehouse": profile.warehouse,
		"search": f"%{(search or '').strip()}%",
		"limit": int(limit or 20),
	}
	search_clause = ""
	if search:
		search_clause = "AND (i.item_code LIKE %(search)s OR i.item_name LIKE %(search)s)"
	rows = frappe.db.sql(
		f"""
		SELECT i.name, i.item_code, i.item_name, i.stock_uom, i.image,
		       i.standard_rate, i.valuation_rate, b.actual_qty
		FROM `tabBin` b
		JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %(warehouse)s
		  AND b.actual_qty > 0
		  AND i.disabled = 0
		  AND i.is_sales_item = 1
		  {search_clause}
		ORDER BY i.item_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	out = []
	for row in rows:
		rate, currency, unresolved = _rate_for_item(row["item_code"], price_list, row.get("stock_uom"))
		out.append(
			{
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"stock_uom": row["stock_uom"],
				"image": row.get("image"),
				"available_qty": flt(row["actual_qty"]),
				"rate": rate,
				"currency": currency or profile.currency,
				"price_list": price_list or "",
				"price_unresolved": unresolved,
			}
		)
	return out


def _validate_and_price_cart(profile, items) -> tuple[list[dict], str | None]:
	"""Normalize the cart, confirm every item exists and is in shop stock."""
	cart = _normalize_cart_items(items)
	price_list = profile.selling_price_list or _resolve_price_list(profile.customer)

	item_codes = [item["item_code"] for item in cart]
	for item_code in item_codes:
		if not frappe.db.exists("Item", item_code):
			frappe.throw(_("Unknown item: {0}").format(item_code), frappe.DoesNotExistError)

	bins = frappe.db.sql(
		"""
		SELECT item_code, actual_qty
		FROM `tabBin`
		WHERE warehouse = %(warehouse)s AND item_code IN %(items)s
		""",
		{"warehouse": profile.warehouse, "items": tuple(item_codes)},
		as_dict=True,
	)
	_assert_cart_available(cart, {r["item_code"]: flt(r["actual_qty"]) for r in bins})
	return cart, price_list


def _assemble_pos_invoice(profile, cart, price_list, posting_date):
	"""Build (but do not insert) a POS Sales Invoice with totals calculated."""
	doc = frappe.new_doc("Sales Invoice")
	doc.company = profile.company
	doc.customer = profile.customer
	doc.is_pos = 1
	doc.pos_profile = profile.name
	doc.update_stock = 1
	doc.set_warehouse = profile.warehouse
	doc.posting_date = getdate(posting_date or today())
	doc.due_date = doc.posting_date
	if price_list:
		doc.selling_price_list = price_list
	if profile.currency:
		doc.currency = profile.currency
	if profile.cost_center:
		doc.cost_center = profile.cost_center

	for item in cart:
		item_doc = frappe.get_doc("Item", item["item_code"])
		rate, _, _ = _rate_for_item(item["item_code"], price_list, item_doc.stock_uom)
		doc.append(
			"items",
			{
				"item_code": item["item_code"],
				"qty": item["qty"],
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
				"warehouse": profile.warehouse,
				"rate": rate,
				"price_list_rate": rate,
			},
		)

	doc.set_missing_values()
	doc.calculate_taxes_and_totals()
	return doc


def build_paid_pos_invoice(
	company: str,
	pos_profile: str,
	items,
	payment_mode: str,
	posting_date: str | None = None,
):
	"""Create + submit a fully-paid POS Sales Invoice. Shared by the cash path
	(create_pos_invoice) and the online-gateway finalizer (uzpay.common). Returns
	the submitted Sales Invoice document."""
	profile = _pos_profile_doc(company, pos_profile)
	cart, price_list = _validate_and_price_cart(profile, items)

	allowed_modes = {row.mode_of_payment for row in profile.payments if row.mode_of_payment}
	if payment_mode not in allowed_modes:
		frappe.throw(_("Payment mode is not allowed for this POS Profile."), frappe.ValidationError)

	payment_account = _payment_account(payment_mode, company)
	doc = _assemble_pos_invoice(profile, cart, price_list, posting_date)
	doc.set("payments", [])
	doc.append(
		"payments",
		{
			"mode_of_payment": payment_mode,
			"account": payment_account,
			"amount": doc.grand_total,
			"base_amount": doc.base_grand_total,
			"default": 1,
		},
	)
	doc.set_paid_amount()
	doc.insert()
	doc.submit()
	return doc


@frappe.whitelist()
def create_pos_invoice(
	company: str,
	pos_profile: str,
	items,
	payment_mode: str,
	posting_date: str | None = None,
):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	doc = build_paid_pos_invoice(company, pos_profile, items, payment_mode, posting_date)
	return {
		"name": doc.name,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"grand_total": flt(doc.grand_total),
		"paid_amount": flt(doc.paid_amount),
		"currency": doc.currency,
	}


# ---------------------------------------------------------------------------
# Online QR gateways (Payme / Click / Uzum Bank)
# ---------------------------------------------------------------------------
def _checkout_builder(provider: str):
	from stabler.integrations.uzpay import click, payme, uzum

	return {
		"Payme": payme.build_checkout_url,
		"Click": click.build_checkout_url,
		"Uzum Bank": uzum.build_checkout_url,
	}.get(provider)


@frappe.whitelist()
def pos_gateway_start(
	company: str,
	pos_profile: str,
	items,
	payment_mode: str,
	posting_date: str | None = None,
):
	"""Open an online-payment session for the current cart: compute the total,
	create a POS Payment Session, build the provider checkout URL + QR, and
	hand them back to the SPA. No invoice is created until the provider
	confirms payment via its webhook."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	from stabler.integrations.uzpay import common as C

	profile = _pos_profile_doc(company, pos_profile)
	provider = C.gateway_for(company, payment_mode)
	if not provider:
		frappe.throw(_("Payment mode {0} is not an online gateway.").format(payment_mode))

	allowed_modes = {row.mode_of_payment for row in profile.payments if row.mode_of_payment}
	if payment_mode not in allowed_modes:
		frappe.throw(_("Payment mode is not allowed for this POS Profile."), frappe.ValidationError)
	# fail fast if the clearing account is misconfigured
	_payment_account(payment_mode, company)

	cart, price_list = _validate_and_price_cart(profile, items)
	draft = _assemble_pos_invoice(profile, cart, price_list, posting_date)
	amount = flt(draft.grand_total)
	currency = draft.currency
	if amount <= 0:
		frappe.throw(_("Cannot start a payment for a zero total."))

	session = C.create_session(
		provider=provider,
		company=company,
		pos_profile=profile.name,
		payment_mode=payment_mode,
		amount=amount,
		currency=currency,
		cart=cart,
	)

	builder = _checkout_builder(provider)
	checkout_url = builder(session)
	session.checkout_url = checkout_url
	session.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"session": session.name,
		"order_id": session.order_id,
		"provider": provider,
		"amount": amount,
		"currency": currency,
		"checkout_url": checkout_url,
		"qr_svg": C.qr_svg_data_uri(checkout_url),
		"expires_at": str(session.expires_at) if session.expires_at else None,
	}


@frappe.whitelist()
def pos_gateway_status(session: str):
	"""Poll a payment session. Auto-expires stale pending sessions."""
	from stabler.integrations.uzpay import common as C

	if not frappe.db.exists(C.SESSION_DT, session):
		frappe.throw(_("Unknown payment session."), frappe.DoesNotExistError)
	doc = frappe.get_doc(C.SESSION_DT, session)

	if doc.status == "Pending" and C.is_expired(doc):
		doc.status = "Expired"
		doc.save(ignore_permissions=True)

	return {
		"session": doc.name,
		"status": doc.status,
		"provider": doc.provider,
		"amount": flt(doc.amount),
		"currency": doc.currency,
		"sales_invoice": doc.sales_invoice,
		"paid_at": str(doc.paid_at) if doc.paid_at else None,
	}


@frappe.whitelist()
def pos_gateway_cancel(session: str):
	"""Cashier abandoned the QR before payment. Only voids a still-pending
	session; a paid session is terminal and must be refunded via the provider."""
	from stabler.integrations.uzpay import common as C

	if not frappe.db.exists(C.SESSION_DT, session):
		frappe.throw(_("Unknown payment session."), frappe.DoesNotExistError)
	doc = frappe.get_doc(C.SESSION_DT, session)
	if doc.status == "Pending":
		doc.status = "Cancelled"
		doc.cancel_time_ms = C.epoch_ms()
		doc.save(ignore_permissions=True)
	return {"session": doc.name, "status": doc.status}
