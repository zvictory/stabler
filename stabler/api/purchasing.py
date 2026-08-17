"""Purchasing module — Suppliers, Purchase Invoices, AP aging."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from stabler.api import _import_exposure, _unbilled_receipts
from stabler.api._common import (
	_assert_can_read,
	_assert_can_write,
	_company_default_warehouse,
	_require_company,
	check_concurrency,
)
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from stabler.stabler.doctype.stabler_settings.stabler_settings import (
	imports_supplier_groups_for,
	module_map_for,
)


@frappe.whitelist()
def list_suppliers(company: str, search: str = "", limit: int = 100, supplier_group_scope: str | None = None):
	"""Supplier picker feed. `supplier_group_scope` is optional and narrows the
	list to the supplier groups a company configured for that scope.

	Twenty screens share this endpoint and only the imports CI/Proforma pickers
	pass a scope, so the no-scope call must stay exactly the query it has always
	been — a config row on one tenant must not empty anybody else's picker."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(frappe._("You are not permitted to view suppliers."), frappe.PermissionError)
	conds = ["disabled = 0"]
	params: dict = {"limit": int(limit)}
	if search:
		conds.append("(supplier_name LIKE %(s)s OR name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	if supplier_group_scope:
		# The client sends a scope KEY, never group names: which groups count as
		# "meat suppliers" is per-tenant config, and the browser must neither
		# learn it nor be able to tamper with it. Resolution happens here.
		if supplier_group_scope == "imports":
			groups = imports_supplier_groups_for(company)
		else:
			# A typo is a caller bug, not a request for "no restriction". Log it
			# so it stays visible, then filter nothing so the picker still works.
			frappe.log_error(
				f"list_suppliers: unknown supplier_group_scope {supplier_group_scope!r}",
				"stabler.purchasing",
			)
			groups = []
		# Nothing configured => no predicate at all, i.e. today's behaviour.
		if groups:
			conds.append("supplier_group IN %(groups)s")
			params["groups"] = groups
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, supplier_name, supplier_group, supplier_type, country,
		       default_currency, mobile_no, email_id
		FROM `tabSupplier`
		WHERE {where}
		ORDER BY supplier_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def list_suppliers_with_balances(
	company: str,
	search: str = "",
	limit: int = 200,
	only_with_balance: int = 0,
	only_overdue: int = 0,
):
	"""Suppliers + live payables balance (base + account currency) aggregated
	from GL Entry party rows against this company.

	Sign convention follows QuickBooks A/P: `balance_base` positive = we owe
	the supplier. GL stores payables as credit-natured, so we aggregate
	`SUM(credit - debit)`."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(frappe._("You are not permitted to view suppliers."), frappe.PermissionError)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	conds = ["s.disabled = 0"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(s.supplier_name LIKE %(q)s OR s.name LIKE %(q)s)")
		params["q"] = f"%{search}%"
	where = " AND ".join(conds)
	# How many suppliers the filter actually matches, so the UI can admit when
	# `limit` truncated the page instead of silently under-reporting the footer.
	total_count = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabSupplier` s WHERE {where}",
		params,
	)[0][0]

	# Book-wide balance for the SAME filter, ignoring `limit`. Grouped per account
	# currency because totals are never converted (CLAUDE.md). Payable sign is
	# credit − debit, matching the row query below.
	# NOTE: this omits the Payment Entry drift correction applied per row. The UI
	# only shows this figure when the list IS capped, so it never sits next to the
	# drift-corrected footer for a direct comparison.
	grand_totals = frappe.db.sql(
		f"""
		SELECT p.cur AS currency, SUM(p.bal_acc) AS amount
		FROM (
		  SELECT MAX(g.account_currency) AS cur,
		         SUM(g.credit_in_account_currency - g.debit_in_account_currency) AS bal_acc
		  FROM `tabGL Entry` g
		  JOIN `tabSupplier` s ON s.name = g.party
		  WHERE g.company = %(company)s
		    AND g.party_type = 'Supplier'
		    AND g.is_cancelled = 0
		    AND {where}
		  GROUP BY g.party
		) p
		WHERE p.cur IS NOT NULL
		GROUP BY p.cur
		HAVING SUM(p.bal_acc) != 0
		""",
		params,
		as_dict=True,
	)
	grand_totals = [{"currency": r["currency"], "amount": flt(r["amount"])} for r in (grand_totals or [])]

	rows = frappe.db.sql(
		f"""
		SELECT
		  s.name,
		  s.supplier_name,
		  s.supplier_group,
		  s.supplier_type,
		  s.country,
		  s.default_currency,
		  s.mobile_no,
		  s.email_id,
		  COALESCE(g.balance_base, 0) AS balance_base,
		  COALESCE(g.balance_acc, 0) AS balance_acc,
		  g.account_currency,
		  COALESCE(g.currency_count, 0) AS acc_currency_count
		FROM `tabSupplier` s
		LEFT JOIN (
		  SELECT
		    party,
		    SUM(credit - debit) AS balance_base,
		    SUM(credit_in_account_currency - debit_in_account_currency) AS balance_acc,
		    MAX(account_currency) AS account_currency,
		    COUNT(DISTINCT account_currency) AS currency_count
		  FROM `tabGL Entry`
		  WHERE company = %(company)s
		    AND party_type = 'Supplier'
		    AND is_cancelled = 0
		  GROUP BY party
		) g ON g.party = s.name
		WHERE {where}
		ORDER BY s.supplier_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	# Correct PE party-leg drift (see customers.py for rationale).
	# Supplier balance sign = credit − debit, so drift is computed in that direction.
	drift_rows = frappe.db.sql(
		"""
		SELECT g.party AS party,
		       SUM(
		         (CASE WHEN g.credit_in_account_currency > 0
		               THEN (CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                          WHEN g.account = pe.paid_to   THEN pe.received_amount
		                          ELSE 0 END)
		               ELSE -(CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                           WHEN g.account = pe.paid_to   THEN pe.received_amount
		                           ELSE 0 END)
		          END)
		         - (g.credit_in_account_currency - g.debit_in_account_currency)
		       ) AS drift
		FROM `tabGL Entry` g
		JOIN `tabPayment Entry` pe ON pe.name = g.voucher_no
		JOIN (
		  SELECT voucher_no
		  FROM `tabGL Entry`
		  WHERE voucher_type = 'Payment Entry'
		    AND company = %(company)s
		    AND party_type = 'Supplier'
		    AND is_cancelled = 0
		  GROUP BY voucher_no
		  HAVING COUNT(*) = 1
		) single ON single.voucher_no = g.voucher_no
		WHERE g.voucher_type = 'Payment Entry'
		  AND g.company = %(company)s
		  AND g.party_type = 'Supplier'
		  AND g.is_cancelled = 0
		GROUP BY g.party
		""",
		{"company": company},
		as_dict=True,
	)
	drift_map = {r["party"]: flt(r["drift"]) for r in drift_rows}

	# Overdue AP per party — ONE batched query for the party set already on the page.
	# outstanding_amount is in the invoice currency, so multiply by conversion_rate to
	# get a comparable base-currency figure. Mirrors list_customers_with_balances.
	overdue_map: dict = {}
	parties = tuple(r["name"] for r in rows)
	if parties:
		overdue_rows = (
			frappe.db.sql(
				"""
			SELECT supplier AS party,
			       COALESCE(SUM(outstanding_amount * conversion_rate), 0) AS overdue_base
			FROM `tabPurchase Invoice`
			WHERE company = %(company)s
			  AND supplier IN %(parties)s
			  AND docstatus = 1
			  AND due_date < %(today)s
			  AND outstanding_amount > 0
			GROUP BY supplier
			""",
				{"company": company, "parties": parties, "today": today()},
				as_dict=True,
			)
			or []
		)
		overdue_map = {r["party"]: flt(r["overdue_base"]) for r in overdue_rows}

	# Did `limit` actually bite? Decide here, BEFORE the Python-side filters below
	# thin the list out: `total_count` ignores those filters, so comparing it with
	# the final row count would flag a filtered-but-complete list as truncated.
	truncated = total_count > len(rows)

	for r in rows:
		r["balance_base"] = flt(r["balance_base"])
		r["balance_acc"] = flt(r["balance_acc"]) + drift_map.get(r["name"], 0.0)
		r["company_currency"] = company_currency
		r["overdue_base"] = overdue_map.get(r["name"], 0.0)
	if cint(only_with_balance):
		rows = [r for r in rows if flt(r["balance_base"]) != 0]
	if cint(only_overdue):
		rows = [r for r in rows if flt(r.get("overdue_base")) > 0]
	return {
		"rows": rows,
		"company_currency": company_currency,
		"total_count": total_count,
		"truncated": truncated,
		"grand_totals": grand_totals,
	}


@frappe.whitelist()
def supplier_ledger(
	company: str,
	supplier: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 1000,
):
	"""Trial-balance-style ledger for a single supplier in `company`.

	Sign convention mirrors `list_suppliers_with_balances`: positive balance
	means we owe the supplier (credit - debit). Account-currency amounts
	mirror the source voucher's originally-entered amount (PE.paid_amount
	/ received_amount), preventing the base÷rate rounding drift baked into
	GL Entry's *_in_account_currency columns."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	limit = max(1, min(5000, int(limit)))

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	from stabler.api.sales import _fetch_party_ledger_rows

	rows = _fetch_party_ledger_rows(
		company=company,
		party_type="Supplier",
		party=supplier,
		to_date=to_d,
	)

	def _before_from(r):
		return from_d is not None and getdate(r["posting_date"]) < from_d

	# Payable sign: positive = we owe (credit − debit).
	opening_base = sum(r["credit"] - r["debit"] for r in rows if _before_from(r))
	opening_acc = sum(
		r["credit_in_account_currency"] - r["debit_in_account_currency"] for r in rows if _before_from(r)
	)
	closing_base = sum(r["credit"] - r["debit"] for r in rows)
	closing_acc = sum(r["credit_in_account_currency"] - r["debit_in_account_currency"] for r in rows)

	window = [r for r in rows if not _before_from(r)][:limit]
	for r in window:
		r["posting_date"] = str(r["posting_date"]) if r["posting_date"] else ""
	_attach_ledger_sources(company, window)

	account_currency = next(
		(r["account_currency"] for r in reversed(window) if r["account_currency"]),
		None,
	)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	return {
		"supplier": supplier,
		"company_currency": company_currency,
		"account_currency": account_currency or company_currency,
		"opening_base": flt(opening_base),
		"opening_acc": flt(opening_acc),
		"closing_base": flt(closing_base),
		"closing_acc": flt(closing_acc),
		"entries": window,
		"from_date": str(from_d) if from_d else None,
		"to_date": str(to_d) if to_d else None,
	}


def _attach_ledger_sources(company: str, rows: list[dict]) -> None:
	"""Name every ledger line by the document the business actually recognises.

	The GL only knows accounting vouchers (Purchase Invoice, Payment Entry). The
	buyer knows Commercial Invoices. A Purchase Invoice born from a CI is
	plumbing — so each row gets, in place, the SOURCE document behind the
	voucher plus the SPA route that opens its own form:

	    source_doctype / source_name / source_label / source_route
	    voucher_route   – the accounting document's own form (fallback)
	    channel         – Bank / Cash for payments (MSA dual-channel)

	Batched: ONE query per doctype over the whole window (never per row — a
	1000-line ledger would otherwise fire 1000 round-trips). Degrades safely:
	a site without the imports columns simply keeps the voucher as its own
	source, and CI links are only emitted where the imports module is on.
	"""
	if not rows:
		return

	pinv_names = {
		r["voucher_no"] for r in rows if r.get("voucher_type") == "Purchase Invoice" and r.get("voucher_no")
	}
	pe_names = {
		r["voucher_no"] for r in rows if r.get("voucher_type") == "Payment Entry" and r.get("voucher_no")
	}

	# Purchase Invoice → Commercial Invoice (imports-gated; the route itself is
	# module-guarded, so a link there would dead-end for a non-imports tenant).
	ci_of: dict[str, str] = {}
	ci_label_of: dict[str, str] = {}
	bill_of: dict[str, str] = {}
	has_ci_col = frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")
	has_cinum_col = frappe.db.has_column("Purchase Invoice", "custom_ci_number")
	imports_on = bool(module_map_for(company).get("imports"))

	ci_doc_map: dict[str, tuple[str, str]] = {}

	if pinv_names:
		fields = ["name", "bill_no"]
		if has_ci_col and imports_on:
			fields.append("custom_commercial_invoice")
		if has_cinum_col and imports_on:
			fields.append("custom_ci_number")

		pi_rows = frappe.get_all(
			"Purchase Invoice",
			filters={"name": ["in", list(pinv_names)]},
			fields=fields,
			limit_page_length=0,
		)

		# The CI map is a company-wide fetch, so it is built only once there is
		# something to resolve against. A payments-only window (the common case
		# when the ledger is filtered to Payment Entry) never pays for it.
		if imports_on and pi_rows:
			for c in frappe.get_all(
				"Commercial Invoice",
				filters={"company": company},
				fields=["name", "ci_number"],
				limit_page_length=0,
			):
				c_name = c["name"]
				c_num = c.get("ci_number") or c_name
				ci_doc_map[c_name] = (c_name, c_num)
				if c.get("ci_number"):
					ci_doc_map[c["ci_number"]] = (c_name, c_num)

		for row in pi_rows:
			p_name = row["name"]
			ref = row.get("custom_commercial_invoice") or row.get("bill_no") or row.get("custom_ci_number")
			if ref and ref in ci_doc_map:
				ci_name, ci_num = ci_doc_map[ref]
				ci_of[p_name] = ci_name
				ci_label_of[p_name] = ci_num
			elif row.get("bill_no"):
				bill_of[p_name] = row["bill_no"]

	# Payment Entry → which channel the money left through (K3 label only).
	stream_of: dict[str, str] = {}
	if pe_names and frappe.db.has_column("Payment Entry", "custom_payment_stream"):
		for row in frappe.get_all(
			"Payment Entry",
			filters={"name": ["in", list(pe_names)]},
			fields=["name", "custom_payment_stream"],
			limit_page_length=0,
		):
			if row.get("custom_payment_stream"):
				stream_of[row["name"]] = row["custom_payment_stream"]

	# Voucher type → SPA form route. Journal Entry has a list page but no
	# per-record form, so it stays None and the drawer remains its detail view.
	routes = {
		"Purchase Invoice": "/purchasing/invoices/",
		"Payment Entry": "/money/payments/",
		"Purchase Order": "/purchasing/orders/",
	}

	for r in rows:
		vtype = r.get("voucher_type") or ""
		vno = r.get("voucher_no") or ""
		base = routes.get(vtype)
		r["voucher_route"] = f"{base}{vno}" if base and vno else None
		r["channel"] = stream_of.get(vno)
		ci = ci_of.get(vno)
		if ci:
			r["source_doctype"] = "Commercial Invoice"
			r["source_name"] = ci
			r["source_label"] = ci_label_of.get(vno) or ci
			r["source_route"] = f"/imports/commercial-invoices/{ci}"
		else:
			r["source_doctype"] = vtype or None
			r["source_name"] = vno or None
			# A hand-entered supplier bill shows its own number, not our PINV id.
			r["source_label"] = bill_of.get(vno) or vno or None
			r["source_route"] = r["voucher_route"]


@frappe.whitelist()
def supplier_detail(name: str, company: str):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not name or not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	_assert_can_read("Supplier", name)
	doc = frappe.get_doc("Supplier", name)

	# AP per transaction currency. Lifetime stays in base currency.
	ap_by_currency = (
		frappe.db.sql(
			"""
		SELECT
		  currency,
		  COALESCE(SUM(outstanding_amount), 0) AS outstanding
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		GROUP BY currency
		HAVING SUM(outstanding_amount) <> 0
		""",
			{"name": name, "company": company},
			as_dict=True,
		)
		or []
	)
	lifetime_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(base_grand_total), 0) AS lifetime
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		""",
		{"name": name, "company": company},
		as_dict=True,
	)
	lifetime_base = flt(lifetime_row[0]["lifetime"]) if lifetime_row else 0.0
	# Lifetime in the currency actually invoiced. Grouping is what makes the
	# figure legal: SUM(grand_total) over a supplier billing in both USD and UZS
	# is a number true in neither. A supplier who bills in one currency gets it
	# shown; a mixed one falls back to base, labelled as base.
	lifetime_by_currency = (
		frappe.db.sql(
			"""
		SELECT currency,
		       COALESCE(SUM(grand_total), 0) AS lifetime
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		GROUP BY currency
		HAVING SUM(grand_total) <> 0
		""",
			{"name": name, "company": company},
			as_dict=True,
		)
		or []
	)
	if len(lifetime_by_currency) == 1:
		lifetime_amount = flt(lifetime_by_currency[0]["lifetime"])
		lifetime_currency = lifetime_by_currency[0]["currency"]
	else:
		lifetime_amount = lifetime_base
		lifetime_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	overdue_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(outstanding_amount), 0) AS overdue
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		  AND due_date < %(today)s
		  AND outstanding_amount > 0
		""",
		{"name": name, "company": company, "today": today()},
		as_dict=True,
	)
	overdue_amount = flt(overdue_row[0]["overdue"]) if overdue_row else 0.0

	last_payment_row = frappe.db.sql(
		"""
		SELECT posting_date
		FROM `tabPayment Entry`
		WHERE party_type = 'Supplier' AND party = %(name)s AND company = %(company)s
		  AND docstatus = 1
		ORDER BY posting_date DESC
		LIMIT 1
		""",
		{"name": name, "company": company},
	)
	last_payment_date = str(last_payment_row[0][0]) if last_payment_row and last_payment_row[0][0] else None

	recent = frappe.db.sql(
		"""
		SELECT name, posting_date, due_date, grand_total, outstanding_amount, status, currency
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s AND docstatus = 1
		ORDER BY posting_date DESC, name DESC
		LIMIT 200
		""",
		{"name": name, "company": company},
		as_dict=True,
	)

	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_group": doc.supplier_group,
		"supplier_type": doc.supplier_type,
		"country": doc.country,
		"default_currency": doc.default_currency,
		"mobile_no": doc.mobile_no,
		"email_id": doc.email_id,
		"tax_id": doc.tax_id,
		"website": doc.website,
		"supplier_details": doc.supplier_details,
		"outstanding_by_currency": [
			{"currency": r["currency"], "amount": flt(r["outstanding"])} for r in ap_by_currency
		],
		"lifetime_base": lifetime_base,
		"lifetime_amount": lifetime_amount,
		"lifetime_currency": lifetime_currency,
		"overdue_amount": overdue_amount,
		"last_payment_date": last_payment_date,
		"recent_invoices": recent,
	}


@frappe.whitelist()
def supplier_import_exposure(supplier: str, company: str) -> dict:
	"""Import position for a supplier — SEPARATE from supplier_detail so the base
	Vendor Center payload is byte-identical for tenants without the imports module.

	Tenant-gated: returns ``{"enabled": False}`` unless the company has the imports
	module on (enable_imports). Everything here is already in GL — the cash/bank
	figures are the payment split by the Payment Entry source-account type, and
	they reconcile to the GL total paid. ``docs_total`` (customs) never appears.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(frappe._("You are not permitted to view suppliers."), frappe.PermissionError)

	# Company-level gate: import-disabled tenants get an inert, empty payload so a
	# stray SPA call can never surface import figures where the module is off.
	if not module_map_for(company).get("imports"):
		return {"enabled": False}
	if not frappe.db.exists("DocType", "Commercial Invoice"):
		return {"enabled": False}

	# Open commitments — Commercial Invoices still in flight (not delivered).
	# Cash/bank earmark columns are guarded so this works before v50 migrates.
	_has_earmark = frappe.db.has_column("Commercial Invoice", "custom_bank_agreed")
	earmark_sel = (
		"ci.custom_bank_agreed, ci.custom_cash_agreed"
		if _has_earmark
		else "0 AS custom_bank_agreed, 0 AS custom_cash_agreed"
	)
	# A CI drops out of virtual exposure once it has a linked Purchase Invoice
	# (WP-I5): the agreed_total then lives on that PInv (draft = pending A/P,
	# submitted = GL A/P), so counting it here too would double-count.
	# The match is on supplier as well as CI: bills from other parties — a
	# transporter's freight invoice, a service fee — can be attributed to the
	# same CI, and one of those must not be mistaken for the goods payable. It
	# would retire the CI's whole agreed_total from virtual exposure while the
	# goods A/P has not been booked at all, silently erasing the commitment.
	_has_pi_ref = frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")
	converted_sel = (
		"""EXISTS(SELECT 1 FROM `tabPurchase Invoice` pi
		          WHERE pi.custom_commercial_invoice = ci.name
		            AND pi.supplier = ci.supplier
		            AND pi.docstatus < 2) AS has_purchase_invoice"""
		if _has_pi_ref
		else "0 AS has_purchase_invoice"
	)
	ci_rows = frappe.db.sql(
		f"""
		SELECT ci.name, ci.ci_number, ci.agreed_total, ci.docs_total, ci.currency,
		       ci.status, {earmark_sel}, {converted_sel}
		FROM `tabCommercial Invoice` ci
		WHERE ci.supplier = %(supplier)s AND ci.company = %(company)s AND ci.docstatus < 2
		ORDER BY ci.ci_date DESC
		LIMIT 200
		""",
		{"supplier": supplier, "company": company},
		as_dict=True,
	)

	# Payments to the supplier, split by the source account's type (Cash / Bank).
	pay_rows = frappe.db.sql(
		"""
		SELECT pe.paid_amount AS amount, acc.account_type AS account_type
		FROM `tabPayment Entry` pe
		JOIN `tabAccount` acc ON acc.name = pe.paid_from
		WHERE pe.party_type = 'Supplier' AND pe.party = %(supplier)s
		  AND pe.company = %(company)s AND pe.docstatus = 1
		""",
		{"supplier": supplier, "company": company},
		as_dict=True,
	)
	gl_total_paid = sum(flt(r.get("amount")) for r in pay_rows)

	summary = _import_exposure.exposure_summary(ci_rows, pay_rows, gl_total_paid)
	return {
		"enabled": True,
		"summary": summary,
		"commitments": [
			{
				"name": r.get("name"),
				"ci_number": r.get("ci_number"),
				"agreed_total": flt(r.get("agreed_total")),
				"currency": r.get("currency"),
				"status": r.get("status"),
			}
			for r in ci_rows
			if (r.get("status") or "") not in ("DELIVERED_TO_UZBEKISTAN", "Cancelled")
			and not r.get("has_purchase_invoice")
		],
	}


