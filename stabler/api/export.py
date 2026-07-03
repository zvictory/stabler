"""Professional XLSX export endpoint + report registry for Stabler.

One endpoint, one registry — every report exports consistently. The endpoint
re-runs the existing report function server-side (so permissions, company scope
and submitted-doc filters are enforced exactly as in the UI), then hands the
shaped {columns, rows, totals, meta} to the styled writer in
stabler/utils/excel_export.py.

NEVER trusts client row data — official exports always re-query.
"""

from __future__ import annotations

import inspect
import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from stabler.utils.excel_export import (
	build_financial_statement_workbook,
	build_ledger_workbook,
	build_report_workbook,
	normalize_frappe_columns,
	report_filename,
	workbook_to_bytes,
)


def _financial_bold(row) -> bool:
	"""Section roots (indent 0) and 'Total …' lines render bold in statements."""
	if not isinstance(row, dict):
		return False
	if int(row.get("indent") or 0) == 0:
		return True
	first = next((v for v in row.values() if isinstance(v, str)), "")
	return first.strip().lower().startswith("total")

#: Roles that may export everything (admins).
_ADMIN_ROLES = {"System Manager", "Stabler Admin"}
#: Roles allowed to see cost/margin/profit.
_FINANCE_ROLES = {"Accounts Manager", "Accounts User", "Payroll Manager", "System Manager", "Stabler Admin"}

