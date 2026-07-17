# Copyright (c) 2026, Stabler and contributors
"""Kassa Bot (Telegram kasiyer botu) yönetim API'si — SPA Admin > Kassa Bot.

Frappe Desk'e gitmeden `Stabler Kassir` kayıtlarını yönetmek için CRUD katmanı.
`admin.py` desenini yansıtır: her whitelist metodu önce `_require_admin()`,
tüm user-facing string'ler `_()` ile. Bot okuma tarafı (bot.py:_resolve_kassir)
`{telegram_user_id, enabled:1}` ile filtreler → `enabled=0` = kill-switch.
"""

from __future__ import annotations

import frappe
from frappe import _

_DOCTYPE = "Stabler Kassir"


def _require_admin():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def list_kassirs(search=None, company=None, enabled=None, limit=100):
	"""Kassir kayıtlarını listele (opsiyonel company/enabled/search filtreli)."""
	_require_admin()
	filters = {}
	if company:
		filters["company"] = company
	if enabled is not None and enabled != "":
		filters["enabled"] = int(enabled)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"telegram_user_id": ["like", like], "user": ["like", like]}

	return frappe.get_all(
		_DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=["name", "telegram_user_id", "user", "company", "enabled"],
		order_by="modified desc",
		limit=int(limit),
	)


@frappe.whitelist()
def get_kassir(name):
	"""Tek kassir + izinli kasa hesapları (accounts child listesi)."""
	_require_admin()
	if not frappe.db.exists(_DOCTYPE, name):
		frappe.throw(_("Kassir not found"))
	doc = frappe.get_doc(_DOCTYPE, name)
	return {
		"name": doc.name,
		"telegram_user_id": doc.telegram_user_id,
		"user": doc.user,
		"company": doc.company,
		"enabled": int(doc.enabled or 0),
		"accounts": [{"account": a.account} for a in (doc.accounts or [])],
	}


@frappe.whitelist()
def create_kassir(telegram_user_id, user, company, enabled=1, accounts=None):
	"""Yeni kassir oluştur. Dupe guard telegram_user_id üzerinde (autoname alanı)."""
	_require_admin()
	telegram_user_id = (telegram_user_id or "").strip()
	if not telegram_user_id:
		frappe.throw(_("Telegram User ID is required."))
	if frappe.db.exists(_DOCTYPE, telegram_user_id):
		frappe.throw(_("A kassir with this Telegram User ID already exists."))
	if not user:
		frappe.throw(_("User is required."))
	if not company:
		frappe.throw(_("Company is required."))

	doc = frappe.new_doc(_DOCTYPE)
	doc.telegram_user_id = telegram_user_id
	doc.user = user
	doc.company = company
	doc.enabled = int(enabled)
	for row in frappe.parse_json(accounts) or []:
		acc = row.get("account") if isinstance(row, dict) else row
		if acc:
			doc.append("accounts", {"account": acc})
	# telegram_user_id rakam-dışı ise doctype validate() throw eder.
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def update_kassir(name, user=None, company=None, enabled=None, accounts=None):
	"""Kassir düzenle. accounts child'ı clear-then-append ile yeniden yazılır.

	telegram_user_id değiştirilemez (autoname/allow_rename:0) — kasıtlı olarak
	imzada yok.
	"""
	_require_admin()
	if not frappe.db.exists(_DOCTYPE, name):
		frappe.throw(_("Kassir not found"))
	doc = frappe.get_doc(_DOCTYPE, name)
	if user:
		doc.user = user
	if company:
		doc.company = company
	if enabled is not None and enabled != "":
		doc.enabled = int(enabled)
	if accounts is not None:
		doc.set("accounts", [])
		for row in frappe.parse_json(accounts) or []:
			acc = row.get("account") if isinstance(row, dict) else row
			if acc:
				doc.append("accounts", {"account": acc})
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def set_kassir_enabled(name, enabled):
	"""Inline kill-switch — enable/disable tek alan güncellemesi."""
	_require_admin()
	if not frappe.db.exists(_DOCTYPE, name):
		frappe.throw(_("Kassir not found"))
	doc = frappe.get_doc(_DOCTYPE, name)
	doc.enabled = int(enabled)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "enabled": int(doc.enabled or 0)}


@frappe.whitelist()
def delete_kassir(name):
	"""Kassir kaydını sil."""
	_require_admin()
	if not frappe.db.exists(_DOCTYPE, name):
		frappe.throw(_("Kassir not found"))
	frappe.delete_doc(_DOCTYPE, name, ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}