@frappe.whitelist()
def list_purchase_invoices(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
	status: str | None = None,
	limit: int = 100,
	tender_only: bool | str = False,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if supplier:
		conds.append("supplier = %(supplier)s")
		params["supplier"] = supplier
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	if cint(tender_only):
		conds.append(
			"""EXISTS (
				SELECT 1 FROM `tabPurchase Invoice Item` pii
				JOIN `tabPurchase Order` po ON po.name = pii.purchase_order
				WHERE pii.parent = `tabPurchase Invoice`.name
				  AND po.company = %(company)s
				  AND po.custom_crm_deal IS NOT NULL
				  AND po.custom_crm_deal != ''
			)"""
		)
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, posting_date, due_date, supplier, supplier_name, bill_no,
		       grand_total, base_grand_total,
		       outstanding_amount,
		       conversion_rate,
		       status, currency, docstatus
		FROM `tabPurchase Invoice`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_invoice_detail(name: str):
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Purchase Invoice", name)
	doc = frappe.get_doc("Purchase Invoice", name)
	_has_dim = frappe.db.has_column("Item", "custom_dimension_mode")

	def _dim_mode(code):
		if not _has_dim or not code:
			return ""
		return frappe.get_cached_value("Item", code, "custom_dimension_mode") or ""

	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"due_date": str(doc.due_date) if doc.due_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"bill_no": doc.bill_no,
		"bill_date": str(doc.bill_date) if doc.bill_date else None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges),
		"grand_total": flt(doc.grand_total),
		"outstanding_amount": flt(doc.outstanding_amount),
		"base_net_total": flt(doc.base_net_total),
		"base_total_taxes_and_charges": flt(doc.base_total_taxes_and_charges),
		"base_grand_total": flt(doc.base_grand_total),
		"base_currency": frappe.db.get_value("Company", doc.company, "default_currency") or "",
		"status": doc.status,
		"docstatus": doc.docstatus,
		"remarks": doc.remarks,
		"update_stock": cint(doc.update_stock),
		"set_warehouse": doc.set_warehouse or "",
		"taxes_and_charges": doc.taxes_and_charges or "",
		"buying_price_list": doc.buying_price_list or "",
		"items": [
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"custom_line_note": getattr(it, "custom_line_note", None) or None,
				"qty": flt(it.qty),
				"uom": it.uom,
				"rate": flt(it.rate),
				"amount": flt(it.amount),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"price_list_rate": flt(it.price_list_rate),
				"purchase_order": it.purchase_order or "",
				"custom_dimension_mode": _dim_mode(it.item_code),
				"custom_length": flt(getattr(it, "custom_length", 0)) or None,
				"custom_width": flt(getattr(it, "custom_width", 0)) or None,
				"custom_height": flt(getattr(it, "custom_height", 0)) or None,
				"custom_pieces": flt(getattr(it, "custom_pieces", 0)) or None,
			}
			for it in (doc.items or [])
		],
		"taxes": [
			{
				"description": t.description,
				"rate": flt(t.rate),
				"tax_amount": flt(t.tax_amount),
			}
			for t in (doc.taxes or [])
		],
		"is_return": cint(doc.is_return),
		"return_against": doc.return_against or "",
		"amended_from": doc.amended_from or "",
		"debit_notes": frappe.db.sql(
			"""
			SELECT name, docstatus FROM `tabPurchase Invoice`
			WHERE return_against = %(name)s AND docstatus < 2
			""",
			{"name": name},
			as_dict=True,
		),
	}


