"""Thin Frappe wrapper for the standalone shadow store (WP-S4a).

Resolves the SEPARATE SQLite file (site private files — NOT the ERPNext DB, NOT a
doctype), exposes in-process helpers the bot/admin call (record / remove /
set_opening) and a fail-closed Telegram-Mini-App READ endpoint (shadow_view).
The store logic itself is frappe-free (shadow_store.py). Never logs init_data or
the bot token. This shadow ledger never posts to GL / accounting.
"""

from __future__ import annotations

from . import shadow_store
from .miniapp import _resolve_kassir, verify_init_data

try:  # frappe-optional so the module imports under plain unittest
	import frappe
	from frappe import _
except Exception:  # pragma: no cover
	frappe = None

	def _(m):
		return m


SHADOW_DB = "kassa_shadow.sqlite"


def _db_path() -> str:
	"""The standalone SQLite file, per-site, outside the ERPNext DB."""
	return frappe.get_site_path("private", "files", SHADOW_DB)


# --------------------------------------------------------------------------- #
# In-process helpers (called by the bot / admin, never from the browser)
# --------------------------------------------------------------------------- #
def record(company, kassir, op, deltas, **kw) -> str:
	"""Write one shadow action + its signed per-kassa deltas. Returns entry id."""
	return shadow_store.add_entry(_db_path(), company=company, kassir=kassir, op=op, deltas=deltas, **kw)


def remove(entry_id, company) -> None:
	shadow_store.delete_entry(_db_path(), entry_id, company)


def set_opening(company, date, kassa, amount) -> None:
	shadow_store.set_opening(_db_path(), company, date, kassa, float(amount))


def balances(company, date) -> dict:
	"""{'nakit':..,'pk':..,'usd':..} for the bot header (ctx['balances'])."""
	return shadow_store.balances(_db_path(), company, date)


def last_counterparty(company, date):
	"""Most-recent entry's counterparty today (for 'yana …' reuse). None if none."""
	for e in shadow_store.list_entries(_db_path(), company, date):
		if e.get("counterparty"):
			return e["counterparty"]
	return None


def undo_last(company, date):
	"""Delete the most-recent entry of the day. Returns the deleted entry dict or None."""
	entries = shadow_store.list_entries(_db_path(), company, date)
	if not entries:
		return None
	e = entries[0]
	shadow_store.delete_entry(_db_path(), e["id"], company)
	return e


def view(company, date) -> dict:
	p = _db_path()
	return {
		"date": date,
		"company": company,
		"balances": shadow_store.balances(p, company, date),
		"openings": shadow_store.get_openings(p, company, date),
		# What the ledger's running column starts at. Not the same as `openings`,
		# which holds only what was declared for this date and is usually empty.
		"opening_balances": shadow_store.opening_balances(p, company, date),
		"entries": shadow_store.list_entries(p, company, date),
	}


# --------------------------------------------------------------------------- #
# Mini App read endpoint — fail-closed (Telegram initData HMAC), read-only.
# --------------------------------------------------------------------------- #
def _shadow_view(init_data: str, date: str | None = None) -> dict:
	token = getattr(frappe.conf, "kassa_telegram_token", None)
	if not token:
		frappe.throw(_("Kassa Telegram integration is not configured"), frappe.PermissionError)
	user = verify_init_data(init_data, token)
	if not user:
		frappe.log_error(
			title="Kassa shadow: rejected (invalid initData)",
			message="init_data signature verification failed or expired",
		)
		frappe.throw(_("Invalid Telegram signature"), frappe.PermissionError)
	kassir = _resolve_kassir(str(user.get("id") or "").strip())
	if not kassir:
		frappe.throw(_("Ruxsat yo'q"), frappe.PermissionError)
	return view(kassir.company, date or frappe.utils.today())


if frappe is not None:
	try:
		from frappe.rate_limiter import rate_limit
	except Exception:  # pragma: no cover

		def rate_limit(*a, **k):
			def deco(fn):
				return fn

			return deco

	shadow_view = frappe.whitelist(allow_guest=True)(rate_limit(limit=120, seconds=60)(_shadow_view))
else:  # pragma: no cover — plain-unittest import path only
	shadow_view = _shadow_view
