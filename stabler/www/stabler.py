"""Controller for the /stabler SPA shell.

Handles guest redirect, CSRF token, and user/locale context for the Tabler
HTML shell. The actual route inside the SPA is parsed client-side.
"""

import csv
import os
from urllib.parse import quote_plus

import frappe
import frappe.sessions

no_cache = 1
no_sitemap = 1


def get_context(context):
	# Allow Guest users to load the SPA shell so client-side routing can handle the operator kiosk
	# guest view, while redirecting other paths on the client side.
	pass

	try:
		csrf_token = frappe.sessions.get_csrf_token()
	except Exception:
		csrf_token = ""

	context.csrf_token = csrf_token
	context.no_cache = 1

	user = frappe.session.user
	context.user_id = user
	context.user_fullname = user
	context.user_image = ""
	context.user_language = frappe.local.lang or "en"

	try:
		user_doc = frappe.get_doc("User", user)
		context.user_fullname = user_doc.full_name or user_doc.first_name or user
		context.user_image = user_doc.user_image or ""
		context.user_language = user_doc.language or context.user_language
	except Exception:
		pass

	context.default_company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	context.companies = _list_companies()

	context.app_path = frappe.local.request.path or "/stabler"
	context.translations = _load_translations(context.user_language)
	context.asset_version = _asset_version()
	context.cost_visible = _cost_visible_for_shell(user)

	return context


def _cost_visible_for_shell(user: str) -> bool:
	"""Imports landed-cost visibility flag for window.__STABLER__ (never fatal).

	Seeds the SPA session store before the async boot() round-trip so the create
	forms show/hide cost inputs without a flash; the backend re-checks on write."""
	try:
		if not user or user == "Guest":
			return False
		from stabler.api.permissions import cost_visible_for

		return bool(cost_visible_for(user))
	except Exception:
		return False


def _asset_version() -> str:
	"""Cache-busting token for raw /assets links (stabler.css + stabler-modernist.css).
	Unlike the hashed JS bundle from include_script(), the CSS is linked by a static
	path, so without this it serves stale after every edit/deploy (forcing a hard
	refresh). Keyed on the NEWEST mtime across every linked stylesheet — one token
	is shared by both <link> tags, so keying it on only one of them would serve the
	other stale whenever that one alone changed."""
	try:
		stamps = []
		for fname in ("stabler.css", "stabler-modernist.css"):
			path = frappe.get_app_path("stabler", "public", "css", fname)
			try:
				stamps.append(int(os.path.getmtime(path)))
			except OSError:
				# Dosya henüz yoksa atla — tek bir eksik dosya yüzünden
				# diğerinin cache-bust'ı kaybolmasın.
				continue
		return str(max(stamps)) if stamps else "0"
	except Exception:
		return "0"


def _load_translations(lang: str) -> dict:
	"""Read apps/stabler/stabler/translations/<lang>.csv and return source→target map.
	English (or any unknown language) returns an empty dict — falls back to source strings."""
	if not lang or lang == "en":
		return {}
	cache_key = f"stabler:translations:{lang}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	app_path = frappe.get_app_path("stabler")
	csv_path = os.path.join(app_path, "translations", f"{lang}.csv")
	if not os.path.exists(csv_path):
		return {}
	out: dict = {}
	try:
		with open(csv_path, encoding="utf-8") as f:
			reader = csv.reader(f)
			for i, row in enumerate(reader):
				if i == 0 and row and row[0].lower() == "source":
					continue
				if len(row) >= 2 and row[0] and row[1]:
					out[row[0]] = row[1]
	except Exception:
		frappe.log_error(f"Failed to load stabler translations for {lang}")
	frappe.cache().set_value(cache_key, out, expires_in_sec=3600)
	return out


def _list_companies():
	user = frappe.session.user
	try:
		allowed = frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Company"},
			pluck="for_value",
		)
		filters: dict = {}
		if allowed:
			filters["name"] = ("in", allowed)
		return frappe.get_all(
			"Company",
			filters=filters,
			fields=["name", "abbr", "default_currency"],
			order_by="name asc",
		)
	except Exception:
		return []