@frappe.whitelist()
def purchase_invoice_print(name: str):
	"""Full payload for the in-SPA printable PI receipt (extends detail with
	company header, in_words, and supplier running balance from GL)."""
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Purchase Invoice", name)
	base = purchase_invoice_detail(name)
	doc = frappe.get_doc("Purchase Invoice", name)
	company_doc = frappe.get_doc("Company", doc.company)
	bal = frappe.db.sql(
		"""SELECT SUM(debit_in_account_currency - credit_in_account_currency)
		   FROM `tabGL Entry`
		   WHERE company=%s AND party_type='Supplier' AND party=%s AND is_cancelled=0""",
		(doc.company, doc.supplier),
	)
	supplier_balance = flt(bal[0][0]) if bal and bal[0][0] is not None else 0.0
	return {
		**base,
		"company_name": company_doc.company_name,
		"company_abbr": company_doc.abbr,
		"company_tax_id": getattr(company_doc, "tax_id", "") or "",
		"discount_amount": flt(doc.discount_amount),
		"in_words": doc.in_words or "",
		"supplier_balance": supplier_balance,
	}


@frappe.whitelist()
def ap_aging(company: str, as_of: str | None = None):
	"""Bucket outstanding Purchase Invoices by age into 0-30/31-60/61-90/90+.

	Grouped by (supplier, currency); totals broken out per currency."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	as_of = getdate(as_of or today())
	rows = frappe.db.sql(
		"""
		SELECT
		  supplier,
		  supplier_name,
		  currency,
		  COUNT(*) AS invoice_count,
		  COALESCE(SUM(outstanding_amount), 0) AS total,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 0 AND 30
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_0_30,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 31 AND 60
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_31_60,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 61 AND 90
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_61_90,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) > 90
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_90_plus
		FROM `tabPurchase Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		GROUP BY supplier, supplier_name, currency
		ORDER BY currency, total DESC
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)
	totals_by_ccy: dict[str, dict] = {}
	for r in rows:
		ccy = r["currency"]
		bucket = totals_by_ccy.setdefault(
			ccy,
			{
				"currency": ccy,
				"total": 0.0,
				"b_0_30": 0.0,
				"b_31_60": 0.0,
				"b_61_90": 0.0,
				"b_90_plus": 0.0,
			},
		)
		bucket["total"] += flt(r["total"])
		bucket["b_0_30"] += flt(r["b_0_30"])
		bucket["b_31_60"] += flt(r["b_31_60"])
		bucket["b_61_90"] += flt(r["b_61_90"])
		bucket["b_90_plus"] += flt(r["b_90_plus"])
	return {
		"rows": rows,
		"totals_by_currency": list(totals_by_ccy.values()),
		"as_of": str(as_of),
	}


VALID_SUPPLIER_TYPES = {"Individual", "Company", "Partnership"}


@frappe.whitelist()
def create_supplier(
	supplier_name: str,
	supplier_type: str = "Company",
	supplier_group: str | None = None,
	country: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
	default_price_list: str | None = None,
	default_currency: str | None = None,
):
	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw("Supplier name is required.")
	if supplier_type not in VALID_SUPPLIER_TYPES:
		frappe.throw(f"Supplier type must be one of: {', '.join(sorted(VALID_SUPPLIER_TYPES))}.")
	if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
		frappe.throw(f"Supplier '{supplier_name}' already exists.")

	if not supplier_group:
		supplier_group = (
			frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
		)
	if not frappe.db.exists("Supplier Group", supplier_group):
		frappe.throw(f"Unknown supplier group: {supplier_group}")
	if country and not frappe.db.exists("Country", country):
		frappe.throw(f"Unknown country: {country}")

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = supplier_name
	doc.supplier_type = supplier_type
	doc.supplier_group = supplier_group
	if country:
		doc.country = country
	if email_id:
		doc.email_id = email_id.strip()
	if mobile_no:
		doc.mobile_no = mobile_no.strip()
	if tax_id:
		doc.tax_id = tax_id.strip()
	if default_price_list:
		if not frappe.db.exists("Price List", default_price_list):
			frappe.throw(f"Unknown price list: {default_price_list}")
		doc.default_price_list = default_price_list
	doc.default_currency = default_currency or ""
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "supplier_name": doc.supplier_name}


@frappe.whitelist()
def get_supplier(name: str):
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	_assert_can_read("Supplier", name)
	doc = frappe.get_doc("Supplier", name)
	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_type": doc.supplier_type or "Company",
		"supplier_group": doc.supplier_group or "",
		"country": doc.country or "",
		"email_id": doc.email_id or "",
		"mobile_no": doc.mobile_no or "",
		"tax_id": doc.tax_id or "",
		"default_price_list": doc.default_price_list or "",
		"default_currency": doc.default_currency or "",
	}


@frappe.whitelist()
def update_supplier(
	name: str,
	supplier_name: str,
	supplier_type: str = "Company",
	supplier_group: str | None = None,
	country: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
	default_price_list: str | None = None,
	default_currency: str | None = None,
):
	_assert_can_write("Supplier", name, "write")
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw("Supplier name is required.")
	if supplier_type not in VALID_SUPPLIER_TYPES:
		frappe.throw(f"Supplier type must be one of: {', '.join(sorted(VALID_SUPPLIER_TYPES))}.")
	if default_price_list and not frappe.db.exists("Price List", default_price_list):
		frappe.throw(f"Unknown price list: {default_price_list}")
	doc = frappe.get_doc("Supplier", name)
	doc.supplier_name = supplier_name
	doc.supplier_type = supplier_type
	if supplier_group:
		doc.supplier_group = supplier_group
	if country:
		doc.country = country
	doc.email_id = (email_id or "").strip()
	doc.mobile_no = (mobile_no or "").strip()
	doc.tax_id = (tax_id or "").strip()
	doc.default_price_list = default_price_list or ""
	doc.default_currency = default_currency or ""
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "supplier_name": doc.supplier_name}


@frappe.whitelist()
def delete_supplier(name: str):
	_assert_can_write("Supplier", name, "delete")
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	frappe.delete_doc("Supplier", name, ignore_permissions=False)
	return {"deleted": name}


def _clean_invoice_items(items) -> list[dict]:
	"""Validate and normalize the PI items payload (shared by create/update)."""
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		disc_pct = flt(row.get("discount_percentage"))
		if not (0 <= disc_pct <= 100):
			frappe.throw(f"Row {idx}: discount_percentage must be between 0 and 100.")
		rate_val = row.get("rate")
		if rate_val not in (None, "") and flt(rate_val) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		if flt(row.get("discount_amount")) < 0:
			frappe.throw(f"Row {idx}: discount_amount cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)
	return cleaned


def _validate_invoice_inputs(
	company: str,
	update_stock: int,
	set_warehouse: str | None,
	currency: str | None,
	conversion_rate,
	price_list: str | None,
	taxes_template: str | None,
) -> float:
	"""Shared create/update validation. Returns the resolved conversion rate."""
	if update_stock and not set_warehouse:
		frappe.throw("Warehouse is required when receiving goods into stock.")
	if set_warehouse and not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(f"Unknown warehouse: {set_warehouse}")
	if currency and not frappe.db.exists("Currency", currency):
		frappe.throw(f"Unknown currency: {currency}")
	if price_list and not frappe.db.exists("Price List", price_list):
		frappe.throw(f"Unknown price list: {price_list}")
	if taxes_template and not frappe.db.exists(
		"Purchase Taxes and Charges Template", {"name": taxes_template, "company": company}
	):
		frappe.throw(f"Unknown purchase tax template: {taxes_template}")

	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	if currency and currency != company_currency:
		rate = flt(conversion_rate)
		if rate <= 0:
			frappe.throw("Exchange rate must be greater than zero for foreign-currency bills.")
		return rate
	# Same currency as the company → rate is 1 by definition.
	return 1.0


def _apply_invoice_payload(
	doc,
	cleaned: list[dict],
	posting_date,
	due_date,
	bill_no,
	bill_date,
	remarks,
	update_stock: int,
	set_warehouse,
	currency,
	rate: float,
	price_list,
	taxes_template,
	commercial_invoice: str | None = None,
	import_truck: str | None = None,
	import_container: str | None = None,
):
	"""Write validated PI fields + item/tax rows onto `doc` (new or draft)."""
	doc.posting_date = getdate(posting_date or today())
	doc.due_date = getdate(due_date) if due_date else None
	doc.bill_no = (bill_no or "").strip() or None
	doc.bill_date = getdate(bill_date) if bill_date else None
	doc.remarks = (remarks or "").strip() or None
	doc.update_stock = 1 if update_stock else 0
	doc.set_warehouse = set_warehouse or None
	if currency:
		doc.currency = currency
		doc.conversion_rate = rate
	doc.buying_price_list = price_list or ""

	if frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice"):
		doc.custom_commercial_invoice = (commercial_invoice or "").strip() or None
	if frappe.db.has_column("Purchase Invoice", "custom_import_truck"):
		doc.custom_import_truck = (import_truck or "").strip() or None
	if frappe.db.has_column("Purchase Invoice", "custom_import_container"):
		doc.custom_import_container = (import_container or "").strip() or None

	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		if update_stock and set_warehouse:
			line.warehouse = set_warehouse
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]
		if row["discount_percentage"]:
			line.discount_percentage = row["discount_percentage"]
		if row["discount_amount"]:
			line.discount_amount = row["discount_amount"]
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	if (
		(commercial_invoice or doc.get("custom_commercial_invoice"))
		and hasattr(doc, "company")
		and doc.company
	):
		try:
			from stabler.stabler.imports_module import hooks as imports_hooks

			lcv_acc = imports_hooks.resolve_lcv_expense_account(doc.company)
			if lcv_acc:
				for line in doc.items:
					acc_type = frappe.db.get_value("Account", line.expense_account, "account_type")
					if acc_type != "Expenses Included In Valuation":
						line.expense_account = lcv_acc
		except Exception:
			pass

	doc.set("taxes", [])
	doc.taxes_and_charges = taxes_template or None
	if taxes_template:
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		for tax_row in get_taxes_and_charges("Purchase Taxes and Charges Template", taxes_template):
			doc.append("taxes", tax_row)


@frappe.whitelist()
def create_purchase_invoice(
	company: str,
	supplier: str,
	items,
	posting_date: str | None = None,
	due_date: str | None = None,
	bill_no: str | None = None,
	bill_date: str | None = None,
	remarks: str | None = None,
	update_stock: int = 0,
	set_warehouse: str | None = None,
	currency: str | None = None,
	conversion_rate=None,
	price_list: str | None = None,
	taxes_template: str | None = None,
	commercial_invoice: str | None = None,
	import_truck: str | None = None,
	import_container: str | None = None,
):
	"""Create a Purchase Invoice as Draft (docstatus=0).

	`items` is a list of dicts with keys: item_code (required), qty, rate, uom,
	discount_percentage, discount_amount.
	When `update_stock` is truthy, `set_warehouse` is required and goods are
	received into stock on submit. Foreign-currency bills require a positive
	`conversion_rate` (1 foreign = X company currency)."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")

	update_stock = cint(update_stock)
	cleaned = _clean_invoice_items(items)
	rate = _validate_invoice_inputs(
		company, update_stock, set_warehouse, currency, conversion_rate, price_list, taxes_template
	)

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = company
	doc.supplier = supplier
	_apply_invoice_payload(
		doc,
		cleaned,
		posting_date,
		due_date,
		bill_no,
		bill_date,
		remarks,
		update_stock,
		set_warehouse,
		currency,
		rate,
		price_list,
		taxes_template,
		commercial_invoice,
		import_truck,
		import_container,
	)
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
	}


@frappe.whitelist()
def update_purchase_invoice(
	name: str,
	supplier: str,
	items,
	posting_date: str | None = None,
	due_date: str | None = None,
	bill_no: str | None = None,
	bill_date: str | None = None,
	remarks: str | None = None,
	update_stock: int = 0,
	set_warehouse: str | None = None,
	currency: str | None = None,
	conversion_rate=None,
	price_list: str | None = None,
	taxes_template: str | None = None,
	modified: str | None = None,
	commercial_invoice: str | None = None,
	import_truck: str | None = None,
	import_container: str | None = None,
):
	"""Replace a draft Purchase Invoice's fields and rows (full-row replace).

	Submitted/cancelled invoices are immutable — use cancel + amend instead."""
	_assert_can_write("Purchase Invoice", name, "write")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft bills can be edited.")
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")

	update_stock = cint(update_stock)
	cleaned = _clean_invoice_items(items)
	rate = _validate_invoice_inputs(
		doc.company, update_stock, set_warehouse, currency, conversion_rate, price_list, taxes_template
	)

	if supplier != doc.supplier:
		doc.supplier = supplier
		# Force set_missing_values to re-resolve the payable account for the
		# new supplier (a stale credit_to can carry the wrong account currency).
		doc.credit_to = None
	_apply_invoice_payload(
		doc,
		cleaned,
		posting_date,
		due_date,
		bill_no,
		bill_date,
		remarks,
		update_stock,
		set_warehouse,
		currency,
		rate,
		price_list,
		taxes_template,
		commercial_invoice,
		import_truck,
		import_container,
	)
	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
	}


@frappe.whitelist()
def delete_purchase_invoice(name: str, modified: str | None = None):
	"""Delete a draft Purchase Invoice. Submitted documents cannot be deleted."""
	_assert_can_write("Purchase Invoice", name, "delete")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	check_concurrency("Purchase Invoice", name, modified)
	docstatus = cint(frappe.db.get_value("Purchase Invoice", name, "docstatus"))
	if docstatus != 0:
		frappe.throw("Only draft bills can be deleted.")
	frappe.delete_doc("Purchase Invoice", name, ignore_permissions=False)
	return {"deleted": name}


@frappe.whitelist()
def list_purchase_tax_templates(company: str):
	"""Purchase tax templates for `company`, each with its tax rows so the UI
	can preview tax/grand totals before the server computes them."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	templates = frappe.db.get_all(
		"Purchase Taxes and Charges Template",
		filters={"company": company, "disabled": 0},
		fields=["name", "title", "is_default"],
		order_by="is_default desc, title asc",
	)
	for tpl in templates:
		tpl["taxes"] = frappe.db.get_all(
			"Purchase Taxes and Charges",
			filters={"parent": tpl["name"], "parenttype": "Purchase Taxes and Charges Template"},
			fields=["charge_type", "description", "rate", "tax_amount"],
			order_by="idx asc",
		)
	return templates


@frappe.whitelist()
def get_purchase_exchange_rate(
	company: str,
	currency: str,
	posting_date: str | None = None,
	supplier: str | None = None,
):
	"""Suggested conversion rate for a foreign-currency bill.

	Sources in priority order: ERPNext Currency Exchange records for the
	posting date, then the supplier's most recent submitted PI in that
	currency. Returns rate=0 when no trustworthy source exists — the UI must
	then require manual entry (never default a foreign rate to 1.0)."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	if not currency or currency == company_currency:
		return {"rate": 1.0, "source": "company"}

	date = getdate(posting_date or today())
	rate = 0.0
	try:
		from erpnext.setup.utils import get_exchange_rate as _erp_rate

		rate = flt(_erp_rate(currency, company_currency, str(date), "for_buying"))
	except Exception:
		rate = 0.0
	# ERPNext falls back to 1.0/0.0 when it has no record — for a foreign
	# currency that is "not found", not a real rate.
	if rate > 0 and rate != 1.0:
		return {"rate": rate, "source": "erpnext", "date": str(date)}

	if supplier:
		row = frappe.db.sql(
			"""
			SELECT conversion_rate
			FROM `tabPurchase Invoice`
			WHERE supplier = %(supplier)s AND company = %(company)s
			  AND currency = %(currency)s AND docstatus = 1
			  AND conversion_rate > 0 AND conversion_rate <> 1
			ORDER BY posting_date DESC, creation DESC
			LIMIT 1
			""",
			{"supplier": supplier, "company": company, "currency": currency},
			as_dict=True,
		)
		if row:
			return {"rate": flt(row[0]["conversion_rate"]), "source": "last_invoice"}

	return {"rate": 0.0, "source": None}


@frappe.whitelist()
def submit_purchase_invoice(name: str, modified: str | None = None):
	"""Submit a Draft Purchase Invoice (docstatus 0 → 1)."""
	_assert_can_write("Purchase Invoice", name, "submit")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus == 1:
		frappe.throw("Invoice is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Invoice is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_purchase_invoice(name: str, modified: str | None = None):
	"""Cancel a Submitted Purchase Invoice (docstatus 1 → 2)."""
	_assert_can_write("Purchase Invoice", name, "cancel")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted invoices can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def amend_purchase_invoice(name: str):
	"""Create a new draft Purchase Invoice as an amendment of a cancelled one."""
	_assert_can_write("Purchase Invoice", name, "cancel")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled purchase invoices can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def create_purchase_return(
	purchase_invoice: str,
	posting_date: str | None = None,
	item_returns=None,
	submit: int = 0,
):
	"""Issue a debit note (is_return=1) against a submitted Purchase Invoice.

	`item_returns` is an optional list of `{item_code, qty}` where qty is
	entered positive (negated internally). Pass nothing to return the full invoice.
	"""
	from frappe.utils import getdate
	from frappe.utils import today as _today
	from frappe.utils.data import flt as _flt

	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))
	# IDOR guard: @frappe.whitelist gates method access only, not record access.
	# Without this, a user could issue (and with submit=1, post) a debit note
	# against another company's invoice by guessing its sequential name.
	_assert_can_read("Purchase Invoice", purchase_invoice)
	src = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if src.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))
	if src.is_return:
		frappe.throw(_("Cannot create a return against a return document."))

	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	doc = make_return_doc("Purchase Invoice", purchase_invoice)
	doc.posting_date = getdate(posting_date or _today())

	if isinstance(item_returns, str):
		try:
			item_returns = frappe.parse_json(item_returns)
		except Exception:
			frappe.throw(_("Invalid item_returns payload"))

	if item_returns:
		src_qty: dict[str, float] = {it.item_code: _flt(it.qty) for it in src.items}
		override: dict[str, float] = {
			row["item_code"]: _flt(row.get("qty", 0))
			for row in (item_returns or [])
			if isinstance(row, dict) and row.get("item_code")
		}
		for line in doc.items:
			requested = override.get(line.item_code)
			if requested is None:
				continue
			clamped = min(abs(requested), abs(src_qty.get(line.item_code, 0)))
			line.qty = -clamped if clamped else line.qty

		non_zero = [ln for ln in doc.items if _flt(ln.qty) != 0]
		if non_zero:
			doc.items = non_zero

	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {
		"name": doc.name,
		"is_return": 1,
		"grand_total": _flt(doc.grand_total),
		"docstatus": doc.docstatus,
		"return_against": purchase_invoice,
	}


@frappe.whitelist()
def list_supplier_groups(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabSupplier Group`
		WHERE is_group = 0
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


