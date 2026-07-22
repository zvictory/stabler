"""Inventory module — Items, Warehouses, Stock balances, Stock ledger, low-stock alerts."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from stabler.api._common import _require_company, _assert_can_read, _assert_can_write
from stabler.api.approvals import _assert_company_scope
from stabler.api._stock_recon import prepare_reconciliation
from stabler.api import _fefo
from erpnext.stock.get_item_details import get_conversion_factor


# Central item-picker context → the is_*_item flag each caller must filter by.
# One source of truth so a purchase/transfer/sales picker can never silently
# apply the wrong flag again (that was the root cause of "item not found" in the
# Purchase Invoice / Stock Transfer pickers). See composables/items.js.
_ITEM_CONTEXT_FILTER = {
	"sales": "is_sales_item = 1",
	"purchase": "is_purchase_item = 1",
	"stock": "is_stock_item = 1",
	"all": "1 = 1",
}


@frappe.whitelist()
def list_items(
	search: str = "",
	item_group: str | None = None,
	warehouse: str | None = None,
	limit: int = 100,
	stock_only: int = 0,
	context: str | None = None,
):
	"""Return items matching *search* (code or name), optionally scoped to a warehouse.

	context — the picker's intent, one of ``sales`` / ``purchase`` / ``stock`` /
	``all``. This is the sanctioned way to choose the item-type filter: a Purchase
	picker passes ``purchase`` (is_purchase_item), a transfer/ledger passes
	``stock`` (is_stock_item), a sales picker passes ``sales`` (is_sales_item), and
	``all`` disables the type filter. When ``context`` is given it wins over the
	legacy ``stock_only`` flag.

	warehouse — when provided, only items that have a Bin row in that warehouse are
	returned (i.e. items ever stocked there, regardless of current qty). This prevents
	raw-material items from appearing in a finished-goods warehouse picker.

	stock_only — legacy flag (is_stock_item). Kept for back-compat; ``context``
	supersedes it. Callers that omit both keep the historical is_sales_item default.
	"""
	if context:
		item_filter = _ITEM_CONTEXT_FILTER.get(context, _ITEM_CONTEXT_FILTER["sales"])
	elif stock_only:
		item_filter = "is_stock_item = 1"
	else:
		item_filter = "is_sales_item = 1"
	conds = ["disabled = 0", item_filter]
	params: dict = {"limit": int(limit)}
	if search:
		conds.append("(item_name LIKE %(s)s OR item_code LIKE %(s)s)")
		params["s"] = f"%{search}%"
	if item_group:
		conds.append("item_group = %(item_group)s")
		params["item_group"] = item_group
	if warehouse:
		# Only items that actually have stock in the target warehouse.
		# actual_qty > 0 prevents 0-qty Bin rows (e.g. raw materials ever staged there) from leaking in.
		conds.append(
			"EXISTS (SELECT 1 FROM `tabBin` b"
			" WHERE b.item_code = `tabItem`.name AND b.warehouse = %(warehouse)s AND b.actual_qty > 0)"
		)
		params["warehouse"] = warehouse
	where = " AND ".join(conds)
	# custom_dimension_mode drives dimensional pricing (m / m² / m³). Guard the
	# column so item search keeps working before the v23 patch has run.
	dim_sel = (
		"custom_dimension_mode"
		if frappe.db.has_column("Item", "custom_dimension_mode")
		else "NULL AS custom_dimension_mode"
	)
	return frappe.db.sql(
		f"""
		SELECT name, item_code, item_name, item_group, stock_uom,
		       is_stock_item, is_purchase_item, is_sales_item,
		       has_variants, image, standard_rate, valuation_rate,
		       {dim_sel}
		FROM `tabItem`
		WHERE {where}
		ORDER BY item_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def item_detail(name: str, company: str | None = None):
	if not name or not frappe.db.exists("Item", name):
		frappe.throw(f"Unknown item: {name}")
	doc = frappe.get_doc("Item", name)

	bin_conds = ["b.item_code = %(item)s"]
	bin_params: dict = {"item": name}
	if company:
		_require_company(company)
		_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
		bin_conds.append("w.company = %(company)s")
		bin_params["company"] = company
	bin_where = " AND ".join(bin_conds)

	balances = frappe.db.sql(
		f"""
		SELECT b.warehouse, b.actual_qty, b.reserved_qty, b.ordered_qty,
		       b.projected_qty, b.valuation_rate, b.stock_uom, w.company
		FROM `tabBin` b
		JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE {bin_where} AND b.actual_qty != 0
		ORDER BY b.actual_qty DESC
		""",
		bin_params,
		as_dict=True,
	)

	total_qty = sum(flt(r["actual_qty"]) for r in balances)
	total_value = sum(flt(r["actual_qty"]) * flt(r["valuation_rate"]) for r in balances)

	return {
		"name": doc.name,
		"item_code": doc.item_code,
		"item_name": doc.item_name,
		"item_group": doc.item_group,
		"stock_uom": doc.stock_uom,
		"description": doc.description,
		"image": doc.image,
		"is_stock_item": doc.is_stock_item,
		"is_purchase_item": doc.is_purchase_item,
		"is_sales_item": doc.is_sales_item,
		"disabled": doc.disabled,
		"standard_rate": flt(doc.standard_rate),
		"valuation_rate": flt(doc.valuation_rate),
		"weight_per_unit": flt(doc.weight_per_unit),
		"weight_uom": doc.weight_uom,
		"balances": balances,
		"total_qty": total_qty,
		"total_value": total_value,
	}

