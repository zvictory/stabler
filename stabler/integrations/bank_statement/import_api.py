"""Whitelisted API for importing bank statements into Bank Transaction rows.

Phase 1 of bank reconciliation (see BANK_RECONCILIATION_UZ_PLAN.md): turn a
1C ClientBank Exchange statement file into ERPNext ``Bank Transaction`` rows,
idempotently. Matching/reconciliation is Phase 2.

Idempotency: each normalized line carries a stable ``dedupe_key``; we store it
on ``Bank Transaction.transaction_id`` and skip any line whose key already
exists for that bank account. Re-importing the same (or an overlapping)
statement is therefore safe.
"""
from __future__ import annotations

import base64

import frappe
from stabler.api.approvals import _assert_company_scope
from frappe import _

from stabler.api._common import _require_company
from stabler.api.organization import _can_access_module
from stabler.integrations.bank_statement.parser_1c import (
	is_1c_exchange,
	parse_statement_bytes,
)


def _require_recon() -> None:
	if not _can_access_module(frappe.session.user, "money"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _decode_content(content_base64: str) -> bytes:
	try:
		return base64.b64decode(content_base64)
	except Exception:
		frappe.throw(_("Could not read the uploaded file."))


def _bank_account_meta(bank_account: str) -> dict:
	row = frappe.db.get_value(
		"Bank Account",
		bank_account,
		["name", "account", "company", "bank_account_no", "account_name", "bank"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Bank Account '{0}' not found.").format(bank_account))
	row["currency"] = (
		frappe.db.get_value("Account", row.account, "account_currency") if row.account else None
	) or frappe.get_cached_value("Company", row.company, "default_currency")
	return row


@frappe.whitelist()
def bank_accounts_for_recon(company: str) -> list[dict]:
	"""Bank Accounts for the company, for the reconciliation account picker."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_recon()
	_require_company(company)
	rows = frappe.get_all(
		"Bank Account",
		filters={"company": company, "is_company_account": 1},
		fields=["name", "account_name", "bank", "bank_account_no", "account"],
		order_by="account_name",
	)
	for r in rows:
		r["currency"] = (
			frappe.db.get_value("Account", r.account, "account_currency") if r.account else None
		)
	return rows


@frappe.whitelist()
def preview_statement(content_base64: str, bank_account: str | None = None) -> dict:
	"""Parse a statement WITHOUT saving — returns rows + period for review."""
	_require_recon()
	raw = _decode_content(content_base64)
	
	from stabler.integrations.bank_statement.parser_msaerp_xlsx import is_msaerp_xlsx, parse_statement_bytes as parse_xlsx_bytes

	if is_msaerp_xlsx(raw):
		parsed = parse_xlsx_bytes(raw, our_account=bank_account)
	else:
		text_head = raw[:64].decode("ascii", errors="ignore")
		if "1CClientBankExchange" not in raw[:64].decode("cp1251", errors="ignore") and "1CClientBankExchange" not in text_head:
			frappe.throw(
				_("Unsupported statement format. Please upload a 1C ClientBank file or an Excel statement.")
			)
		parsed = parse_statement_bytes(raw)

	account_match = None
	if bank_account:
		meta = _bank_account_meta(bank_account)
		stmt_acc = (parsed.get("account") or "").strip()
		acc_no = (meta.get("bank_account_no") or "").strip()
		account_match = bool(stmt_acc and acc_no and stmt_acc == acc_no)
		parsed["expected_account_no"] = acc_no
	parsed["account_match"] = account_match
	# Cap rows returned to the UI; the import reads them all server-side.
	parsed["rows"] = parsed["rows"][:500]
	return parsed


@frappe.whitelist()
def import_statement(
	company: str,
	bank_account: str,
	content_base64: str,
	file_name: str | None = None,
) -> dict:
	"""Parse a 1C or Excel statement and create Bank Transaction rows (idempotent)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_recon()
	_require_company(company)
	meta = _bank_account_meta(bank_account)
	if meta.company != company:
		frappe.throw(_("Bank account does not belong to company '{0}'.").format(company))

	raw = _decode_content(content_base64)
	
	from stabler.integrations.bank_statement.parser_msaerp_xlsx import is_msaerp_xlsx, parse_statement_bytes as parse_xlsx_bytes

	if is_msaerp_xlsx(raw):
		parsed = parse_xlsx_bytes(raw, our_account=meta.get("bank_account_no") or None)
		file_format = "Excel"
	else:
		text = raw.decode("cp1251", errors="ignore")
		if not is_1c_exchange(text) and not is_1c_exchange(raw.decode("utf-8", errors="ignore")):
			frappe.throw(_("Unsupported statement format. Please upload a 1C ClientBank file or an Excel statement."))
		parsed = parse_statement_bytes(raw, our_account=meta.get("bank_account_no") or None)
		file_format = "1CClientBankExchange"

	rows = parsed["rows"]

	imported = duplicates = skipped = 0
	for r in rows:
		if not r.get("direction") or not r.get("date") or not r.get("amount"):
			skipped += 1
			continue
		key = r["dedupe_key"]
		if frappe.db.exists(
			"Bank Transaction", {"bank_account": bank_account, "transaction_id": key}
		):
			duplicates += 1
			continue
		bt = frappe.new_doc("Bank Transaction")
		bt.date = r["date"]
		bt.bank_account = bank_account
		bt.company = company
		bt.deposit = r["deposit"]
		bt.withdrawal = r["withdrawal"]
		bt.currency = meta.get("currency")
		bt.description = r["description"]
		bt.reference_number = r["reference_number"]
		bt.transaction_id = key
		bt.insert(ignore_permissions=False)
		# Bank Transaction is submittable; submit so it is reconcilable. This is
		# not a money movement (no GL impact), so the approval gate does not apply.
		bt.submit()
		imported += 1

	status = "Imported" if not skipped else "Partial"
	batch = frappe.new_doc("Stabler Bank Import")
	batch.bank_account = bank_account
	batch.company = company
	batch.statement_account = parsed.get("account")
	batch.period_from = parsed.get("period_from")
	batch.period_to = parsed.get("period_to")
	batch.total_rows = len(rows)
	batch.imported_rows = imported
	batch.duplicate_rows = duplicates
	batch.skipped_rows = skipped
	batch.file_name = file_name
	batch.format = file_format
	batch.status = status
	batch.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"import": batch.name,
		"total": len(rows),
		"imported": imported,
		"duplicates": duplicates,
		"skipped": skipped,
		"period_from": parsed.get("period_from"),
		"period_to": parsed.get("period_to"),
	}


@frappe.whitelist()
def list_recent_imports(company: str | None = None, limit: int = 25) -> list[dict]:
	"""Recent statement imports for the audit/history panel."""
	_require_recon()

	# Multi-tenant scoping: validate a passed company against the caller's
	# allowed set; when omitted, restrict a scoped non-admin to their allowed
	# companies instead of returning every tenant's import history. Admins /
	# unrestricted users (empty allowed list) are unaffected.
	from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

	is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
	allowed = [] if is_admin else _user_allowed_companies(frappe.session.user)
	filters = {}
	if company:
		if allowed and company not in allowed:
			frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
		filters["company"] = company
	elif allowed:
		filters["company"] = ["in", allowed]
	return frappe.get_all(
		"Stabler Bank Import",
		filters=filters,
		fields=[
			"name", "bank_account", "statement_account", "period_from", "period_to",
			"total_rows", "imported_rows", "duplicate_rows", "skipped_rows",
			"status", "file_name", "creation", "owner",
		],
		order_by="creation desc",
		limit=min(int(limit or 25), 100),
	)