# ── Purchase Order helpers ────────────────────────────────────────────────────


def _resolve_buy_price_list(supplier: str) -> str:
	"""Return the supplier's default buying price list, or empty string."""
	return frappe.db.get_value("Supplier", supplier, "default_price_list") or ""


def _lookup_item_buy_price(item_code: str, price_list: str, uom: str | None = None) -> dict | None:
	"""Look up the buying Item Price for the given item + price list."""
	conds = [
		"item_code = %(item_code)s",
		"price_list = %(price_list)s",
		"buying = 1",
	]
	params: dict = {"item_code": item_code, "price_list": price_list}
	if uom:
		conds.append("uom = %(uom)s")
		params["uom"] = uom
	rows = frappe.db.sql(
		f"SELECT price_list_rate FROM `tabItem Price` WHERE {' AND '.join(conds)} LIMIT 1",
		params,
		as_dict=True,
	)
	return rows[0] if rows else None


# ── Purchase Order endpoints ──────────────────────────────────────────────────


@frappe.whitelist()
def list_purchase_orders(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
	status: str | None = None,
	limit: int = 100,
	tender_only: bool | str = False,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("transaction_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("transaction_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if supplier:
		conds.append("supplier = %(supplier)s")
		params["supplier"] = supplier
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	if cint(tender_only):
		conds.append("custom_crm_deal IS NOT NULL AND custom_crm_deal != ''")
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, transaction_date, schedule_date, supplier, supplier_name,
		       grand_total, per_received, per_billed,
		       status, currency, docstatus, set_warehouse
		FROM `tabPurchase Order`
		WHERE {where}
		ORDER BY transaction_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_order_detail(name: str):
	if not name:
		frappe.throw("Purchase order name is required.")
	_assert_can_read("Purchase Order", name)
	doc = frappe.get_doc("Purchase Order", name)
	_has_dim = frappe.db.has_column("Item", "custom_dimension_mode")

	def _dim_mode(code):
		if not _has_dim or not code:
			return ""
		return frappe.get_cached_value("Item", code, "custom_dimension_mode") or ""

	# linked Purchase Invoices created via PO→PI bridge (or manually)
	pi_links = frappe.db.sql(
		"""
		SELECT DISTINCT pi.name, pi.docstatus
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pii.purchase_order = %(name)s AND pi.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	# linked Purchase Receipts created via PO→PR bridge (or manually)
	pr_links = frappe.db.sql(
		"""
		SELECT DISTINCT pr.name, pr.docstatus
		FROM `tabPurchase Receipt Item` pri
		JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
		WHERE pri.purchase_order = %(name)s AND pr.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
		"schedule_date": str(doc.schedule_date) if doc.schedule_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None) or None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"per_received": flt(doc.per_received),
		"per_billed": flt(doc.per_billed),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"amended_from": doc.amended_from or None,
		"remarks": getattr(doc, "terms", None) or None,
		"purchase_invoices": pi_links,
		"purchase_receipts": pr_links,
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"custom_line_note": getattr(it, "custom_line_note", None) or None,
				"warehouse": getattr(it, "warehouse", None) or None,
				"qty": flt(it.qty),
				"received_qty": flt(getattr(it, "received_qty", 0)),
				"billed_amt": flt(getattr(it, "billed_amt", 0)),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"price_list_rate": flt(it.price_list_rate),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"amount": flt(it.amount),
				"schedule_date": str(it.schedule_date) if it.schedule_date else None,
				"custom_dimension_mode": _dim_mode(it.item_code),
				"custom_length": flt(getattr(it, "custom_length", 0)) or None,
				"custom_width": flt(getattr(it, "custom_width", 0)) or None,
				"custom_height": flt(getattr(it, "custom_height", 0)) or None,
				"custom_pieces": flt(getattr(it, "custom_pieces", 0)) or None,
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def create_purchase_order(
	company: str,
	supplier: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	schedule_date: str | None = None,
	remarks: str | None = None,
	auto_submit: int = 1,
	currency: str | None = None,
	price_list: str | None = None,
	deal: str | None = None,
):
	"""Create (and optionally submit) a Purchase Order.

	`set_warehouse` is optional — POs are inbound, no stock-guard needed.
	When `auto_submit` is truthy (default) the PO is submitted immediately.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	if not set_warehouse or not frappe.db.exists("Warehouse", set_warehouse):
		from stabler.api._common import _company_default_warehouse

		set_warehouse = _company_default_warehouse(company)

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	txn_date = getdate(transaction_date or today())
	sched_date = getdate(schedule_date) if schedule_date else txn_date

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		disc_pct = flt(row.get("discount_percentage"))
		if not (0 <= disc_pct <= 100):
			frappe.throw(f"Row {idx}: discount_percentage must be between 0 and 100.")
		rate_val = row.get("rate")
		if rate_val not in (None, "") and flt(rate_val) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		if flt(row.get("discount_amount")) < 0:
			frappe.throw(f"Row {idx}: discount_amount cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)

	doc = frappe.new_doc("Purchase Order")
	doc.company = company
	doc.supplier = supplier
	doc.transaction_date = txn_date
	doc.schedule_date = sched_date
	# Tag the PO to a tender so it appears on the Tender PO control board. Guarded
	# on the custom field (patch v34) so it's a no-op before migrate runs.
	if (
		deal
		and frappe.db.exists("CRM Deal", deal)
		and frappe.db.has_column("Purchase Order", "custom_crm_deal")
	):
		doc.custom_crm_deal = deal
	if set_warehouse:
		doc.set_warehouse = set_warehouse
	if remarks:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	resolved_pl = price_list or _resolve_buy_price_list(supplier)
	if resolved_pl:
		doc.buying_price_list = resolved_pl

	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		line.schedule_date = sched_date
		if set_warehouse:
			line.warehouse = set_warehouse
		rate = row["rate"]
		if not rate and resolved_pl:
			hit = _lookup_item_buy_price(row["item_code"], resolved_pl)
			if hit:
				rate = hit["price_list_rate"]
		if rate:
			line.rate = rate
		if row["uom"]:
			line.uom = row["uom"]
		if row.get("conversion_factor"):
			line.conversion_factor = row["conversion_factor"]
		if row.get("discount_percentage"):
			line.discount_percentage = row["discount_percentage"]
		if row.get("discount_amount"):
			line.discount_amount = row["discount_amount"]
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.insert(ignore_permissions=True)
	pending_approval = False
	approval_request = None
	if cint(auto_submit):
		from stabler.api.approvals import ensure_request_for_doc, requires_approval

		if requires_approval(doc):
			# Maker-checker: keep the PO a Draft and route it to the approvals
			# queue instead of self-submitting. A different user must approve.
			approval_request = ensure_request_for_doc(doc)
			pending_approval = True
		else:
			doc.submit()

	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"pending_approval": pending_approval,
		"approval_request": approval_request,
	}


@frappe.whitelist()
def update_purchase_order(
	name: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	schedule_date: str | None = None,
	remarks: str | None = None,
	currency: str | None = None,
	price_list: str | None = None,
	modified: str | None = None,
):
	"""Update an existing Draft Purchase Order in-place.

	Only docstatus=0 (Draft) orders may be edited — submitted orders are immutable.
	Replaces item lines entirely.
	"""
	_assert_can_write("Purchase Order", name, "write")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft purchase orders can be edited.")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	txn_date = getdate(transaction_date or doc.transaction_date)
	sched_date = getdate(schedule_date) if schedule_date else txn_date

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		disc_pct = flt(row.get("discount_percentage"))
		if not (0 <= disc_pct <= 100):
			frappe.throw(f"Row {idx}: discount_percentage must be between 0 and 100.")
		rate_val = row.get("rate")
		if rate_val not in (None, "") and flt(rate_val) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		if flt(row.get("discount_amount")) < 0:
			frappe.throw(f"Row {idx}: discount_amount cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)

	doc.transaction_date = txn_date
	doc.schedule_date = sched_date
	if set_warehouse:
		doc.set_warehouse = set_warehouse
	else:
		doc.set_warehouse = None

	if remarks is not None:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	resolved_pl = price_list or _resolve_buy_price_list(doc.supplier)
	if resolved_pl:
		doc.buying_price_list = resolved_pl

	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		line.schedule_date = sched_date
		if set_warehouse:
			line.warehouse = set_warehouse
		rate = row["rate"]
		if not rate and resolved_pl:
			hit = _lookup_item_buy_price(row["item_code"], resolved_pl)
			if hit:
				rate = hit["price_list_rate"]
		if rate:
			line.rate = rate
		if row["uom"]:
			line.uom = row["uom"]
		if row.get("conversion_factor"):
			line.conversion_factor = row["conversion_factor"]
		if row.get("discount_percentage"):
			line.discount_percentage = row["discount_percentage"]
		if row.get("discount_amount"):
			line.discount_amount = row["discount_amount"]
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
		"status": doc.status,
	}


@frappe.whitelist()
def submit_purchase_order(name: str, modified: str | None = None):
	"""Submit a draft Purchase Order (docstatus 0 → 1)."""
	_assert_can_write("Purchase Order", name, "submit")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus == 1:
		frappe.throw("Purchase order is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Purchase order is cancelled and cannot be submitted.")

	from stabler.api.approvals import ensure_request_for_doc, requires_approval

	if requires_approval(doc):
		# Route to the approvals queue instead of submitting; a different user
		# must approve. (The before_submit gate is the backstop if anyone tries
		# to submit it directly.)
		req = ensure_request_for_doc(doc)
		return {
			"name": doc.name,
			"docstatus": doc.docstatus,
			"status": doc.status,
			"pending_approval": True,
			"approval_request": req,
		}
	doc.submit()
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"pending_approval": False,
	}


@frappe.whitelist()
def cancel_purchase_order(name: str, modified: str | None = None):
	"""Cancel a submitted Purchase Order (docstatus 1 → 2)."""
	_assert_can_write("Purchase Order", name, "cancel")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def amend_purchase_order(name: str):
	"""Create a new draft Purchase Order as an amendment of a cancelled one."""
	_assert_can_write("Purchase Order", name, "cancel")
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled purchase orders can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def create_purchase_invoice_from_po(name: str):
	"""Create a draft Purchase Invoice from a submitted Purchase Order.

	Uses ERPNext's make_purchase_invoice mapper which automatically sets
	po_detail + purchase_order on each PI item row and handles partial billing.
	"""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	_assert_can_read("Purchase Order", name)
	po = frappe.get_doc("Purchase Order", name)
	if po.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be invoiced.")
	from erpnext.buying.doctype.purchase_order.purchase_order import (
		make_purchase_invoice as _make_pi,
	)

	doc = _make_pi(name)
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_order": name,
	}


# ── Purchase Receipt endpoints ────────────────────────────────────────────────


@frappe.whitelist()
def list_purchase_receipts(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
	status: str | None = None,
	limit: int = 100,
	tender_only: bool | str = False,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if supplier:
		conds.append("supplier = %(supplier)s")
		params["supplier"] = supplier
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	if cint(tender_only):
		conds.append(
			"""EXISTS (
				SELECT 1 FROM `tabPurchase Receipt Item` pri
				JOIN `tabPurchase Order` po ON po.name = pri.purchase_order
				WHERE pri.parent = `tabPurchase Receipt`.name
				  AND po.company = %(company)s
				  AND po.custom_crm_deal IS NOT NULL
				  AND po.custom_crm_deal != ''
			)"""
		)
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, posting_date, supplier, supplier_name,
		       grand_total, per_billed,
		       status, currency, docstatus, set_warehouse
		FROM `tabPurchase Receipt`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_receipt_detail(name: str):
	if not name:
		frappe.throw("Purchase receipt name is required.")
	_assert_can_read("Purchase Receipt", name)
	doc = frappe.get_doc("Purchase Receipt", name)
	# linked Purchase Invoices created via PR→PI bridge (or manually)
	pi_links = frappe.db.sql(
		"""
		SELECT DISTINCT pi.name, pi.docstatus
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pii.purchase_receipt = %(name)s AND pi.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	# linked Landed Cost Vouchers referencing this receipt
	lcv_links = frappe.db.sql(
		"""
		SELECT DISTINCT lcv.name, lcv.docstatus
		FROM `tabLanded Cost Purchase Receipt` lpr
		JOIN `tabLanded Cost Voucher` lcv ON lcv.name = lpr.parent
		WHERE lpr.receipt_document_type = 'Purchase Receipt'
		  AND lpr.receipt_document = %(name)s AND lcv.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None) or None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"base_grand_total": flt(doc.base_grand_total),
		"per_billed": flt(doc.per_billed),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"amended_from": doc.amended_from or None,
		"remarks": getattr(doc, "remarks", None) or None,
		"purchase_invoices": pi_links,
		"landed_cost_vouchers": lcv_links,
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"warehouse": getattr(it, "warehouse", None) or None,
				"qty": flt(it.qty),
				"rejected_qty": flt(getattr(it, "rejected_qty", 0)),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"amount": flt(it.amount),
				"billed_amt": flt(getattr(it, "billed_amt", 0)),
				"purchase_order": getattr(it, "purchase_order", None) or None,
				"landed_cost_voucher_amount": flt(getattr(it, "landed_cost_voucher_amount", 0)),
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def create_purchase_receipt_from_po(name: str, items=None):
	"""Create a draft Purchase Receipt from a submitted Purchase Order.

	Uses ERPNext's make_purchase_receipt mapper, which maps only rows with
	pending qty (qty - received_qty) and sets purchase_order_item on each row.

	`items` (optional) enables partial receiving: a list of
	{"po_detail": <PO item row name>, "qty": <qty to receive>}.
	Rows not listed are dropped; requested qty is capped at the pending qty.
	"""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	_assert_can_read("Purchase Order", name)
	po = frappe.get_doc("Purchase Order", name)
	if po.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be received.")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if items is not None and (not isinstance(items, list) or not items):
		frappe.throw("Invalid items payload.")

	from erpnext.buying.doctype.purchase_order.purchase_order import (
		make_purchase_receipt as _make_pr,
	)

	doc = _make_pr(name)
	if not doc.get("items"):
		frappe.throw("Nothing left to receive on this purchase order.")

	if items:
		requested: dict[str, float] = {}
		for idx, row in enumerate(items, start=1):
			po_detail = (row or {}).get("po_detail")
			if not po_detail:
				frappe.throw(f"Row {idx}: po_detail is required.")
			qty = flt(row.get("qty"))
			if qty <= 0:
				frappe.throw(f"Row {idx}: qty must be greater than zero.")
			requested[po_detail] = qty

		mapped = {r.purchase_order_item: r for r in doc.items}
		unknown = [d for d in requested if d not in mapped]
		if unknown:
			frappe.throw("These order rows have nothing pending to receive: " + ", ".join(unknown))

		kept = []
		for po_detail, qty in requested.items():
			row = mapped[po_detail]
			row.qty = min(qty, flt(row.qty))  # cap at pending
			kept.append(row)
		doc.items = kept
		for i, row in enumerate(doc.items, start=1):
			row.idx = i

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_order": name,
		"docstatus": doc.docstatus,
	}


@frappe.whitelist()
def create_purchase_receipt(
	company: str,
	supplier: str,
	items,
	set_warehouse: str,
	posting_date: str | None = None,
	currency: str | None = None,
	remarks: str | None = None,
):
	"""Create a draft Purchase Receipt directly (no Purchase Order).

	A receipt moves stock, so `set_warehouse` is required.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	if not set_warehouse:
		frappe.throw("Warehouse is required — a receipt moves stock into it.")
	if not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(f"Unknown warehouse: {set_warehouse}")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		if row.get("rate") not in (None, "") and flt(row.get("rate")) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"conversion_factor": flt(row.get("conversion_factor")) or None,
			}
		)

	doc = frappe.new_doc("Purchase Receipt")
	doc.company = company
	doc.supplier = supplier
	doc.posting_date = getdate(posting_date or today())
	doc.set_warehouse = set_warehouse
	if currency:
		doc.currency = currency
	if remarks:
		doc.remarks = remarks.strip()

	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		line.warehouse = set_warehouse
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]
		if row["conversion_factor"]:
			line.conversion_factor = row["conversion_factor"]

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
	}