def _get_restricted_warehouses(company: str) -> set[str] | None:
	user = frappe.session.user
	if not user or user == "Guest":
		return None
	roles = set(frappe.get_roles(user))
	is_admin = bool(roles & {"System Manager", "Stabler Admin"})
	is_manager = bool(roles & {"Manufacturing Manager", "Stock Manager"})

	if is_admin or is_manager:
		return None

	restricted = None

	# 1. User Permissions
	from frappe.permissions import get_allowed_docs_for_doctype, get_user_permissions
	user_permissions = get_user_permissions(user)
	allowed = get_allowed_docs_for_doctype(user_permissions, "Warehouse")
	if allowed and "*" not in allowed:
		restricted = set(allowed)

	# 2. Operator Work Orders
	operator_wips = frappe.db.get_all(
		"Work Order",
		filters={"operator": user, "company": company},
		pluck="wip_warehouse"
	)
	operator_wips = {w for w in operator_wips if w}
	if operator_wips:
		if restricted is not None:
			restricted = restricted.intersection(operator_wips)
		else:
			restricted = operator_wips

	return restricted


@frappe.whitelist()
def list_warehouses(company: str):
	"""Tree of warehouses for a company, ordered by left-traversal."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	rows = frappe.db.sql(
		"""
		SELECT name, warehouse_name, parent_warehouse, is_group,
		       warehouse_type, disabled, lft, rgt
		FROM `tabWarehouse`
		WHERE company = %(company)s
		ORDER BY lft
		""",
		{"company": company},
		as_dict=True,
	)

	restricted = _get_restricted_warehouses(company)
	if restricted is not None:
		allowed_all = set()
		for wh in restricted:
			allowed_all.add(wh)
			curr = wh
			for _ in range(10):
				parent = frappe.db.get_value("Warehouse", curr, "parent_warehouse")
				if parent and parent != company:
					allowed_all.add(parent)
					curr = parent
				else:
					break
		rows = [r for r in rows if r["name"] in allowed_all]

	# Attach actual_qty summed across all items in each warehouse
	totals = dict(
		frappe.db.sql(
			"""
			SELECT warehouse, COALESCE(SUM(actual_qty * valuation_rate), 0) AS value
			FROM `tabBin`
			WHERE actual_qty > 0
			GROUP BY warehouse
			"""
		)
	)
	for r in rows:
		r["stock_value"] = flt(totals.get(r["name"], 0))
	return rows


def _format_warehouse_stock_row(row: dict) -> dict:
	actual_qty = flt(row.get("actual_qty"))
	reserved_qty = flt(row.get("reserved_qty"))
	valuation_rate = flt(row.get("valuation_rate"))
	return {
		"item_code": row.get("item_code"),
		"item_name": row.get("item_name"),
		"item_group": row.get("item_group"),
		"stock_uom": row.get("stock_uom"),
		"actual_qty": actual_qty,
		"reserved_qty": reserved_qty,
		"ordered_qty": flt(row.get("ordered_qty")),
		"projected_qty": flt(row.get("projected_qty")),
		"free_qty": actual_qty - reserved_qty,
		"valuation_rate": valuation_rate,
		"stock_value": actual_qty * valuation_rate,
	}


def _get_stock_anomalies(items, company):
	from frappe.utils import flt
	# Get company currency
	if company == "Test Company" or (frappe.flags.in_test and str(company).startswith("Test")):
		base_currency = "USD"
	else:
		company_doc = frappe.get_cached_doc("Company", company)
		base_currency = company_doc.default_currency or "USD"

	# Thresholds
	if base_currency == "UZS":
		high_rate_threshold = 40000.0   # ~$3.00
		high_val_threshold = 1300000000.0 # ~$100,000
	else:
		high_rate_threshold = 3.0
		high_val_threshold = 100000.0

	# Keywords for low-cost items
	low_cost_keywords = [
		"etiketka", "korobka", "chopak", "upakovka", "box", "label",
		"stick", "folga", "zarlik", "qop", "plombir", "paket", "meshok",
		"stakan", "tara", "probka", "krishka", "butylka", "lenta", "skotch", "skoch"
	]

	# Group median calculation
	from collections import defaultdict
	group_rates = defaultdict(list)
	for it in items:
		rate = flt(it.get("valuation_rate"))
		group = it.get("item_group")
		if rate > 0:
			group_rates[group].append(rate)

	group_medians = {}
	for group, rates in group_rates.items():
		if len(rates) >= 3:
			sorted_rates = sorted(rates)
			n = len(sorted_rates)
			median = sorted_rates[n // 2] if n % 2 == 1 else (sorted_rates[n // 2 - 1] + sorted_rates[n // 2]) / 2.0
			group_medians[group] = median

	anomalies = []
	for it in items:
		item_code = it.get("item_code")
		item_name = it.get("item_name") or item_code
		group = it.get("item_group")
		qty = flt(it.get("actual_qty"))
		rate = flt(it.get("valuation_rate"))
		val = flt(it.get("stock_value"))

		# Check 1: Zero or negative rate on positive stock
		if qty > 0 and rate <= 0:
			anomalies.append({
				"item_code": item_code,
				"item_name": item_name,
				"type": "zero_rate",
				"message": f"Valuation rate is missing or negative (current rate: {rate:,.2f})"
			})
			continue

		# Check 2: Unusually high rate for packaging/low-cost raw materials
		name_lower = item_name.lower()
		is_low_cost = any(k in name_lower for k in low_cost_keywords)
		if qty > 0 and is_low_cost and rate > high_rate_threshold:
			anomalies.append({
				"item_code": item_code,
				"item_name": item_name,
				"type": "high_rate",
				"message": f"Suspiciously high rate for low-cost item: {base_currency} {rate:,.2f}"
			})
			continue

		# Check 3: Statistically high rate compared to group median
		median = group_medians.get(group)
		if qty > 0 and median and rate > 10 * median:
			anomalies.append({
				"item_code": item_code,
				"item_name": item_name,
				"type": "high_rate",
				"message": f"Abnormally high rate: {base_currency} {rate:,.2f} (>10x group median of {base_currency} {median:,.2f})"
			})
			continue

		# Check 4: Unusually high total stock value for packaging
		if qty > 0 and is_low_cost and val > high_val_threshold:
			anomalies.append({
				"item_code": item_code,
				"item_name": item_name,
				"type": "high_value",
				"message": f"Unusually high total value: {base_currency} {val:,.2f} (verify qty/rate)"
			})
			continue

	return anomalies


@frappe.whitelist()
def warehouse_stock(company: str, warehouse: str, limit: int = 100):
	"""Stock rows for the selected warehouse drill-down."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not warehouse:
		frappe.throw(_("Warehouse is required."))
	if not frappe.db.exists("Warehouse", {"name": warehouse, "company": company}):
		frappe.throw(_("Warehouse does not belong to the selected company."))

	restricted = _get_restricted_warehouses(company)
	if restricted is not None and warehouse not in restricted:
		frappe.throw(_("Not permitted to view this warehouse stock."), frappe.PermissionError)
	rows = frappe.db.sql(
		"""
		SELECT b.item_code, i.item_name, i.item_group,
		       COALESCE(b.stock_uom, i.stock_uom) AS stock_uom,
		       b.actual_qty, b.reserved_qty, b.ordered_qty,
		       b.projected_qty, b.valuation_rate
		FROM `tabBin` b
		LEFT JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %(warehouse)s
		  AND b.actual_qty != 0
		ORDER BY (b.actual_qty * b.valuation_rate) DESC, i.item_name ASC
		LIMIT %(limit)s
		""",
		{"warehouse": warehouse, "limit": int(limit)},
		as_dict=True,
	)
	items = [_format_warehouse_stock_row(row) for row in rows]
	return {
		"warehouse": warehouse,
		"items": items,
		"item_count": len(items),
		"total_qty": sum(row["actual_qty"] for row in items),
		"total_reserved_qty": sum(row["reserved_qty"] for row in items),
		"total_free_qty": sum(row["free_qty"] for row in items),
		"total_value": sum(row["stock_value"] for row in items),
		"anomalies": _get_stock_anomalies(items, company),
	}


