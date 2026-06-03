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
	if frappe.session.user == "Guest":
		redirect_to = frappe.local.request.path or "/stabler"
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote_plus(redirect_to)
		raise frappe.Redirect

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

	context.default_company = (
		frappe.db.get_single_value("Global Defaults", "default_company") or ""
	)
	context.companies = _list_companies()

	context.app_path = frappe.local.request.path or "/stabler"
	context.translations = _load_translations(context.user_language)
	context.asset_version = _asset_version()

	return context


def _asset_version() -> str:
	"""Cache-busting token for raw /assets links (e.g. stabler.css). Unlike the
	hashed JS bundle from include_script(), the CSS is linked by a static path, so
	without this it serves stale after every edit/deploy (forcing a hard refresh).
	Keyed on the file's mtime: changes only when the file changes — fresh on edit/
	deploy, fully cacheable in between."""
	try:
		css = frappe.get_app_path("stabler", "public", "css", "stabler.css")
		return str(int(os.path.getmtime(css)))
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