@frappe.whitelist()
def submit_purchase_receipt(name: str):
	"""Submit a draft Purchase Receipt (docstatus 0 → 1) — this moves stock."""
	_assert_can_write("Purchase Receipt", name, "submit")
	if not name:
		frappe.throw("Purchase receipt name is required.")
	doc = frappe.get_doc("Purchase Receipt", name)
	if doc.docstatus == 1:
		frappe.throw("Purchase receipt is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Purchase receipt is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_purchase_receipt(name: str):
	"""Cancel a submitted Purchase Receipt (docstatus 1 → 2) — reverses stock."""
	_assert_can_write("Purchase Receipt", name, "cancel")
	if not name:
		frappe.throw("Purchase receipt name is required.")
	doc = frappe.get_doc("Purchase Receipt", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted purchase receipts can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def create_purchase_invoice_from_pr(name: str):
	"""Create a draft Purchase Invoice from a submitted Purchase Receipt.

	The receipt already moved stock, so the bill must NOT move it again:
	update_stock is forced to 0 (ERPNext also guards this server-side).
	"""
	if not name or not frappe.db.exists("Purchase Receipt", name):
		frappe.throw(f"Unknown Purchase Receipt: {name}")
	_assert_can_read("Purchase Receipt", name)
	pr = frappe.get_doc("Purchase Receipt", name)
	if pr.docstatus != 1:
		frappe.throw("Only submitted purchase receipts can be billed.")
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
		make_purchase_invoice as _make_pi,
	)

	doc = _make_pi(name)
	doc.update_stock = 0
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_receipt": name,
	}