# ── Report registry ──────────────────────────────────────────────────────────
# Each report reuses an existing shaped report function (returns columns/rows/
# totals/meta). `sensitive` reports are role-gated + audit-logged.
REPORT_EXPORTS: dict[str, dict] = {
	"sales_by_customer": {
		"title": "Sales by Customer",
		"source": "stabler.api.reports.sales_by_customer",
		"filename": "Sales_by_Customer",
		"roles": None,
		"sensitive": False,
	},
	"sales_by_customer_detail": {
		"title": "Sales by Customer – Detail",
		"source": "stabler.api.reports.sales_by_customer_detail",
		"filename": "Sales_by_Customer_Detail",
		"roles": None,
		"sensitive": False,
	},
	"customer_balance_summary": {
		"title": "Customer Balance Summary",
		"source": "stabler.api.reports.customer_balance_summary",
		"filename": "Customer_Balance_Summary",
		"roles": None,
		"sensitive": False,
	},
	"customer_balance_detail": {
		"title": "Customer Ledger",
		"source": "stabler.api.reports.customer_balance_detail",
		"filename": "Customer_Ledger",
		"roles": None,
		"sensitive": False,
	},
	"sales_by_item": {
		"title": "Sales by Item",
		"source": "stabler.api.reports.sales_by_item",
		"filename": "Sales_by_Item",
		"roles": None,
		"sensitive": False,
	},
	"sales_by_item_detail": {
		"title": "Sales by Item – Detail",
		"source": "stabler.api.reports.sales_by_item_detail",
		"filename": "Sales_by_Item_Detail",
		"roles": None,
		"sensitive": False,
	},
	"purchases_by_supplier": {
		"title": "Purchases by Supplier",
		"source": "stabler.api.reports.purchases_by_supplier",
		"filename": "Purchases_by_Supplier",
		"roles": None,
		"sensitive": False,
	},
	"inventory_aging": {
		"title": "Inventory Aging",
		"source": "stabler.api.reports.inventory_aging",
		"filename": "Inventory_Aging",
		"roles": None,
		"sensitive": False,
	},
	"inventory_expiry": {
		"title": "Inventory Expiry",
		"source": "stabler.api.reports.inventory_expiry",
		"filename": "Inventory_Expiry",
		"roles": None,
		"sensitive": False,
	},
	"item_abc": {
		"title": "Item ABC Analysis",
		"source": "stabler.api.reports.item_abc",
		"filename": "Item_ABC",
		"roles": None,
		"sensitive": False,
	},
	"customer_abc": {
		"title": "Customer ABC Analysis",
		"source": "stabler.api.reports.customer_abc",
		"filename": "Customer_ABC",
		"roles": None,
		"sensitive": False,
	},
	"supplier_abc": {
		"title": "Supplier ABC Analysis",
		"source": "stabler.api.reports.supplier_abc",
		"filename": "Supplier_ABC",
		"roles": None,
		"sensitive": False,
	},
	# /sales/reports page tabs — these endpoints return plain lists, so columns
	# and totals are declared here (list_source). Money columns are per-row currency
	# (mixed), so only currency-agnostic / base-currency columns are totalled.
	"sales_report_by_customer": {
		"title": "Sales by Customer (period)",
		"source": "stabler.api.sales.sales_report_by_customer",
		"filename": "Sales_by_Customer",
		"list_source": True,
		"columns": [
			{"key": "customer_name", "label": "Customer", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "gross", "label": "Gross", "type": "money", "align": "end"},
			{"key": "returns_amt", "label": "Returns", "type": "money", "align": "end"},
			{"key": "total", "label": "Net", "type": "money", "align": "end"},
			{"key": "outstanding", "label": "Outstanding", "type": "money", "align": "end"},
			{"key": "cogs", "label": "COGS", "type": "money", "align": "end"},
			{"key": "margin", "label": "Margin", "type": "money", "align": "end"},
			{"key": "margin_pct", "label": "Margin %", "type": "percent", "align": "end"},
		],
		"total_keys": ["invoice_count", "cogs", "margin"],
		"roles": None, "sensitive": False,
	},
	"sales_report_by_item": {
		"title": "Sales by Item (period)",
		"source": "stabler.api.sales.sales_report_by_item",
		"filename": "Sales_by_Item",
		"list_source": True,
		"columns": [
			{"key": "item_name", "label": "Item", "type": "text"},
			{"key": "item_code", "label": "Item Code", "type": "text"},
			{"key": "item_group", "label": "Group", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "qty", "label": "Qty", "type": "number", "align": "end"},
			{"key": "gross", "label": "Gross", "type": "money", "align": "end"},
			{"key": "returns_amt", "label": "Returns", "type": "money", "align": "end"},
			{"key": "revenue", "label": "Revenue", "type": "money", "align": "end"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "cogs", "label": "COGS", "type": "money", "align": "end"},
			{"key": "margin", "label": "Margin", "type": "money", "align": "end"},
			{"key": "margin_pct", "label": "Margin %", "type": "percent", "align": "end"},
		],
		"total_keys": ["qty", "invoice_count", "cogs", "margin"],
		"roles": None, "sensitive": False,
	},
	"sales_report_by_date": {
		"title": "Sales Trend",
		"source": "stabler.api.sales.sales_report_by_date",
		"filename": "Sales_Trend",
		"list_source": True,
		"columns": [
			{"key": "period", "label": "Period", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "total", "label": "Total", "type": "money", "align": "end"},
			{"key": "outstanding", "label": "Outstanding", "type": "money", "align": "end"},
		],
		"total_keys": ["invoice_count"],
		"roles": None, "sensitive": False,
	},
	"sales_report_by_salesperson": {
		"title": "Sales by Salesperson",
		"source": "stabler.api.sales.sales_report_by_salesperson",
		"filename": "Sales_by_Salesperson",
		"list_source": True,
		"columns": [
			{"key": "sales_person", "label": "Salesperson", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "total", "label": "Total", "type": "money", "align": "end"},
		],
		"total_keys": ["invoice_count"],
		"roles": None, "sensitive": False,
	},
	"sales_report_orders": {
		"title": "Sales Orders (period)",
		"source": "stabler.api.sales.sales_report_orders",
		"filename": "Sales_Orders",
		"list_source": True,
		"columns": [
			{"key": "customer_name", "label": "Customer", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "order_count", "label": "Orders", "type": "int", "align": "end"},
			{"key": "booked", "label": "Booked", "type": "money", "align": "end"},
			{"key": "to_deliver", "label": "To deliver", "type": "money", "align": "end"},
			{"key": "to_bill", "label": "To bill", "type": "money", "align": "end"},
		],
		"total_keys": ["order_count"],
		"roles": None, "sensitive": False,
	},
	# Sensitive — exposes cost/margin → finance roles only, audit-logged.
	"gross_margin_by_item": {
		"title": "Gross Margin by Item",
		"source": "stabler.api.reports.gross_margin_by_item",
		"filename": "Gross_Margin_by_Item",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	"gross_margin_by_customer": {
		"title": "Gross Margin by Customer",
		"source": "stabler.api.reports.gross_margin_by_customer",
		"filename": "Gross_Margin_by_Customer",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	# Financial statements — Frappe Query Reports run via money.run_report (which
	# enforces the ALLOWED_REPORTS allow-list). Hierarchical → financial template.
	"profit_and_loss": {
		"title": "Profit and Loss Statement",
		"query_report": "Profit and Loss Statement",
		"template": "financial",
		"filename": "Profit_and_Loss",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	"balance_sheet": {
		"title": "Balance Sheet",
		"query_report": "Balance Sheet",
		"template": "financial",
		"filename": "Balance_Sheet",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	"trial_balance": {
		"title": "Trial Balance",
		"query_report": "Trial Balance",
		"template": "financial",
		"filename": "Trial_Balance",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	"cash_flow": {
		"title": "Cash Flow",
		"query_report": "Cash Flow",
		"template": "financial",
		"filename": "Cash_Flow",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	"general_ledger": {
		"title": "General Ledger",
		"query_report": "General Ledger",
		"template": "table",
		"filename": "General_Ledger",
		"roles": _FINANCE_ROLES,
		"sensitive": True,
	},
	# Aging — source returns {rows, ...}; buckets are per-currency so not cross-totalled.
	"ar_aging": {
		"title": "AR Aging (Receivables)",
		"source": "stabler.api.sales.ar_aging",
		"filename": "AR_Aging",
		"list_source": True,
		"rows_key": "rows",
		"columns": [
			{"key": "customer_name", "label": "Customer", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "b_0_30", "label": "0–30", "type": "money", "align": "end"},
			{"key": "b_31_60", "label": "31–60", "type": "money", "align": "end"},
			{"key": "b_61_90", "label": "61–90", "type": "money", "align": "end"},
			{"key": "b_90_plus", "label": "90+", "type": "money", "align": "end"},
			{"key": "total", "label": "Total", "type": "money", "align": "end"},
		],
		"total_keys": ["invoice_count"],
		"roles": None, "sensitive": False,
	},
	"ap_aging": {
		"title": "AP Aging (Payables)",
		"source": "stabler.api.purchasing.ap_aging",
		"filename": "AP_Aging",
		"list_source": True,
		"rows_key": "rows",
		"columns": [
			{"key": "supplier_name", "label": "Supplier", "type": "text"},
			{"key": "currency", "label": "Currency", "type": "text"},
			{"key": "invoice_count", "label": "Invoices", "type": "int", "align": "end"},
			{"key": "b_0_30", "label": "0–30", "type": "money", "align": "end"},
			{"key": "b_31_60", "label": "31–60", "type": "money", "align": "end"},
			{"key": "b_61_90", "label": "61–90", "type": "money", "align": "end"},
			{"key": "b_90_plus", "label": "90+", "type": "money", "align": "end"},
			{"key": "total", "label": "Total", "type": "money", "align": "end"},
		],
		"total_keys": ["invoice_count"],
		"roles": None, "sensitive": False,
	},
	# Ledgers — opening/movements/running/closing via the ledger template.
	"customer_ledger": {
		"title": "Customer Ledger",
		"source": "stabler.api.sales.customer_ledger",
		"filename": "Customer_Ledger",
		"template": "ledger",
		"ledger_sign": "dr",
		"party_filter": "customer",
		"roles": None, "sensitive": False,
	},
	"supplier_ledger": {
		"title": "Supplier Ledger",
		"source": "stabler.api.purchasing.supplier_ledger",
		"filename": "Supplier_Ledger",
		"template": "ledger",
		"ledger_sign": "cr",
		"party_filter": "supplier",
		"roles": None, "sensitive": False,
	},
}


def _roles():
	return set(frappe.get_roles())


def _check_roles(spec: dict):
	allowed = spec.get("roles")
	if not allowed:
		return
	if not (_roles() & (set(allowed) | _ADMIN_ROLES)):
		frappe.throw(_("Not permitted to export this report."), frappe.PermissionError)


def _call_source(source: str, filters: dict) -> dict:
	"""Call the registered report function with only the kwargs it accepts."""
	fn = frappe.get_attr(source)
	sig = inspect.signature(fn)
	kwargs = {k: v for k, v in (filters or {}).items() if k in sig.parameters and v not in (None, "")}
	return fn(**kwargs) or {}


def _header_meta(spec: dict, filters: dict, shaped_meta: dict) -> list:
	"""The metadata block printed above the table."""
	company = filters.get("company") or ""
	company_name = frappe.get_cached_value("Company", company, "company_name") if company else ""
	d_from = filters.get("from_date") or shaped_meta.get("from")
	d_to = filters.get("to_date") or shaped_meta.get("to")
	date_range = f"{d_from} → {d_to}" if (d_from and d_to) else (d_from or d_to or "")
	# Filters echoed (minus the always-present ones) so the reader sees the scope.
	extra = {k: v for k, v in (filters or {}).items() if k not in ("company", "from_date", "to_date") and v not in (None, "")}
	meta = [
		("Company", company_name or company),
		("Report", spec["title"]),
		("Date range", date_range),
		("Currency", shaped_meta.get("currency")),
		("Basis", shaped_meta.get("basis")),
		("Filters", ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else "—"),
		("Generated at", now_datetime().strftime("%Y-%m-%d %H:%M")),
		("Generated by", frappe.session.user),
		("Source", "Stabler / ERPStable"),
		("Note", shaped_meta.get("note")),
	]
	return meta


@frappe.whitelist()
def export_report_xlsx(report_key: str, filters: dict | str | None = None):
	"""Stream a styled .xlsx for `report_key` with the given `filters`.

	Re-runs the report server-side (permission + company enforced), builds the
	workbook, and writes it to frappe.response as a binary download.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)

	spec = REPORT_EXPORTS.get(report_key)
	if not spec:
		frappe.throw(_("Unknown report: {0}").format(report_key), frappe.ValidationError)
	_check_roles(spec)

	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			frappe.throw(_("Invalid filters payload."))
	filters = dict(filters or {})

	totals = {}
	shaped_meta = {}
	filename_suffix = None

	if spec.get("template") == "ledger":
		# Party ledger: opening/movements/running/closing via the ledger template.
		data = _call_source(spec["source"], filters)
		rows = data.get("entries") or []
		# Hide pure FX-revaluation rows (base-only "Exchange Gain Or Loss", zero
		# account-currency movement) so the exported ledger matches the on-screen
		# ledger. Opening/closing come from the source unchanged.
		rows = [
			r for r in rows
			if abs(flt(r.get("debit_in_account_currency"))) > 0.005
			or abs(flt(r.get("credit_in_account_currency"))) > 0.005
		]
		party = filters.get(spec.get("party_filter", "")) or ""
		shaped_meta = {
			"currency": data.get("account_currency") or "",
			"from": data.get("from_date"),
			"to": data.get("to_date"),
		}
		wb = build_ledger_workbook(
			title=f"{spec['title']} — {party}" if party else spec["title"],
			entries=rows,
			opening=data.get("opening_acc") or 0,
			header_meta=_header_meta(spec, filters, shaped_meta),
			sheet_name=spec["title"],
			sign=spec.get("ledger_sign", "dr"),
		)
		filename_suffix = party
	else:
		if spec.get("query_report"):
			# Frappe Query Report (GL / P&L / Balance Sheet / Trial Balance / Cash Flow).
			# Reuse money.run_report — it enforces the ALLOWED_REPORTS allow-list.
			from stabler.api.money import run_report

			res = run_report(spec["query_report"], filters) or {}
			columns = normalize_frappe_columns(res.get("columns") or [])
			rows = res.get("result") or []
		elif spec.get("list_source"):
			shaped = _call_source(spec["source"], filters)
			if spec.get("rows_key"):
				rows = shaped.get(spec["rows_key"]) or []
			else:
				rows = shaped if isinstance(shaped, list) else (shaped.get("rows") or [])
			columns = spec["columns"]
			for k in spec.get("total_keys", []):
				totals[k] = sum(float(r.get(k) or 0) for r in rows)
		else:
			shaped = _call_source(spec["source"], filters)
			columns = shaped.get("columns") or []
			rows = shaped.get("rows") or shaped.get("result") or []
			totals = shaped.get("totals") or {}
			shaped_meta = dict(shaped.get("meta") or {})
			# Use the most common per-row currency (original transaction currency)
			# rather than the company base currency stored in meta.currency.
			row_ccys = [r.get("currency") for r in rows if r.get("currency")]
			if row_ccys:
				from collections import Counter
				shaped_meta["currency"] = Counter(row_ccys).most_common(1)[0][0]

		if spec.get("template") == "financial":
			wb = build_financial_statement_workbook(
				title=spec["title"], columns=columns, rows=rows,
				header_meta=_header_meta(spec, filters, shaped_meta),
				sheet_name=spec["title"], bold_predicate=_financial_bold,
			)
		else:
			wb = build_report_workbook(
				title=spec["title"], columns=columns, rows=rows, totals=totals,
				header_meta=_header_meta(spec, filters, shaped_meta),
				sheet_name=spec["title"],
			)

	# Audit sensitive exports.
	if spec.get("sensitive"):
		try:
			frappe.get_doc({
				"doctype": "Activity Log",
				"subject": f"Exported sensitive report: {spec['title']}",
				"operation": "Export",
				"status": "Success",
				"remark": json.dumps({
					"report_key": report_key,
					"filters": filters,
					"company": filters.get("company"),
					"row_count": len(rows),
					"format": "xlsx",
				}, default=str)[:1000],
			}).insert(ignore_permissions=True)
		except Exception:
			pass  # auditing must never block the export

	filename = report_filename(
		spec["filename"],
		filters.get("from_date") or shaped_meta.get("from"),
		filters.get("to_date") or shaped_meta.get("to"),
		filename_suffix,
	)
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = workbook_to_bytes(wb)
	frappe.local.response.type = "binary"


@frappe.whitelist()
def list_exportable_reports() -> list:
	"""Report keys the current user is allowed to export (for the UI)."""
	out = []
	for key, spec in REPORT_EXPORTS.items():
		allowed = spec.get("roles")
		if allowed and not (_roles() & (set(allowed) | _ADMIN_ROLES)):
			continue
		out.append({"report_key": key, "title": spec["title"], "sensitive": spec.get("sensitive", False)})
	return out
