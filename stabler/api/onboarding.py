"""GENESIS onboarding — server-driven wizard schema, resumable checkpoint state,
and the single idempotent provisioning transaction.

Design notes / deliberate deviations from the standard endpoint template:

  * These endpoints run BEFORE a company exists (that is the whole point of
    onboarding), so the usual `_require_company` / `_assert_company_scope` guard
    cannot apply on the way in. Instead they are gated to an authenticated (non
    Guest) user, and `provision()` is idempotent + one-company-per-user so it
    cannot be abused to spawn duplicates.
  * Checkpoint state is stored as a per-user default (`frappe.defaults`), NOT a
    new doctype — this keeps the change inside the WP-271 package (no schema
    migration, no files outside the package).
  * No `frappe.db.commit()` — the request transaction commits atomically, so a
    failure part-way rolls the whole provisioning back (checkpoint lets the user
    resume). No f-string / %-interpolated SQL.

VERIFICATION BOUNDARY: `provision()` orchestrates ERPNext company setup (the
Company controller auto-creates the CoA from the chosen template plus default
warehouses and cost centers on insert; we then set user default + roles + a
starter POS Profile). This path CANNOT be exercised in a unit sandbox — it must
be validated on a CLEAN Frappe site. The "TTV <= 10 min to POS + first sale"
acceptance is an end-to-end product check run on that fresh site.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from stabler.api.organization import _user_allowed_companies, set_user_allowed_companies

SCHEMA_VERSION = 1
_WIZARD_STATE_KEY = "stabler_genesis_wizard_state"
_POS_ROUTE = "/pos"  # SPA route (never the Frappe Desk)


# --------------------------------------------------------------------------- #
# Server-driven wizard schema (the 7 frictionless questions)
# --------------------------------------------------------------------------- #
def _languages() -> list[dict]:
	return [
		{"value": "en", "label": "English"},
		{"value": "ru", "label": "Русский"},
		{"value": "uz", "label": "O'zbek"},
		{"value": "uzc", "label": "Ўзбек"},
		{"value": "tr", "label": "Türkçe"},
	]


def _industries() -> list[str]:
	return [
		_("Retail"),
		_("Wholesale / Distribution"),
		_("Manufacturing"),
		_("Services"),
		_("Food & Beverage"),
		_("Construction"),
		_("Other"),
	]


def _tax_types() -> list[dict]:
	return [
		{"value": "vat", "label": _("VAT registered")},
		{"value": "simplified", "label": _("Simplified / turnover tax")},
		{"value": "none", "label": _("Not registered")},
	]


@frappe.whitelist()
def wizard_schema() -> dict:
	"""Return the versioned, server-driven schema for the Genesis wizard.

	Read-only reference data (Currency/Country are public reference doctypes); no
	company exists yet, so no company scope applies. Bounded with an explicit limit.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	currencies = frappe.get_all("Currency", filters={"enabled": 1}, pluck="name", limit_page_length=500) or [
		"UZS",
		"USD",
		"EUR",
	]
	countries = frappe.get_all("Country", pluck="name", limit_page_length=500)
	return {
		"v": SCHEMA_VERSION,
		"questions": [
			{"key": "business_name", "label": _("Business name"), "type": "text", "required": 1},
			{
				"key": "industry",
				"label": _("Industry"),
				"type": "select",
				"options": _industries(),
				"required": 1,
			},
			{
				"key": "country",
				"label": _("Country"),
				"type": "select",
				"options": countries,
				"required": 1,
				"default": "Uzbekistan",
			},
			{
				"key": "currency",
				"label": _("Base currency"),
				"type": "select",
				"options": currencies,
				"required": 1,
				"default": "UZS",
			},
			{
				"key": "language",
				"label": _("Language"),
				"type": "select",
				"options": _languages(),
				"required": 1,
				"default": "uz",
			},
			{
				"key": "tax_type",
				"label": _("Tax type"),
				"type": "select",
				"options": _tax_types(),
				"required": 1,
				"default": "vat",
			},
			{
				"key": "abbr",
				"label": _("Short code"),
				"type": "text",
				"required": 0,
				"hint": _("e.g. ANJ — leave blank to auto-generate"),
			},
		],
	}


# --------------------------------------------------------------------------- #
# Resumable checkpoint (per-user default; no doctype)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_wizard_state() -> dict:
	"""Return the saved checkpoint so an interrupted signup can resume."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	raw = frappe.defaults.get_user_default(_WIZARD_STATE_KEY, frappe.session.user)
	try:
		return {"state": json.loads(raw) if raw else {}}
	except Exception:
		return {"state": {}}


@frappe.whitelist()
def save_wizard_state(state: dict | str) -> dict:
	"""Persist the wizard checkpoint (bounded, JSON-safe primitives only)."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if isinstance(state, str):
		try:
			state = json.loads(state)
		except Exception:
			state = {}
	if not isinstance(state, dict):
		state = {}
	safe = {
		str(k): v for k, v in list(state.items())[:20] if isinstance(v, (str, int, float, bool)) or v is None
	}
	frappe.defaults.set_user_default(
		_WIZARD_STATE_KEY, json.dumps(safe, ensure_ascii=False), frappe.session.user
	)
	return {"ok": True}