# ──────────────────────────────────────────────────────────────────────────── #
# GR/IR — goods received, supplier invoice missing (ADR-107).
# ──────────────────────────────────────────────────────────────────────────── #
#: The Company field holding the SRBNB account (ERPNext v15 Company doctype,
#: Link -> Account, label "Stock Received But Not Billed"). It is the same field
#: ERPNext's own Purchase Receipt GL posting reads, which is why the report
#: reconciles against it and not against some account picked by name.
_SRBNB_COMPANY_FIELD = "stock_received_but_not_billed"


def _srbnb_account(company: str) -> str | None:
	"""The company's Stock Received But Not Billed account, or None if unset.

	Primary source is the Company field. A company set up before that default
	was filled can still be resolved from its chart of accounts by
	``account_type``, which ERPNext stamps on the account itself — but only when
	the match is unambiguous, because reconciling against the wrong account is
	worse than reporting no reconciliation at all.
	"""
	account = None
	if frappe.db.has_column("Company", _SRBNB_COMPANY_FIELD):
		account = frappe.get_cached_value("Company", company, _SRBNB_COMPANY_FIELD)
	if account:
		return account
	matches = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"account_type": "Stock Received But Not Billed",
			"is_group": 0,
			"disabled": 0,
		},
		pluck="name",
		limit=2,
	)
	return matches[0] if len(matches) == 1 else None


def _srbnb_reconciliation(company: str, as_of, total_unbilled: float, comparable: bool) -> dict:
	"""Reconcile this report against the SRBNB ledger — the point of the report.

	Sign convention: SRBNB is a liability. A Purchase Receipt credits it, the
	Purchase Invoice debits it. ``gl_balance`` is therefore normalised
	CREDIT-POSITIVE (``SUM(credit - debit)``, cancelled entries excluded) so it
	is directly comparable to ``total_unbilled``, which is also positive. A clean
	company reads ``gl_balance ~= total_unbilled`` and ``difference ~= 0``.

	``difference = gl_balance - total_unbilled`` is always company-wide: it
	ignores the endpoint's ``supplier`` / ``bucket`` filters, because the
	identity it tests is a company-level one and comparing a filtered subset
	against the whole ledger would manufacture a break out of a UI filter.

	What a non-zero difference accuses:

	* **positive** (ledger above the report) — something credited SRBNB outside
	  the receipt chain. A Journal Entry posted straight to the account (ADR-107
	  forbids it), or a Purchase Invoice submitted with ``update_stock = 1``,
	  which posts its own SRBNB leg while no receipt carries the ``per_billed``
	  that would clear it.
	* **negative** (report above the ledger) — the report over-states: a return
	  receipt debited SRBNB and returns are out of this report's scope, or a
	  receipt was billed by an invoice that never wrote ``per_billed`` back, or
	  taxes make the proportional ``per_billed`` split a poor proxy for the real
	  SRBNB leg on that receipt.

	``comparable`` is what keeps that accusation off a date the two sides do not
	share. ``per_billed`` is current state, not history: a back-dated ``as_of``
	cuts off later receipts and ages the rest correctly, but bills raised since
	then are already reflected, so the list answers *unbilled now* while the
	ledger answers *owed then*. Their difference is then the invoicing done in
	between, and printing it as a break accuses an accountant of doing their job.
	When ``comparable`` is False this returns ``difference: None`` and leaves
	``gl_balance`` at its real value — both numbers stay visible, only the
	subtraction is withheld.

	``None`` rather than a number the SPA agrees not to render, because this is
	whitelisted API surface: a second consumer reading ``difference`` must not be
	handed a figure that is arithmetically valid and semantically wrong. The
	honest fix is to derive billing state as of the cut-off from Purchase Invoice
	Items instead of ``per_billed``, which would also correct which rows appear;
	that is a separate change, and this flag is what keeps the report truthful
	until it lands.

	An unconfigured account (or a caller without GL Entry read access) returns
	``account: None`` with zeros rather than throwing: the receipt list is still
	the useful half of the report. ``difference`` is only meaningful when
	``account`` is set.
	"""
	if not frappe.has_permission("GL Entry", "read"):
		return {"account": None, "gl_balance": 0.0, "difference": 0.0, "comparable": True}
	account = _srbnb_account(company)
	if not account:
		return {"account": None, "gl_balance": 0.0, "difference": 0.0, "comparable": True}
	balance = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(credit - debit), 0)
			FROM `tabGL Entry`
			WHERE company = %(company)s
			  AND account = %(account)s
			  AND is_cancelled = 0
			  AND posting_date <= %(as_of)s
			""",
			{"company": company, "account": account, "as_of": as_of},
		)[0][0]
	)
	return {
		"account": account,
		"gl_balance": round(balance, 2),
		"difference": round(balance - flt(total_unbilled), 2) if comparable else None,
		"comparable": comparable,
	}


def _unbilled_scan(where: str, params: dict) -> list[dict]:
	"""Money-only pass over the whole filtered set, for totals that are not per-page.

	Three numeric columns per row, so the aggregate stays correct across every
	page while the page query itself stays bounded. The arithmetic deliberately
	happens in ``_unbilled_receipts`` rather than in SQL: the ``per_billed``
	clamps (blank, over-100, negative) are the part that must be unit-tested, and
	expressing them twice — once in a SUM, once in Python for the rows — is how
	the two numbers drift apart.
	"""
	return _unbilled_receipts.annotate_rows(
		frappe.db.sql(
			f"""
			SELECT pr.base_grand_total, pr.per_billed,
			       DATEDIFF(%(as_of)s, pr.posting_date) AS age_days
			FROM `tabPurchase Receipt` pr
			WHERE {where}
			""",
			params,
			as_dict=True,
		)
	)


@frappe.whitelist()
def unbilled_receipts(
	company: str,
	supplier: str | None = None,
	as_of: str | None = None,
	bucket: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
) -> dict:
	"""Age the goods this company received and never billed, and reconcile to SRBNB.

	Submitted Purchase Receipts (``docstatus = 1``) posted on or before ``as_of``
	that are not fully billed, aged into 0-30 / 31-60 / 61-90 / 90+ days and
	valued at what is still unbilled. Each row can be turned into a draft
	Purchase Invoice with ``create_purchase_invoice_from_pr``.

	Scope notes, all of them deliberate:

	* ``COALESCE(per_billed, 0) < 100`` — a NULL ``per_billed`` makes the plain
	  comparison NULL, i.e. false, which would drop the never-touched receipts:
	  the most exposed rows in the report.
	* Return receipts (``is_return``) are excluded when the column exists on this
	  site; a credit note is not unbilled exposure. They still move the SRBNB
	  ledger, so they are one of the things ``srbnb.difference`` can accuse.
	* ``posting_date <= as_of`` matches the cut-off used for the GL balance, but
	  only for the receipt's own date. Billing state comes from ``per_billed``,
	  which carries no date, so the two halves cover the same period only when
	  ``as_of`` is today or later; ``srbnb.comparable`` says which run this is.
	* ``status`` is deliberately NOT filtered, unlike ``list_purchase_receipts``.
	  A receipt manually set to *Closed*, or one carrying *Return Issued*, still
	  holds its SRBNB credit in the ledger; hiding it from the report would only
	  move that balance into ``srbnb.difference`` and blame the ledger for it.
	* Imports receipts arrive one per truck, so a single shipment shows as
	  several rows — that is the physical truth, not duplication.

	``totals`` and every bucket are COMPANY currency (``base_grand_total``);
	transaction currencies cannot be summed. Per-row ``grand_total`` stays in the
	row's own ``currency`` for display, alongside its ``base_grand_total``.

	``supplier`` and ``bucket`` are optional filters and narrow ``rows`` and
	``totals`` together; ``srbnb`` stays company-wide (see
	``_srbnb_reconciliation``). Rows are oldest-first — most at risk first.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Purchase Receipt", "read"):
		frappe.throw(_("Not permitted to read Purchase Receipt."), frappe.PermissionError)
	as_of = getdate(as_of or today())
	# Both sides as ISO strings: this predicate lives in the frappe-free module,
	# and frappe returns today() as str but getdate() as date.
	comparable = _unbilled_receipts.reconciliation_comparable(str(as_of), str(getdate(today())))
	start = max(cint(limit_start), 0)
	page_length = min(max(cint(limit_page_length) or 50, 1), 200)

	base_conds = [
		"pr.company = %(company)s",
		"pr.docstatus = 1",
		"pr.posting_date <= %(as_of)s",
		"COALESCE(pr.per_billed, 0) < 100",
	]
	if frappe.db.has_column("Purchase Receipt", "is_return"):
		base_conds.append("COALESCE(pr.is_return, 0) = 0")
	base_params: dict = {"company": company, "as_of": as_of}

	conds = list(base_conds)
	params = dict(base_params)
	if supplier:
		conds.append("pr.supplier = %(supplier)s")
		params["supplier"] = supplier
	if bucket:
		if bucket not in _unbilled_receipts.BUCKETS:
			frappe.throw(_("Unknown bucket: {0}").format(bucket), frappe.ValidationError)
		age_min, age_max = _unbilled_receipts.BUCKET_BOUNDS[bucket]
		if age_min is not None:
			conds.append("DATEDIFF(%(as_of)s, pr.posting_date) >= %(age_min)s")
			params["age_min"] = age_min
		if age_max is not None:
			conds.append("DATEDIFF(%(as_of)s, pr.posting_date) <= %(age_max)s")
			params["age_max"] = age_max
	where = " AND ".join(conds)

	scanned = _unbilled_scan(where, params)
	totals = _unbilled_receipts.summarise(scanned)

	page_params = {**params, "limit": page_length, "start": start}
	rows = _unbilled_receipts.annotate_rows(
		frappe.db.sql(
			f"""
			SELECT pr.name, pr.supplier, pr.supplier_name, pr.posting_date, pr.currency,
			       pr.grand_total, pr.base_grand_total, pr.per_billed,
			       DATEDIFF(%(as_of)s, pr.posting_date) AS age_days
			FROM `tabPurchase Receipt` pr
			WHERE {where}
			ORDER BY pr.posting_date ASC, pr.name ASC
			LIMIT %(limit)s OFFSET %(start)s
			""",
			page_params,
			as_dict=True,
		)
	)
	for row in rows:
		row["grand_total"] = flt(row.get("grand_total"))
		row["base_grand_total"] = flt(row.get("base_grand_total"))
		row["per_billed"] = flt(row.get("per_billed"))

	# The reconciliation is a company-level identity, so it is measured against
	# the unfiltered total even when the screen is showing one supplier or bucket.
	company_total = totals["total_unbilled"]
	if supplier or bucket:
		base_where = " AND ".join(base_conds)
		company_totals = _unbilled_receipts.summarise(_unbilled_scan(base_where, base_params))
		company_total = company_totals["total_unbilled"]

	return {
		"rows": rows,
		"totals": totals,
		"srbnb": _srbnb_reconciliation(company, as_of, company_total, comparable),
		"as_of": str(as_of),
		"company_currency": frappe.get_cached_value("Company", company, "default_currency") or "",
		"has_more": start + len(rows) < len(scanned),
	}