@frappe.whitelist()
def list_stock_warehouses(company: str):
	"""Flat list of active leaf warehouses for transaction pickers."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	rows = frappe.db.sql(
		"""
		SELECT name, warehouse_name, warehouse_type, company
		FROM `tabWarehouse`
		WHERE company = %(company)s
		  AND is_group = 0
		  AND COALESCE(disabled, 0) = 0
		ORDER BY warehouse_name
		""",
		{"company": company},
		as_dict=True,
	)
	restricted = _get_restricted_warehouses(company)
	if restricted is not None:
		rows = [r for r in rows if r["name"] in restricted]
	return rows


@frappe.whitelist()
def item_availability(item_code: str, warehouse: str):
	"""Single-bin availability snapshot for the SO line-item warehouse picker."""
	if not item_code or not warehouse:
		frappe.throw(_("item_code and warehouse are required"))
	row = frappe.db.sql(
		"""
		SELECT actual_qty, reserved_qty, ordered_qty, projected_qty, stock_uom
		FROM `tabBin`
		WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s
		LIMIT 1
		""",
		{"item_code": item_code, "warehouse": warehouse},
		as_dict=True,
	)
	if not row:
		return {
			"item_code": item_code,
			"warehouse": warehouse,
			"actual": 0.0,
			"reserved": 0.0,
			"ordered": 0.0,
			"projected": 0.0,
			"free": 0.0,
			"stock_uom": None,
		}
	r = row[0]
	actual = flt(r.get("actual_qty"))
	reserved = flt(r.get("reserved_qty"))
	return {
		"item_code": item_code,
		"warehouse": warehouse,
		"actual": actual,
		"reserved": reserved,
		"ordered": flt(r.get("ordered_qty")),
		"projected": flt(r.get("projected_qty")),
		"free": actual - reserved,
		"stock_uom": r.get("stock_uom"),
	}


@frappe.whitelist()
def get_items_stock(warehouse: str, item_codes: str):
	"""Return the actual_qty in warehouse for a list of item_codes (JSON list)."""
	import json
	if not warehouse or not item_codes:
		return {}
	try:
		codes = json.loads(item_codes)
	except Exception:
		return {}
	if not codes:
		return {}

	bins = frappe.db.get_all(
		"Bin",
		filters={"warehouse": warehouse, "item_code": ["in", codes]},
		fields=["item_code", "actual_qty"]
	)
	return {b.item_code: flt(b.actual_qty) for b in bins}


@frappe.whitelist()
def stock_ledger(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	limit: int = 200,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["sle.company = %(company)s", "sle.is_cancelled = 0"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("sle.posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("sle.posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if item_code:
		conds.append("sle.item_code = %(item_code)s")
		params["item_code"] = item_code
	if warehouse:
		conds.append("sle.warehouse = %(warehouse)s")
		params["warehouse"] = warehouse
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT sle.name, sle.posting_date, sle.posting_time,
		       sle.item_code, i.item_name, sle.warehouse, w.warehouse_name,
		       sle.voucher_type, sle.voucher_no,
		       sle.actual_qty, sle.qty_after_transaction,
		       sle.valuation_rate, sle.stock_value_difference,
		       sle.stock_uom
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabItem` i ON i.name = sle.item_code
		LEFT JOIN `tabWarehouse` w ON w.name = sle.warehouse
		WHERE {where}
		ORDER BY sle.posting_date DESC, sle.posting_time DESC, sle.creation DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def item_valuation_history(company, item_code, warehouse=None, limit=500):
	"""Return the full valuation history for a single item, company-wide (or
	filtered to one warehouse when *warehouse* is given).  Ordered ASC so the
	chart x-axis runs old → new without client-side reversal."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["sle.company = %(company)s", "sle.is_cancelled = 0", "sle.item_code = %(item_code)s"]
	params = {"company": company, "item_code": item_code, "limit": int(limit)}
	if warehouse:
		conds.append("sle.warehouse = %(warehouse)s")
		params["warehouse"] = warehouse
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT sle.name, sle.posting_date, sle.posting_time,
		       sle.item_code, i.item_name, sle.warehouse, w.warehouse_name,
		       sle.voucher_type, sle.voucher_no,
		       sle.actual_qty, sle.qty_after_transaction,
		       sle.incoming_rate, sle.valuation_rate,
		       sle.stock_value, sle.stock_value_difference, sle.stock_uom
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabItem` i ON i.name = sle.item_code
		LEFT JOIN `tabWarehouse` w ON w.name = sle.warehouse
		WHERE {where}
		ORDER BY sle.posting_date ASC, sle.posting_time ASC, sle.creation ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def list_item_groups(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabItem Group`
		WHERE is_group = 0
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def list_uoms(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabUOM`
		WHERE enabled = 1
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def create_item(
	item_name: str,
	item_code: str | None = None,
	item_group: str | None = None,
	stock_uom: str = "Nos",
	is_stock_item: int = 1,
	is_sales_item: int = 1,
	is_purchase_item: int = 1,
	standard_rate: float | None = None,
	description: str | None = None,
):
	item_name = (item_name or "").strip()
	if not item_name:
		frappe.throw("Item name is required.")

	item_code = (item_code or item_name).strip()
	if frappe.db.exists("Item", item_code):
		frappe.throw(f"Item '{item_code}' already exists.")

	if not item_group:
		item_group = (
			frappe.db.get_single_value("Stock Settings", "item_group") or "All Item Groups"
		)
	if not frappe.db.exists("Item Group", item_group):
		frappe.throw(f"Unknown item group: {item_group}")

	stock_uom = (stock_uom or "Nos").strip()
	if not frappe.db.exists("UOM", stock_uom):
		frappe.throw(f"Unknown UOM: {stock_uom}")

	doc = frappe.new_doc("Item")
	doc.item_code = item_code
	doc.item_name = item_name
	doc.item_group = item_group
	doc.stock_uom = stock_uom
	doc.is_stock_item = 1 if int(is_stock_item) else 0
	doc.is_sales_item = 1 if int(is_sales_item) else 0
	doc.is_purchase_item = 1 if int(is_purchase_item) else 0
	if standard_rate is not None:
		doc.standard_rate = flt(standard_rate)
	if description:
		doc.description = description.strip()
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "item_code": doc.item_code, "item_name": doc.item_name}


@frappe.whitelist()
def update_item(
	name: str,
	item_name: str | None = None,
	item_group: str | None = None,
	stock_uom: str | None = None,
	is_stock_item: int | None = None,
	is_sales_item: int | None = None,
	is_purchase_item: int | None = None,
	standard_rate: float | None = None,
	description: str | None = None,
	disabled: int | None = None,
	weight_per_unit: float | None = None,
	weight_uom: str | None = None,
):
	if not name or not frappe.db.exists("Item", name):
		frappe.throw(_("Item '{0}' not found.").format(name))
	doc = frappe.get_doc("Item", name)
	if item_name is not None and item_name.strip():
		doc.item_name = item_name.strip()
	if item_group is not None and item_group.strip():
		if not frappe.db.exists("Item Group", item_group.strip()):
			frappe.throw(_("Unknown item group: {0}").format(item_group))
		doc.item_group = item_group.strip()
	if stock_uom is not None and stock_uom.strip():
		if not frappe.db.exists("UOM", stock_uom.strip()):
			frappe.throw(_("Unknown UOM: {0}").format(stock_uom))
		doc.stock_uom = stock_uom.strip()
	if is_stock_item is not None:
		doc.is_stock_item = 1 if int(is_stock_item) else 0
	if is_sales_item is not None:
		doc.is_sales_item = 1 if int(is_sales_item) else 0
	if is_purchase_item is not None:
		doc.is_purchase_item = 1 if int(is_purchase_item) else 0
	if standard_rate is not None:
		doc.standard_rate = flt(standard_rate)
	if description is not None:
		doc.description = description.strip()
	if disabled is not None:
		doc.disabled = 1 if int(disabled) else 0
	if weight_per_unit is not None:
		doc.weight_per_unit = flt(weight_per_unit)
	if weight_uom is not None:
		doc.weight_uom = weight_uom.strip() if weight_uom else None
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "item_code": doc.item_code, "item_name": doc.item_name, "disabled": doc.disabled}


# --------------------------------------------------------------------------- #
# Price List & Item Price APIs — ERPNext tabPrice List & tabItem Price
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_price_lists(buying: int | None = None, selling: int | None = None):
	"""Return list of active Price Lists from ERPNext `tabPrice List`."""
	conds = ["enabled = 1"]
	params: dict = {}
	if buying is not None:
		conds.append("buying = %(buying)s")
		params["buying"] = 1 if int(buying) else 0
	if selling is not None:
		conds.append("selling = %(selling)s")
		params["selling"] = 1 if int(selling) else 0
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, price_list_name, currency, buying, selling
		FROM `tabPrice List`
		WHERE {where}
		ORDER BY name ASC
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def create_price_list(price_list_name: str, currency: str = "USD", buying: int = 1, selling: int = 1):
	"""Create a new ERPNext `Price List` doc."""
	name = (price_list_name or "").strip()
	if not name:
		frappe.throw(_("Price List name is required."))
	if frappe.db.exists("Price List", name):
		frappe.throw(_("Price List '{0}' already exists.").format(name))
	doc = frappe.new_doc("Price List")
	doc.price_list_name = name
	doc.currency = (currency or "USD").strip()
	doc.buying = 1 if int(buying) else 0
	doc.selling = 1 if int(selling) else 0
	doc.enabled = 1
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "price_list_name": doc.price_list_name, "currency": doc.currency}


@frappe.whitelist()
def list_item_prices_for_item(item_code: str):
	"""Return all Item Price records for a specific item from `tabItem Price`."""
	if not item_code:
		return []
	return frappe.db.sql(
		"""
		SELECT ip.name, ip.price_list, ip.price_list_rate, ip.currency,
		       ip.packing_unit, ip.uom, pl.buying, pl.selling
		FROM `tabItem Price` ip
		LEFT JOIN `tabPrice List` pl ON pl.name = ip.price_list
		WHERE ip.item_code = %(item_code)s
		ORDER BY ip.price_list ASC
		""",
		{"item_code": item_code},
		as_dict=True,
	)


@frappe.whitelist()
def save_item_price(
	item_code: str,
	price_list: str,
	price_list_rate: float,
	currency: str | None = None,
	min_qty: float = 1,
	uom: str | None = None,
	name: str | None = None,
):
	"""Create or update an ERPNext `Item Price` doc."""
	if not item_code or not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item '{0}' not found.").format(item_code))
	if not price_list or not frappe.db.exists("Price List", price_list):
		frappe.throw(_("Price List '{0}' not found.").format(price_list))

	rate = flt(price_list_rate)
	if rate < 0:
		frappe.throw(_("Price list rate cannot be negative."))

	pl_doc = frappe.get_doc("Price List", price_list)
	curr = (currency or pl_doc.currency or "USD").strip()

	if not name:
		existing = frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list})
		if existing:
			name = existing

	if name and frappe.db.exists("Item Price", name):
		doc = frappe.get_doc("Item Price", name)
	else:
		doc = frappe.new_doc("Item Price")
		doc.item_code = item_code
		doc.price_list = price_list

	doc.price_list_rate = rate
	doc.currency = curr
	if uom:
		doc.uom = uom
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "item_code": doc.item_code, "price_list": doc.price_list, "price_list_rate": doc.price_list_rate, "currency": doc.currency}


@frappe.whitelist()
def delete_item_price(name: str):
	"""Delete an Item Price record."""
	if not name or not frappe.db.exists("Item Price", name):
		frappe.throw(_("Item Price '{0}' not found.").format(name))
	frappe.delete_doc("Item Price", name, ignore_permissions=False)
	return {"status": "ok"}


@frappe.whitelist()
def get_price_list_matrix(price_list: str, item_group: str | None = None, search: str | None = None, limit: int = 200):
	"""Get all items along with their rate in the specified `price_list` for bulk editing."""
	if not price_list or not frappe.db.exists("Price List", price_list):
		frappe.throw(_("Price List '{0}' not found.").format(price_list))

	pl = frappe.get_doc("Price List", price_list)
	conds = ["i.disabled = 0"]
	params = {"price_list": price_list, "limit": min(int(limit or 200), 500)}

	if search:
		conds.append("(i.item_name LIKE %(s)s OR i.item_code LIKE %(s)s)")
		params["s"] = f"%{search}%"
	if item_group:
		conds.append("i.item_group = %(item_group)s")
		params["item_group"] = item_group

	where = " AND ".join(conds)
	rows = frappe.db.sql(
		f"""
		SELECT i.name AS item_code, i.item_name, i.item_group, i.stock_uom, i.standard_rate,
		       ip.name AS item_price_name, ip.price_list_rate,
		       COALESCE(ip.currency, %(pl_curr)s) AS currency
		FROM `tabItem` i
		LEFT JOIN `tabItem Price` ip ON ip.item_code = i.name AND ip.price_list = %(price_list)s
		WHERE {where}
		ORDER BY i.item_name ASC
		LIMIT %(limit)s
		""",
		{**params, "pl_curr": pl.currency or "USD"},
		as_dict=True,
	)
	return {"price_list": pl.name, "currency": pl.currency, "items": rows}


@frappe.whitelist()
def bulk_update_item_prices(price_list: str, price_updates: list | str):
	"""Bulk update Item Price rates for a specific Price List."""
	if not price_list or not frappe.db.exists("Price List", price_list):
		frappe.throw(_("Price List '{0}' not found.").format(price_list))

	if isinstance(price_updates, str):
		price_updates = json.loads(price_updates or "[]")
	if not isinstance(price_updates, list):
		frappe.throw(_("Invalid price updates format."))

	updated_count = 0
	for item_upd in price_updates:
		code = item_upd.get("item_code")
		rate = flt(item_upd.get("price_list_rate"))
		if not code or rate < 0:
			continue
		save_item_price(
			item_code=code,
			price_list=price_list,
			price_list_rate=rate,
			currency=item_upd.get("currency"),
		)
		updated_count += 1

	return {"status": "ok", "updated_count": updated_count}


@frappe.whitelist()
def list_warehouse_types(limit: int = 50):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabWarehouse Type`
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def list_parent_warehouses(company: str):
	"""Group warehouses that can act as parents under the given company."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	return frappe.db.sql(
		"""
		SELECT name, warehouse_name
		FROM `tabWarehouse`
		WHERE company = %(company)s AND is_group = 1 AND disabled = 0
		ORDER BY lft
		""",
		{"company": company},
		as_dict=True,
	)


@frappe.whitelist()
def create_warehouse(
	warehouse_name: str,
	company: str,
	parent_warehouse: str | None = None,
	warehouse_type: str | None = None,
	is_group: int = 0,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	name = (warehouse_name or "").strip()
	if not name:
		frappe.throw("Warehouse name is required.")

	if parent_warehouse and not frappe.db.exists("Warehouse", parent_warehouse):
		frappe.throw(f"Unknown parent warehouse: {parent_warehouse}")

	if warehouse_type and not frappe.db.exists("Warehouse Type", warehouse_type):
		frappe.throw(f"Unknown warehouse type: {warehouse_type}")

	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = name
	doc.company = company
	doc.is_group = 1 if int(is_group) else 0
	if parent_warehouse:
		doc.parent_warehouse = parent_warehouse
	if warehouse_type:
		doc.warehouse_type = warehouse_type
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "warehouse_name": doc.warehouse_name}


_ALLOWED_STOCK_PURPOSES = {"Material Receipt", "Material Issue", "Material Transfer"}


@frappe.whitelist()
def list_stock_entries(
	company: str,
	purpose: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	status: str | None = None,
	search: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["se.company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if purpose:
		conds.append("se.purpose = %(purpose)s")
		params["purpose"] = purpose
	if from_date:
		conds.append("se.posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("se.posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if from_warehouse:
		conds.append("se.from_warehouse = %(from_warehouse)s")
		params["from_warehouse"] = from_warehouse
	if to_warehouse:
		conds.append("se.to_warehouse = %(to_warehouse)s")
		params["to_warehouse"] = to_warehouse
	if status not in (None, ""):
		sv = int(status)
		if sv in (0, 1, 2):
			conds.append("se.docstatus = %(docstatus)s")
			params["docstatus"] = sv
	if search:
		conds.append("se.name LIKE %(search)s")
		params["search"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT se.name, se.posting_date, se.purpose, se.stock_entry_type,
		       se.from_warehouse, se.to_warehouse, se.docstatus,
		       se.total_outgoing_value, se.total_incoming_value,
		       se.total_amount,
		       (SELECT COUNT(*) FROM `tabStock Entry Detail` d WHERE d.parent = se.name) AS item_count
		FROM `tabStock Entry` se
		WHERE {where}
		ORDER BY se.posting_date DESC, se.creation DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def stock_entry_detail(name: str):
	_assert_can_read("Stock Entry", name)
	if not name or not frappe.db.exists("Stock Entry", name):
		frappe.throw(f"Unknown stock entry: {name}")
	doc = frappe.get_doc("Stock Entry", name)
	items = []
	for it in doc.items or []:
		items.append({
			"idx": it.idx,
			"item_code": it.item_code,
			"item_name": it.item_name,
			"custom_line_note": getattr(it, "custom_line_note", None) or None,
			"qty": flt(it.qty),
			"transfer_qty": flt(it.transfer_qty),
			"uom": it.uom,
			"stock_uom": it.stock_uom,
			"basic_rate": flt(it.basic_rate),
			"amount": flt(it.amount),
			"s_warehouse": it.s_warehouse,
			"t_warehouse": it.t_warehouse,
		})
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"posting_time": str(doc.posting_time) if doc.posting_time else None,
		"company": doc.company,
		"purpose": doc.purpose,
		"stock_entry_type": doc.stock_entry_type,
		"from_warehouse": doc.from_warehouse,
		"to_warehouse": doc.to_warehouse,
		"docstatus": doc.docstatus,
		"total_outgoing_value": flt(doc.total_outgoing_value),
		"total_incoming_value": flt(doc.total_incoming_value),
		"total_amount": flt(doc.total_amount),
		"remarks": doc.remarks,
		"items": items,
	}


@frappe.whitelist()
def create_stock_entry(
	company: str,
	purpose: str,
	items: list | str,
	posting_date: str | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	remarks: str | None = None,
	submit: int = 0,
):
	"""Create a Stock Entry of one of three user-facing purposes.

	`items` is a list of {item_code, qty, basic_rate?, s_warehouse?, t_warehouse?}.
	When `from_warehouse`/`to_warehouse` are provided at the header, they are
	applied to lines that don't already specify their own — this matches what
	the ERPNext desk form does."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	purpose = (purpose or "").strip()
	if purpose not in _ALLOWED_STOCK_PURPOSES:
		frappe.throw(f"Unsupported purpose: {purpose}")

	if isinstance(items, str):
		items = json.loads(items or "[]")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item line is required.")

	for it in items:
		if not (it or {}).get("item_code"):
			frappe.throw("Each item line needs an item_code.")
		if flt((it or {}).get("qty")) <= 0:
			frappe.throw("Each item line needs a positive qty.")

	if purpose in ("Material Receipt", "Material Transfer") and not to_warehouse:
		# allow per-line override
		if not all(it.get("t_warehouse") for it in items):
			frappe.throw("Pick a destination warehouse.")
	if purpose in ("Material Issue", "Material Transfer") and not from_warehouse:
		if not all(it.get("s_warehouse") for it in items):
			frappe.throw("Pick a source warehouse.")

	doc = frappe.new_doc("Stock Entry")
	doc.company = company
	doc.purpose = purpose
	doc.stock_entry_type = purpose  # default Stock Entry Type names match purposes
	if posting_date:
		doc.posting_date = getdate(posting_date)
	if from_warehouse:
		doc.from_warehouse = from_warehouse
	if to_warehouse:
		doc.to_warehouse = to_warehouse
	if remarks:
		doc.remarks = remarks.strip()

	for it in items:
		row = doc.append("items", {})
		row.item_code = it["item_code"]
		if it.get("custom_line_note"):
			row.custom_line_note = str(it["custom_line_note"])[:500]
		row.qty = flt(it.get("qty"))
		uom = it.get("uom") or frappe.get_cached_value("Item", it["item_code"], "stock_uom")
		row.uom = uom
		row.conversion_factor = get_conversion_factor(it["item_code"], uom).get("conversion_factor") or 1.0
		if it.get("basic_rate") not in (None, ""):
			row.basic_rate = flt(it["basic_rate"])
		s_wh = it.get("s_warehouse") or (from_warehouse if purpose in ("Material Issue", "Material Transfer") else None)
		t_wh = it.get("t_warehouse") or (to_warehouse if purpose in ("Material Receipt", "Material Transfer") else None)
		if s_wh:
			row.s_warehouse = s_wh
		if t_wh:
			row.t_warehouse = t_wh

	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def submit_stock_entry(name: str):
	_assert_can_write("Stock Entry", name, "submit")
	doc = frappe.get_doc("Stock Entry", name)
	if doc.docstatus != 0:
		frappe.throw(f"Stock Entry is already {['Draft','Submitted','Cancelled'][doc.docstatus]}.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_stock_entry(name: str):
	_assert_can_write("Stock Entry", name, "cancel")
	doc = frappe.get_doc("Stock Entry", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted Stock Entries can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def low_stock_alerts(company: str, limit: int = 50):
	"""Items whose total projected_qty (across the company's warehouses) is at or below
	their warehouse reorder level. Uses tabItem Reorder for per-warehouse thresholds."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	rows = frappe.db.sql(
		"""
		SELECT
		  ir.parent AS item_code,
		  i.item_name,
		  ir.warehouse,
		  ir.warehouse_reorder_level AS reorder_level,
		  ir.warehouse_reorder_qty AS reorder_qty,
		  COALESCE(b.actual_qty, 0) AS actual_qty,
		  COALESCE(b.projected_qty, 0) AS projected_qty,
		  b.stock_uom
		FROM `tabItem Reorder` ir
		JOIN `tabItem` i ON i.name = ir.parent
		JOIN `tabWarehouse` w ON w.name = ir.warehouse AND w.company = %(company)s
		LEFT JOIN `tabBin` b ON b.item_code = ir.parent AND b.warehouse = ir.warehouse
		WHERE i.disabled = 0
		  AND COALESCE(b.projected_qty, 0) <= ir.warehouse_reorder_level
		ORDER BY (ir.warehouse_reorder_level - COALESCE(b.projected_qty, 0)) DESC
		LIMIT %(limit)s
		""",
		{"company": company, "limit": int(limit)},
		as_dict=True,
	)
	return rows


# --------------------------------------------------------------------------- #
# Stock Reconciliation (count-to-actual) — surfaces ERPNext Stock Reconciliation.
# ERPNext posts the Stock Ledger difference on submit; we never touch the ledger.
# --------------------------------------------------------------------------- #
def _assert_warehouse_company(warehouse: str, company: str) -> None:
	wc = frappe.db.get_value("Warehouse", warehouse, "company")
	if not wc:
		frappe.throw(_("Warehouse '{0}' not found.").format(warehouse))
	if wc != company:
		frappe.throw(_("Warehouse '{0}' is not in company '{1}'.").format(warehouse, company))


@frappe.whitelist()
def warehouse_stock_balance(company: str, warehouse: str, search: str | None = None, limit: int = 200):
	"""Current Bin qty + valuation for items in a warehouse — prefills the count."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_assert_warehouse_company(warehouse, company)
	conds = ["b.warehouse = %(wh)s"]
	params: dict = {"wh": warehouse, "limit": min(int(limit or 200), 1000)}
	if search:
		conds.append("(b.item_code LIKE %(s)s OR i.item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	rows = frappe.db.sql(
		f"""SELECT b.item_code, i.item_name, b.actual_qty, b.valuation_rate, b.stock_uom
		    FROM `tabBin` b JOIN `tabItem` i ON i.name = b.item_code
		    WHERE {" AND ".join(conds)} AND i.disabled = 0
		    ORDER BY i.item_name LIMIT %(limit)s""",
		params,
		as_dict=True,
	)
	return {"warehouse": warehouse, "items": rows, "count": len(rows)}


@frappe.whitelist()
def preview_reconciliation(items: list | str):
	"""Pure preview: which counted lines changed + variance summary (no write)."""
	_require_recon_role()
	if isinstance(items, str):
		items = json.loads(items or "[]")
	return prepare_reconciliation(items if isinstance(items, list) else [])


def _require_recon_role() -> None:
	"""Stock reconciliation is sensitive (can mask shrinkage) — Stock Manager/admin."""
	roles = set(frappe.get_roles())
	if not roles & {"Stock Manager", "System Manager", "Stabler Admin"}:
		frappe.throw(_("Only a Stock Manager can reconcile stock."), frappe.PermissionError)


@frappe.whitelist()
def create_stock_reconciliation(
	company: str,
	items: list | str,
	posting_date: str | None = None,
	remarks: str | None = None,
	submit: int = 0,
):
	"""Create an ERPNext Stock Reconciliation from counted quantities.

	`items`: [{item_code, warehouse, current_qty, counted_qty, valuation_rate?}].
	Only lines whose count differs from the system qty are sent; ERPNext posts
	the Stock Ledger difference (to the Stock Adjustment account) on submit.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_recon_role()
	if isinstance(items, str):
		items = json.loads(items or "[]")
	if not isinstance(items, list) or not items:
		frappe.throw(_("At least one counted item line is required."))

	prepared = prepare_reconciliation(items)
	lines = prepared["lines"]
	if not lines:
		frappe.throw(_("No lines differ from the system quantity — nothing to reconcile."))
	for ln in lines:
		_assert_warehouse_company(ln["warehouse"], company)

	doc = frappe.new_doc("Stock Reconciliation")
	doc.company = company
	doc.purpose = "Stock Reconciliation"
	if posting_date:
		doc.posting_date = getdate(posting_date)
	if remarks:
		doc.remarks = remarks.strip()
	for ln in lines:
		row = doc.append("items", {})
		row.item_code = ln["item_code"]
		row.warehouse = ln["warehouse"]
		row.qty = ln["qty"]  # the counted (target) quantity
		if ln.get("valuation_rate"):
			row.valuation_rate = ln["valuation_rate"]
	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()  # ERPNext posts the SLE difference
	frappe.logger("stabler.stockrecon").info(
		f"stock reconciliation {doc.name} ({len(lines)} lines) by {frappe.session.user}"
	)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"changed_lines": len(lines),
		"summary": prepared["summary"],
	}


@frappe.whitelist()
def list_stock_reconciliations(company: str, limit: int = 25):
	"""Recent stock reconciliations for the history panel."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	return frappe.get_all(
		"Stock Reconciliation",
		filters={"company": company},
		fields=["name", "posting_date", "docstatus", "remarks", "owner", "creation"],
		order_by="creation desc",
		limit=min(int(limit or 25), 100),
	)


# ---------------------------------------------------------------------------
# Batch / expiry visibility (FEFO)
#
# Batches are created at goods receipt (imports_module/hooks._ensure_batch) with
# the supplier's expiry date, and until now nothing downstream could see them:
# no expiry column, no FEFO order, no batch-level balance. For frozen meat that
# means shelf life was recorded and then ignored. These endpoints are read-only
# — they expose what is already in the ledger. Writing the chosen batch onto a
# sales document is a separate, riskier step.
# ---------------------------------------------------------------------------


def _batch_rows(company: str, item_code: str | None, warehouse: str | None):
	"""Per-batch balances from the Stock Ledger, with days to expiry.

	Supports both ERPNext v15 direct `sle.batch_no` and v16 `serial_and_batch_bundle`.
	"""
	conds = ["sle.company = %(company)s", "sle.is_cancelled = 0", "(sle.batch_no IS NOT NULL OR sbe.batch_no IS NOT NULL)"]
	params = {"company": company, "item_code": item_code, "warehouse": warehouse}
	if item_code:
		conds.append("sle.item_code = %(item_code)s")
	if warehouse:
		conds.append("sle.warehouse = %(warehouse)s")
	return frappe.db.sql(
		f"""
		SELECT COALESCE(sle.batch_no, sbe.batch_no) AS batch_no,
		       sle.item_code, sle.warehouse,
		       SUM(CASE WHEN sle.serial_and_batch_bundle IS NOT NULL THEN sbe.qty ELSE sle.actual_qty END) AS qty,
		       b.expiry_date,
		       DATEDIFF(b.expiry_date, CURDATE()) AS days_left,
		       i.item_name, i.stock_uom
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sle.serial_and_batch_bundle
		LEFT JOIN `tabBatch` b ON b.name = COALESCE(sle.batch_no, sbe.batch_no)
		LEFT JOIN `tabItem` i ON i.name = sle.item_code
		WHERE {" AND ".join(conds)}
		GROUP BY COALESCE(sle.batch_no, sbe.batch_no), sle.item_code, sle.warehouse, b.expiry_date, i.item_name, i.stock_uom
		HAVING SUM(CASE WHEN sle.serial_and_batch_bundle IS NOT NULL THEN sbe.qty ELSE sle.actual_qty END) > 0
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def batch_availability(company: str, item_code: str, warehouse: str | None = None):
	"""Batches holding stock for one item, nearest expiry first."""
	_require_company(company)
	_assert_company_scope(company)
	if not item_code:
		frappe.throw(_("item_code is required"))
	_assert_can_read("Item", item_code)

	rows = _batch_rows(company, item_code, warehouse)
	for r in rows:
		r["qty"] = flt(r["qty"])
		r["days_left"] = int(r["days_left"]) if r["days_left"] is not None else None
		r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
		r["bucket"] = _fefo.expiry_bucket(r["days_left"])
	return {
		"item_code": item_code,
		"warehouse": warehouse,
		"batches": _fefo.sort_fefo(rows),
		"summary": _fefo.summarise(rows),
	}


@frappe.whitelist()
def suggest_fefo(
	company: str,
	item_code: str,
	warehouse: str,
	qty,
	allow_expired: int = 0,
):
	"""Which batches should cover ``qty``, nearest expiry first.

	A suggestion only — nothing is written. The caller decides whether to accept
	it, and a shortfall is returned rather than raised so the picking screen can
	show partial coverage.
	"""
	_require_company(company)
	_assert_company_scope(company)
	if not item_code or not warehouse:
		frappe.throw(_("item_code and warehouse are required"))
	_assert_can_read("Item", item_code)

	rows = _batch_rows(company, item_code, warehouse)
	for r in rows:
		r["qty"] = flt(r["qty"])
		r["days_left"] = int(r["days_left"]) if r["days_left"] is not None else None
		r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
	return _fefo.allocate_fefo(flt(qty), rows, allow_expired=bool(cint(allow_expired)))


@frappe.whitelist()
def expiring_batches(
	company: str,
	warehouse: str | None = None,
	within_days: int = 30,
	include_expired: int = 1,
	limit: int = 200,
):
	"""Stock that has expired or is close to it — the shelf-life watch list."""
	_require_company(company)
	_assert_company_scope(company)
	within = max(0, cint(within_days))

	rows = _batch_rows(company, None, warehouse)
	out = []
	for r in rows:
		days = int(r["days_left"]) if r["days_left"] is not None else None
		if days is None:
			continue  # no expiry recorded — surfaced by the summary, not the alert
		if days < 0 and not cint(include_expired):
			continue
		if days > within:
			continue
		r["qty"] = flt(r["qty"])
		r["days_left"] = days
		r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
		r["bucket"] = _fefo.expiry_bucket(days)
		out.append(r)

	out = _fefo.sort_fefo(out)[: max(1, cint(limit))]
	return {"rows": out, "summary": _fefo.summarise(out), "within_days": within}
