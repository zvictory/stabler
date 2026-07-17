# Copyright (c) 2026, Stabler and contributors
"""Stabler Kassir (WP-K3) — links a Telegram user id to a Frappe User + Company
so the kassa Telegram bot can impersonate the right user for permission /
approval / backdating governance to apply exactly as if they'd used the SPA.

Kept intentionally minimal: this is a mapping record, not a transactional
document. All accounting logic lives in stabler.api.money — see
stabler/integrations/kassa/bot.py.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

_DIGITS_ONLY = re.compile(r"^\d+$")


class StablerKassir(Document):
	def validate(self):
		self._validate_telegram_user_id()

	def _validate_telegram_user_id(self):
		value = (self.telegram_user_id or "").strip()
		if not value or not _DIGITS_ONLY.match(value):
			frappe.throw(_("Telegram User ID must contain digits only."))
		self.telegram_user_id = value