@frappe.whitelist()
def payables_cockpit(company: str):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	# Current total payables balance (credit - debit)
	current_total = flt(
		frappe.db.sql(
			"""
		SELECT COALESCE(SUM(credit - debit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND is_cancelled = 0
		""",
			{"company": company},
		)[0][0]
	)

	# 8-week trend (running balance at the end of each of the last 8 weeks)
	from datetime import datetime, timedelta

	from frappe.utils import getdate

	current_date = getdate(today())
	weeks = []
	for i in range(8):
		date_at_end = current_date - timedelta(days=i * 7)
		weeks.append(date_at_end)
	weeks.reverse()

	trend = []
	for w_end in weeks:
		change_since = flt(
			frappe.db.sql(
				"""
			SELECT COALESCE(SUM(credit - debit), 0)
			FROM `tabGL Entry`
			WHERE company = %(company)s AND party_type = 'Supplier' AND posting_date > %(w_end)s AND is_cancelled = 0
			""",
				{"company": company, "w_end": w_end},
			)[0][0]
		)
		trend.append(round(current_total - change_since, 2))

	# Payments paid today (debit side for Supplier)
	paid_today = flt(
		frappe.db.sql(
			"""
		SELECT COALESCE(SUM(debit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND posting_date = %(today)s AND is_cancelled = 0
		""",
			{"company": company, "today": today()},
		)[0][0]
	)

	# Top 10 creditors
	eps = money_epsilon(frappe.get_cached_value("Company", company, "default_currency"))
	top_creditors_raw = (
		frappe.db.sql(
			"""
		SELECT party AS name, COALESCE(SUM(credit - debit), 0) AS balance
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND is_cancelled = 0
		GROUP BY party
		HAVING SUM(credit - debit) > %(eps)s
		ORDER BY balance DESC
		LIMIT 10
		""",
			{"company": company, "eps": eps},
			as_dict=True,
		)
		or []
	)

	for creditor in top_creditors_raw:
		creditor["supplier_name"] = (
			frappe.db.get_value("Supplier", creditor["name"], "supplier_name") or creditor["name"]
		)
		creditor["balance"] = flt(creditor["balance"])

	return {
		"total_payable": current_total,
		"payments_paid_today": paid_today,
		"trend_8_weeks": trend,
		"top_creditors": top_creditors_raw,
	}


# ──────────────────────────────────────────────────────────────────────────── #
# Tender sourcing (F3) — compare Supplier Quotations collected for one tender.
# ──────────────────────────────────────────────────────────────────────────── #
@frappe.whitelist()
def tender_quotations(deal: str) -> dict:
	"""Supplier Quotations tagged to a CRM Deal, side-by-side for comparison.

	Returns one row per quotation with the supplier's country and the base-currency
	total (the apples-to-apples figure), flags the cheapest, and surfaces the
	procurement-policy checks: at least 5 quotations from at least 2 countries.
	Gated to the deal's company having the tender module enabled.
	"""
	if not frappe.db.exists("CRM Deal", deal):
		frappe.throw(frappe._("Unknown deal: {0}").format(deal))
	company = (
		frappe.db.get_value("CRM Deal", deal, "company")
		or frappe.defaults.get_user_default("Company")
		or (frappe.get_all("Company", pluck="name", limit=1) or [None])[0]
	)
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	if not module_map_for(company).get("tender"):
		frappe.throw(
			frappe._("Tender module is not enabled for {0}.").format(company), frappe.PermissionError
		)

	base_ccy = frappe.get_cached_value("Company", company, "default_currency")
	if not frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		return {
			"rows": [],
			"base_currency": base_ccy,
			"count": 0,
			"countries": 0,
			"has_min_5": False,
			"has_2_countries": False,
		}

	fields = [
		"name",
		"supplier",
		"supplier_name",
		"currency",
		"grand_total",
		"base_grand_total",
		"valid_till",
		"status",
		"transaction_date",
		"total_qty",
	]
	if frappe.db.has_column("Supplier Quotation", "custom_landed_charges"):
		fields.append("custom_landed_charges")

	sqs = frappe.get_all(
		"Supplier Quotation",
		filters={"custom_crm_deal": deal, "docstatus": ["<", 2]},
		fields=fields,
		order_by="base_grand_total asc",
		limit_page_length=0,
	)
	# Supplier → country (for the 2-country policy check).
	suppliers = list({s["supplier"] for s in sqs if s.get("supplier")})
	country_map = {}
	if suppliers:
		for s in frappe.get_all("Supplier", filters={"name": ["in", suppliers]}, fields=["name", "country"]):
			country_map[s["name"]] = s.get("country") or ""

	raw_rows = []
	for s in sqs:
		base_total = flt(s.get("base_grand_total")) or flt(s.get("grand_total"))
		raw_rows.append(
			{
				"name": s["name"],
				"supplier": s["supplier"],
				"supplier_name": s.get("supplier_name") or s["supplier"],
				"country": country_map.get(s["supplier"], ""),
				"currency": s.get("currency"),
				"grand_total": flt(s.get("grand_total")),
				"base_grand_total": base_total,
				"base_total": base_total,
				"valid_till": str(s.get("valid_till") or ""),
				"status": s.get("status"),
				"transaction_date": str(s.get("transaction_date") or ""),
				"qty": flt(s.get("total_qty")),
				"custom_landed_charges": s.get("custom_landed_charges"),
			}
		)

	from stabler.api._landed import rank_quotations_landed

	ranked_res = rank_quotations_landed(raw_rows)
	rows = ranked_res["quotations"]

	for r in rows:
		# Preserve backward compatibility for legacy callers reading `cheapest`:
		# if landed estimates are complete, cheapest means cheapest landed; otherwise sticker price.
		r["cheapest"] = bool(
			r.get("is_cheapest_landed") if ranked_res["estimate_complete"] else r.get("is_cheapest_price")
		)

	countries = {r["country"] for r in rows if r["country"]}
	return {
		"rows": rows,
		"base_currency": base_ccy,
		"count": len(rows),
		"countries": len(countries),
		"has_min_5": len(rows) >= 5,
		"has_2_countries": len(countries) >= 2,
		"cheapest_price_quote": ranked_res["cheapest_price_quote"],
		"cheapest_landed_quote": ranked_res["cheapest_landed_quote"],
		"estimate_complete": ranked_res["estimate_complete"],
		"missing_estimates": ranked_res["missing_estimates"],
	}