# --------------------------------------------------------------------------- #
# The single idempotent provisioning transaction
# --------------------------------------------------------------------------- #
def _auto_abbr(name: str) -> str:
	letters = "".join(ch for ch in name.upper() if ch.isalnum())[:5]
	return letters or "CO"


def _done(company: str) -> dict:
	return {"ok": True, "company": company, "next": _POS_ROUTE}


def _grant_and_default(user: str, company: str) -> None:
	"""Give `user` access to the company and make it their default.

	set_user_allowed_companies() is admin-gated (it's also how Stabler Admin manages
	OTHER users' access), so onboarding — which grants a brand-new non-admin user
	access to the company they just created — must call it as Administrator, same
	as the fixture install above.
	"""
	allowed = set(_user_allowed_companies(user) or [])
	allowed.add(company)
	_actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		set_user_allowed_companies(user, sorted(allowed))
	finally:
		frappe.set_user(_actor)
	frappe.defaults.set_user_default("company", company, user)


def _ensure_pos_profile(company: str, currency: str) -> None:
	"""Create a minimal starter POS Profile if none exists for the company.

	POS Profile requires a payments row plus warehouse/write_off_account/
	write_off_cost_center. All four are resolved dynamically (never hardcoded
	names) since fixture-installed names are language/company dependent —
	validated against a clean site in WP-271. Guarded so a missing/renamed
	field never blocks provisioning; POS Profile is a convenience, not a gate.
	"""
	try:
		if frappe.db.exists("POS Profile", {"company": company}):
			return
		mode_of_payment = frappe.db.get_value("Mode of Payment Account", {"company": company}, "parent")
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0}, "name", order_by="name"
		)
		write_off_account, write_off_cost_center = frappe.db.get_value(
			"Company", company, ["write_off_account", "cost_center"]
		)
		if not (mode_of_payment and warehouse and write_off_account and write_off_cost_center):
			return
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": f"{company} POS",
				"company": company,
				"currency": currency,
				"disabled": 0,
				"warehouse": warehouse,
				"write_off_account": write_off_account,
				"write_off_cost_center": write_off_cost_center,
				"payments": [{"mode_of_payment": mode_of_payment, "default": 1}],
			}
		).insert(ignore_permissions=True)
	except Exception:
		# POS Profile is a convenience, not a gate — the user still reaches POS and
		# can finish it there. Never fail provisioning on it.
		frappe.clear_last_message()


@frappe.whitelist()
def provision(payload: dict | str) -> dict:
	"""Create the company + ERPNext defaults + roles in one idempotent transaction.

	Idempotent: if the user already owns a company, or a company with the same
	name already exists, that company is reused (no duplicate). No db.commit — the
	request commits atomically; a mid-way failure rolls back and the checkpoint
	lets the user resume.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if isinstance(payload, str):
		payload = json.loads(payload)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid payload."), frappe.ValidationError)

	business_name = (payload.get("business_name") or "").strip()
	if not business_name:
		frappe.throw(_("Business name is required."), frappe.ValidationError)
	currency = (payload.get("currency") or "UZS").strip()
	country = (payload.get("country") or "Uzbekistan").strip()
	abbr = (payload.get("abbr") or "").strip() or _auto_abbr(business_name)

	# Idempotency ------------------------------------------------------------
	existing = _user_allowed_companies(frappe.session.user)
	if existing:
		return _done(existing[0])
	existing_owner = frappe.db.get_value("Company", business_name, "owner")
	if existing_owner:
		if existing_owner == frappe.session.user:
			_grant_and_default(frappe.session.user, business_name)
			return _done(business_name)
		frappe.throw(_("A company with this name already exists."), frappe.ValidationError)

	# provision() runs before the interactive ERPNext Setup Wizard ever executes,
	# so Setup-Wizard-only fixtures (e.g. the "Transit" Warehouse Type required by
	# Company.on_update()'s create_default_warehouses()) are seeded here instead.
	# install_fixtures.install() is safe to call repeatedly (ignore_if_duplicate /
	# exists-guards throughout) except that it overwrites the global Selling
	# Settings / Buying Settings singletons on every call — acceptable here since
	# GENESIS onboarding is the only path that creates ERPNext companies. Some of
	# its inserts (e.g. supplier_scorecard.make_default_records) don't pass
	# ignore_permissions, so it must run as Administrator (same as the real Setup
	# Wizard always does) rather than as the onboarding user.
	from erpnext.setup.setup_wizard.operations.install_fixtures import install as _install_fixtures

	_actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		_install_fixtures(country)
	finally:
		frappe.set_user(_actor)

	# Create the company. ERPNext's Company controller auto-creates the CoA from
	# `chart_of_accounts`, plus default warehouses and cost centers, on insert.
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": business_name,
			"abbr": abbr,
			"default_currency": currency,
			"country": country,
			"chart_of_accounts": "Standard",
		}
	)
	company.insert(ignore_permissions=True)

	_grant_and_default(frappe.session.user, company.name)
	_ensure_pos_profile(company.name, currency)

	frappe.defaults.set_user_default(
		_WIZARD_STATE_KEY,
		json.dumps({"step": "done", "company": company.name}),
		frappe.session.user,
	)
	return _done(company.name)
