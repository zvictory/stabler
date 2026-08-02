"""Shared guards and validators for all stabler.api modules.

Import these — do not define local copies. The duplicated definitions have
already diverged in error-message formatting across modules.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def _require_company(company: str | None) -> str:
	if not company:
		frappe.throw(_("Company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))
	return company


def _assert_can_read(doctype: str, name: str) -> None:
	"""Guard any named-record reader against IDOR.

	@frappe.whitelist() gates method access only, not record-level access.
	frappe.get_doc() and raw frappe.db.sql() bypass both permission checks
	and User-Permission (company) row filters — call this before any
	get_doc/sql that fetches a single named record."""
	if not frappe.has_permission(doctype, "read", doc=name):
		raise frappe.PermissionError(_("Not permitted to read {0} {1}").format(doctype, name))


def _assert_can_write(doctype: str, name: str, ptype: str = "write") -> None:
	"""Guard a named-record mutator against IDOR (defense in depth).

	ERPNext's save()/submit()/cancel() check permission themselves, but loading
	with get_doc and then mutating — or using ignore_permissions — can bypass
	that. Call this explicitly. `ptype` may be write / submit / cancel / delete."""
	if not frappe.has_permission(doctype, ptype, doc=name):
		raise frappe.PermissionError(_("Not permitted to {0} {1} {2}").format(ptype, doctype, name))


def _validate_money_overrides(patch: dict, *, row_label: str) -> None:
	if patch.get("rate") not in (None, "") and flt(patch["rate"]) < 0:
		frappe.throw(_("{0}: rate cannot be negative").format(row_label))
	dp = patch.get("discount_percentage")
	if dp not in (None, "") and not (0 <= flt(dp) <= 100):
		frappe.throw(_("{0}: discount_percentage must be between 0 and 100").format(row_label))
	if patch.get("discount_amount") not in (None, "") and flt(patch["discount_amount"]) < 0:
		frappe.throw(_("{0}: discount_amount cannot be negative").format(row_label))


def check_concurrency(doctype: str, name: str, modified: str | None = None) -> None:
	if not name:
		return
	db_modified = frappe.db.get_value(doctype, name, "modified")
	if not db_modified:
		return
	if not modified:
		frappe.throw(_("Stale request: reload the document."))
	from frappe.utils import get_datetime_str

	if get_datetime_str(db_modified) != get_datetime_str(modified):
		frappe.local.response["doctype"] = doctype
		frappe.local.response["name"] = name
		exc = getattr(frappe, "TimestampMismatchError", frappe.ValidationError)
		frappe.throw(_("This document was changed by someone else. Reload to see the latest."), exc=exc)


def _company_default_warehouse(company: str) -> str | None:
	get_val = getattr(frappe, "get_cached_value", getattr(frappe.db, "get_value", None))
	wh = get_val("Company", company, "default_warehouse") if get_val else None
	if wh:
		return wh
	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