@frappe.whitelist()
def get_vendor_category_items(vendor: str, category: str) -> list[dict]:
	"""Items configured for a supplier + category (Stabler Vendor Category).

	RECONSTRUCTED (WP-310): the original uncommitted version of this function was
	lost during a tooling accident and rebuilt from the doctype schema — review
	against the caller before relying on it. Returns each mapped item's code,
	name, stock UOM, boxes-per-container and kg-per-box so the purchasing UI can
	pre-fill lines for a known vendor category.
	"""
	if not frappe.has_permission("Stabler Vendor Category", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not vendor or not category:
		return []
	parent = frappe.db.get_value(
		"Stabler Vendor Category",
		{"vendor": vendor, "category_name": category, "is_active": 1},
		"name",
	)
	if not parent:
		return []
	rows = frappe.get_all(
		"Stabler Vendor Category Item",
		filters={"parent": parent, "parenttype": "Stabler Vendor Category"},
		fields=["item_code", "boxes_per_container", "box_kg"],
		order_by="idx asc",
	)
	for r in rows:
		r["item_name"] = frappe.db.get_value("Item", r["item_code"], "item_name") or r["item_code"]
		r["stock_uom"] = frappe.db.get_value("Item", r["item_code"], "stock_uom") or ""
	return rows


@frappe.whitelist()
def list_supplier_quotations(supplier: str, company: str) -> list[dict]:
	"""List all Supplier Quotations for a supplier, including custom_crm_deal title and amounts.

	Used by the Supplier detail panel ('Quotations' tab) in Suppliers.vue.

	Company is mandatory: a site carries several companies, and an optional
	filter would have listed every one of them the moment the caller left the
	argument out.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier or not frappe.db.exists("Supplier", supplier):
		return []

	filters = {"supplier": supplier, "company": company, "docstatus": ["<", 2]}

	fields = [
		"name",
		"supplier",
		"supplier_name",
		"currency",
		"grand_total",
		"base_grand_total",
		"valid_till",
		"status",
		"transaction_date",
	]
	if frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		fields.append("custom_crm_deal")

	sqs = frappe.get_all(
		"Supplier Quotation",
		filters=filters,
		fields=fields,
		order_by="transaction_date desc, creation desc",
		limit_page_length=100,
	)

	deal_ids = list({s["custom_crm_deal"] for s in sqs if s.get("custom_crm_deal")})
	deal_map = {}
	if deal_ids and frappe.db.exists("DocType", "CRM Deal"):
		fields_deal = ["name"]
		if frappe.db.has_column("CRM Deal", "organization"):
			fields_deal.append("organization")
		if frappe.db.has_column("CRM Deal", "lead_name"):
			fields_deal.append("lead_name")
		for d in frappe.get_all("CRM Deal", filters={"name": ["in", deal_ids]}, fields=fields_deal):
			deal_map[d["name"]] = d.get("organization") or d.get("lead_name") or d["name"]

	for s in sqs:
		s["grand_total"] = flt(s.get("grand_total"))
		s["base_grand_total"] = flt(s.get("base_grand_total")) or s["grand_total"]
		deal_id = s.get("custom_crm_deal")
		if deal_id:
			s["deal_label"] = deal_map.get(deal_id, deal_id)

	return sqs


@frappe.whitelist()
def supplier_quotation_history(supplier, company=None):
	"""Supplier quotation history with derived award result (won/lost/open).

	Uses `frappe.get_list` to enforce record-level user permissions on Supplier
	Quotation, and fetches approved sourcing decisions in a separate batch query
	to avoid row duplication when multiple decision records exist per deal.
	"""
	if not company:
		frappe.throw(_("Company is required."), frappe.ValidationError)
	_assert_company_scope(company)
	selected_company = company
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(_("You are not permitted to view suppliers."), frappe.PermissionError)

	supplier_name = str(supplier or "").strip()
	if not supplier_name:
		return {"rows": [], "count": 0}

	fields = [
		"name",
		"grand_total",
		"base_grand_total",
		"currency",
		"status",
		"valid_till",
		"transaction_date",
	]
	has_deal = frappe.db.has_column("Supplier Quotation", "custom_crm_deal")
	if has_deal:
		fields.append("custom_crm_deal")

	sqs = frappe.get_list(
		"Supplier Quotation",
		filters={"supplier": supplier_name, "company": selected_company, "docstatus": ["<", 2]},
		fields=fields,
		order_by="transaction_date desc, name desc",
		limit_page_length=500,
	)

	deals = list({s["custom_crm_deal"] for s in sqs if s.get("custom_crm_deal")})
	latest_decision = {}
	if deals and frappe.db.exists("DocType", "Tender Sourcing Decision"):
		tsds = frappe.get_list(
			"Tender Sourcing Decision",
			filters={"deal": ["in", deals], "company": selected_company, "status": "Approved"},
			fields=["deal", "selected_quotation", "modified", "creation"],
			order_by="modified desc, creation desc",
			limit_page_length=500,
		)
		for tsd in tsds:
			deal = tsd.get("deal")
			if deal and deal not in latest_decision:
				latest_decision[deal] = tsd.get("selected_quotation")

	for s in sqs:
		s["deal"] = s.get("custom_crm_deal")
		s["grand_total"] = flt(s.get("grand_total"))
		s["base_grand_total"] = flt(s.get("base_grand_total")) or s["grand_total"]
		deal_id = s.get("deal")
		if deal_id in latest_decision:
			winner = latest_decision[deal_id]
			s["result"] = "won" if winner == s["name"] else "lost"
		else:
			s["result"] = "open"

	return {"rows": sqs, "count": len(sqs)}


@frappe.whitelist()
def supplier_rfq_history(supplier, company=None):
	"""Requests for Quotation raised to this supplier, with lot and response facts.

	Queries `Request for Quotation Supplier` to find RFQs where this supplier
	was asked, retrieves parent RFQs scoped to company, and determines whether
	the supplier has responded with a quotation.
	"""
	if not company:
		frappe.throw(_("Company is required."), frappe.ValidationError)
	_assert_company_scope(company)
	selected_company = company
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(_("You are not permitted to view suppliers."), frappe.PermissionError)

	supplier_name = str(supplier or "").strip()
	if not supplier_name:
		return {"rows": [], "count": 0}

	if not frappe.db.exists("DocType", "Request for Quotation Supplier"):
		return {"rows": [], "count": 0}

	rfq_names = frappe.db.sql_list(
		"""
		SELECT DISTINCT parent
		FROM `tabRequest for Quotation Supplier`
		WHERE supplier = %(supplier)s AND parenttype = 'Request for Quotation'
		""",
		{"supplier": supplier_name},
	)
	if not rfq_names:
		return {"rows": [], "count": 0}

	fields = [
		"name",
		"transaction_date",
		"schedule_date",
		"status",
		"docstatus",
	]
	has_deal = frappe.db.has_column("Request for Quotation", "custom_crm_deal")
	if has_deal:
		fields.append("custom_crm_deal")

	rfqs = frappe.get_list(
		"Request for Quotation",
		filters={"name": ["in", rfq_names], "company": selected_company, "docstatus": ["<", 2]},
		fields=fields,
		order_by="transaction_date desc, name desc",
		limit_page_length=500,
	)

	deal_names = list({r["custom_crm_deal"] for r in rfqs if r.get("custom_crm_deal")})
	deal_labels = {}
	if deal_names and frappe.db.exists("DocType", "CRM Deal"):
		deals = frappe.get_all(
			"CRM Deal",
			filters={"name": ["in", deal_names]},
			fields=["name", "organization", "lead_name"],
		)
		for d in deals:
			deal_labels[d["name"]] = d.get("organization") or d.get("lead_name") or d["name"]

	sq_deals = set()
	if deal_names and frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		sq_deals = set(
			frappe.db.sql_list(
				"""
				SELECT DISTINCT custom_crm_deal
				FROM `tabSupplier Quotation`
				WHERE supplier = %(supplier)s
				  AND company = %(company)s
				  AND custom_crm_deal IN %(deals)s
				  AND docstatus < 2
				""",
				{"supplier": supplier_name, "company": selected_company, "deals": deal_names},
			)
		)

	for r in rfqs:
		deal = r.get("custom_crm_deal")
		r["deal"] = deal
		r["deal_label"] = deal_labels.get(deal, deal)
		r["responded"] = bool(deal and deal in sq_deals)

	return {"rows": rfqs, "count": len(rfqs)}


@frappe.whitelist()
def create_po_from_quotation(quotation: str, company: str | None = None) -> dict:
	"""Bridge an approved tender award to a draft ERP Purchase Order.

	Validates company scope, permissions, and SQ attachment to a tender lot.
	Idempotent: returns existing draft PO if one already exists for this lot + supplier.
	"""
	_require_company(company)
	selected_company = _assert_company_scope(company)

	if not frappe.db.exists("Supplier Quotation", quotation):
		frappe.throw(_("Supplier Quotation not found: {0}").format(quotation), frappe.DoesNotExistError)

	sq = frappe.get_doc("Supplier Quotation", quotation)
	if sq.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)

	if not frappe.has_permission("Supplier Quotation", "read", doc=sq):
		frappe.throw(_("Not permitted to read quotation."), frappe.PermissionError)

	if not frappe.has_permission("Purchase Order", "create"):
		frappe.throw(_("Not permitted to create Purchase Order."), frappe.PermissionError)

	if sq.docstatus == 2:
		frappe.throw(_("Cannot create Purchase Order from cancelled quotation."), frappe.ValidationError)

	deal = getattr(sq, "custom_crm_deal", None) or ""
	if not deal:
		frappe.throw(_("Quotation is not linked to a tender lot."), frappe.ValidationError)

	# Idempotent guard: check for existing draft PO for this deal and supplier
	has_deal_field = frappe.db.has_column("Purchase Order", "custom_crm_deal")
	if has_deal_field:
		existing_pos = frappe.get_list(
			"Purchase Order",
			filters={
				"company": selected_company,
				"supplier": sq.supplier,
				"custom_crm_deal": deal,
				"docstatus": ["<", 2],
			},
			fields=["name"],
			limit_page_length=1,
		)
		if existing_pos:
			return {"name": existing_pos[0]["name"], "existing": True}

	sq_items = sq.get("items") or []
	if not sq_items:
		frappe.throw(_("This quotation has no lines."), frappe.ValidationError)

	po = frappe.new_doc("Purchase Order")
	po.company = selected_company
	po.supplier = sq.supplier
	po.currency = sq.currency or frappe.db.get_value("Company", selected_company, "default_currency") or "USD"
	po.transaction_date = today()
	po.schedule_date = str(sq.valid_till or today())
	if has_deal_field:
		po.custom_crm_deal = deal

	warehouse = _company_default_warehouse(selected_company)

	for item in sq_items:
		item_code = item.get("item_code") if isinstance(item, dict) else getattr(item, "item_code", "")
		item_name = (
			item.get("item_name") if isinstance(item, dict) else getattr(item, "item_name", "")
		) or item_code
		qty = flt(item.get("qty") if isinstance(item, dict) else getattr(item, "qty", 1.0)) or 1.0
		uom = (item.get("uom") if isinstance(item, dict) else getattr(item, "uom", "")) or ""
		rate = flt(item.get("rate") if isinstance(item, dict) else getattr(item, "rate", 0.0))
		amount = flt(item.get("amount") if isinstance(item, dict) else getattr(item, "amount", 0.0)) or (
			qty * rate
		)
		item_schedule_date = (
			item.get("schedule_date") if isinstance(item, dict) else getattr(item, "schedule_date", None)
		)
		schedule_date = str(item_schedule_date or sq.valid_till or today())
		item_warehouse = (
			item.get("warehouse") if isinstance(item, dict) else getattr(item, "warehouse", None)
		) or warehouse

		po.append(
			"items",
			{
				"item_code": item_code,
				"item_name": item_name,
				"qty": qty,
				"uom": uom,
				"rate": rate,
				"amount": amount,
				"schedule_date": schedule_date,
				"warehouse": item_warehouse,
			},
		)

	po.flags.ignore_permissions = False
	if hasattr(po, "set_missing_values"):
		po.set_missing_values()
	if hasattr(po, "calculate_taxes_and_totals"):
		po.calculate_taxes_and_totals()

	po.insert()
	return {"name": po.name, "existing": False}
