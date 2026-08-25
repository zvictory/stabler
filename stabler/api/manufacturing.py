"""Manufacturing module — BOMs, Work Orders, Production Plan basics."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.organization import _can_access_module
from stabler.api.valuation_guard import assert_stock_entry_valuation_sane

# ----- Role helpers ---------------------------------------------------------

_ADMIN_ROLES = {"System Manager", "Stabler Admin"}


def _is_mfg_manager(user: str | None = None) -> bool:
	roles = set(frappe.get_roles(user or frappe.session.user))
	return bool(roles & ({"Manufacturing Manager"} | _ADMIN_ROLES))


def _is_warehouse_role(user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	has_role = bool(roles & ({"Stock User", "Stock Manager"} | _ADMIN_ROLES))
	return has_role or _can_access_module(user, "inventory")


def _require_mfg_manager() -> None:
	if not _is_mfg_manager():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_mfg() -> None:
	"""Any user with the manufacturing module (operator OR manager)."""
	if not _can_access_module(frappe.session.user, "manufacturing"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


#: The Work Order fields naming a shop-floor assignee. `operator` is the production
#: role, `packaging_operator` the packing role (patch v97) — one order, two people,
#: and both must pass the same gate. Enumerated once so the access helper and the
#: SQL filter in `list_work_orders` cannot answer differently; a rule spelled out
#: twice is a rule that drifts, and test_wo_operator_roles fails if one does.
_WO_OPERATOR_FIELDS = ("operator", "packaging_operator")

#: Operator field -> the material role that person answers for. The right-hand
#: values are the `Item.custom_operator_role` Select options (patch v98) verbatim:
#: one vocabulary for the role a person holds and the role a material carries, so
#: a sheet cannot come back empty because two literals drifted apart in two files.
#: test_wo_operator_roles pins the keys to `_WO_OPERATOR_FIELDS` and the values to
#: the patch's options.
_WO_FIELD_ROLE = {"operator": "Production", "packaging_operator": "Packaging"}

#: Where the role lives. On the Item, because it is a fact about the material and
#: not about its unit: sugar is in kg and belongs to pouring, packing film is in kg
#: and belongs to packing. The prototype derived it from the unit instead and
#: disagreed with its own catalogue on 28% of its BOM lines.
_ITEM_ROLE_FIELD = "custom_operator_role"

#: ERPNext decides what a Stock Entry *is* by matching this string exactly — it
#: does so in a dozen places in stock_entry.py alone. The consumption purpose gets
#: one spelling here because it is read from three call sites at once, and three
#: copies of a string nobody validates is how the prototype ended up answering the
#: same question two different ways (see patches/v98_item_operator_role.py). The
#: other two purposes predate this and are still spelled inline; they are not
#: worth a rename that touches every line they appear on.
_SE_CONSUMPTION = "Material Consumption for Manufacture"

#: The purposes the kiosk may post. Transfer carries raw material into WIP once for
#: the whole order; consumption writes off one role's share of what is in there;
#: Manufacture receives the finished goods and closes the order.
_SE_PURPOSES = ("Material Transfer for Manufacture", _SE_CONSUMPTION, "Manufacture")


def _wo_operator_columns() -> tuple[str, ...]:
	"""The assignee columns that actually exist on this site.

	`packaging_operator` is a Custom Field, so it exists only after v97 has run.
	Between a code deploy and the `bench migrate` behind it, naming the column in
	raw SQL would 500 the work-order list for every operator on the site. Falling
	back to the production role alone keeps the list serving, and the second role
	appears the moment migrate lands — the same shape `sourcing.py` and `sales.py`
	use for their own custom fields.
	"""
	return tuple(f for f in _WO_OPERATOR_FIELDS if frappe.db.has_column("Work Order", f))


def _require_wo_operator_column(field: str) -> None:
	"""Refuse to write an operator role whose column this site does not carry yet.

	Reads degrade quietly (`_wo_operator_columns`) so the shop floor keeps working
	in the window between a code deploy and the `bench migrate` behind it. Writes
	must not degrade at all: Frappe drops an unknown key before `get_valid_dict()`
	ever sees it, so the packer would simply not be recorded and nothing would say
	so — the manager reads back "not assigned" and re-assigns forever. That silence
	is the exact failure v94 was written about. Fail loudly instead of half-saving.
	"""
	if field not in _wo_operator_columns():
		frappe.throw(_("This site is not migrated for packaging operators yet."))


def _is_wo_assignee(doc, user: str | None = None) -> bool:
	"""Is `user` assigned to this Work Order, in either operator role?

	`doc` is anything answering `.get(fieldname)` — a Document, or the dict
	`frappe.db.get_value(..., as_dict=True)` returns.
	"""
	user = user or frappe.session.user
	# Without this, an anonymous caller matches every unassigned role (None == None)
	# and the guard fails open — the one direction a permission check must not fail.
	if not user:
		return False
	return any(doc.get(field) == user for field in _WO_OPERATOR_FIELDS)


def _assert_distinct_operators(production: str | None, packaging: str | None) -> None:
	"""Refuse one person in both operator roles on the same Work Order.

	Pouring and packing are two stations running at the same time, and their
	output — material used, rejects, minutes — is counted separately per person.
	One name in both slots makes those two numbers indistinguishable, which is
	the whole reason the roles were split apart in v97.
	"""
	if production and packaging and production == packaging:
		frappe.throw(_("One person cannot hold both operator roles on the same Work Order."))


def _require_own_work_order(name: str) -> None:
	"""Assert current user is an assigned operator on this WO (non-managers only)."""
	row = frappe.db.get_value("Work Order", name, list(_wo_operator_columns()), as_dict=True)
	if not row or not _is_wo_assignee(row):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _wo_role_of(doc, user: str | None = None) -> str | None:
	"""Which material role does `user` hold on this Work Order, if any?

	Permission is still decided in exactly one place — this asks `_is_wo_assignee`
	first and only then labels the answer, so the yes/no and the which-one cannot
	disagree. Returns None for anyone the gate already refused.
	"""
	user = user or frappe.session.user
	if not _is_wo_assignee(doc, user):
		return None
	return next((role for field, role in _WO_FIELD_ROLE.items() if doc.get(field) == user), None)


def _item_roles(item_codes) -> dict[str, str]:
	"""item_code -> operator role, for the codes that carry one.

	Returns an empty map on a site that has not run v98 yet, which reads as "no
	line has a role" — every line lands in the shift lead's column and the kiosk
	says so. Naming a column that does not exist would 500 the order instead, in
	the window between a code deploy and the `bench migrate` behind it.
	"""
	codes = [c for c in dict.fromkeys(item_codes) if c]
	if not codes or not frappe.db.has_column("Item", _ITEM_ROLE_FIELD):
		return {}
	rows = frappe.get_all("Item", filters={"name": ("in", codes)}, fields=["name", _ITEM_ROLE_FIELD])
	return {r["name"]: (r.get(_ITEM_ROLE_FIELD) or "") for r in rows}


def _rows_for_role(rows, roles: dict[str, str], role: str | None) -> list:
	"""The material rows `role` is answerable for.

	The `if not role` guard is the one that matters. An undecided item answers
	`roles.get(code)` with None or "", and a caller holding no role is also None —
	compared naively the two match, and a stranger to the order is handed exactly
	the lines nobody owns. Refuse first, compare second.
	"""
	if not role:
		return []
	return [r for r in rows if roles.get(r["item_code"]) == role]


def _unassigned_rows(rows, roles: dict[str, str]) -> list:
	"""Material rows whose operator role nobody has decided yet.

	These belong to the shift lead, not to a default operator. v98 ships the field
	empty on every existing Item on purpose: the answer lives with the people who
	run the floor, and a default would hide the gap behind a value that looks
	answered. Surfacing the count is what keeps it shrinking.
	"""
	return [r for r in rows if not roles.get(r["item_code"])]


def _role_deviation(rows, with_cost: bool) -> list[dict]:
	"""How far each role ran from the BOM, one bucket per role.

	**Money, not quantity.** One order's materials are litres, kilograms and pieces
	at once; a total that adds them is wrong in a way nobody reading it can see.
	The BOM rate is the only common denominator on the row, and it is already
	manager-only — which is exactly who this panel is for. Without that permission
	`cost` is None rather than 0, because a zero reads as "no deviation" instead of
	"not shown to you".

	**A line nobody has written off yet is pending, not a shortfall.**
	`consumed_qty` is 0 until somebody posts the write-off, so counting those would
	report the whole order as under-used the moment work begins and then walk the
	number back all day. They are counted separately and said out loud, so a total
	built from half an order cannot pass for a total built from all of it.

	The two real roles always appear, empty or not: a missing bucket reads as "no
	deviation on that side", an empty one reads as "nothing written off there".
	The undecided bucket appears only when something is actually undecided —
	folding those lines into either operator would put a number on a person who
	never agreed to it, and v98 leaves the role empty on purpose.
	"""
	buckets: dict = {}
	for role in _WO_FIELD_ROLE.values():
		buckets[role] = {"role": role, "counted_lines": 0, "pending_lines": 0, "cost": 0.0}
	for row in rows:
		role = row.get("operator_role") or None
		bucket = buckets.setdefault(role, {"role": role, "counted_lines": 0, "pending_lines": 0, "cost": 0.0})
		consumed = flt(row.get("consumed_qty"))
		if not consumed:
			bucket["pending_lines"] += 1
			continue
		bucket["counted_lines"] += 1
		bucket["cost"] += (consumed - flt(row.get("required_qty"))) * flt(row.get("rate"))
	for bucket in buckets.values():
		bucket["cost"] = flt(bucket["cost"]) if with_cost else None
	return [b for role, b in buckets.items() if role is not None or b["counted_lines"] or b["pending_lines"]]


def _assert_roles_are_both_or_neither(work_order: str) -> None:
	"""Refuse a Work Order that names one operator role and leaves the other empty.

	`list_work_orders` filters an operator's list by the assignee columns, so the
	person who was never named cannot open the order at all. They never write off
	their own materials, and ERPNext's Manufacture entry sweeps every unconsumed
	line onto whoever presses finish. The order completes, the totals look
	plausible, and the packer's kilograms sit on the pourer's document — the exact
	number the split was created to keep apart.

	Neither role filled is a different state and passes: that is a site not using
	the split at all. Refusing those would stop every shop floor on the day this
	deploys, over orders that were never half of anything. Only the deliberate
	half — a manager who filled one box and left the other — is refused, and
	`assign_work_order_operator` writes both boxes in a single call precisely so
	that half is never an accident of ordering.
	"""
	row = frappe.db.get_value("Work Order", work_order, list(_wo_operator_columns()), as_dict=True) or {}
	# Truthiness, not `is None`. `assign_work_order_operator` clears a role by
	# writing "" (the "- Remove operator -" option) while a never-touched column is
	# NULL, and both mean the same thing here: nobody is holding that role.
	assigned = {field: row.get(field) for field in _WO_FIELD_ROLE}
	if all(assigned.values()) or not any(assigned.values()):
		return
	missing = [_WO_FIELD_ROLE[field] for field, who in assigned.items() if not who]
	# The role name goes after a colon rather than inside the sentence: it is a
	# stored value ("Production"/"Packaging"), and inlining an English word into
	# the middle of a translated clause reads as a bug in every other language.
	frappe.throw(
		_("Materials cannot be transferred until both operator roles are assigned. Missing: {0}").format(
			", ".join(missing)
		)
	)


def _material_consumption_enabled() -> bool:
	"""Is ERPNext's per-role write-off switched on for this site?

	With the setting off ERPNext does not refuse a consumption entry. It silently
	builds the wrong one. Measured on genesis-test 2026-08-25, against a Work Order
	whose lines were already fully consumed (consumed_qty == required_qty on both):

	    material_consumption = 1  ->  rows []                       (nothing left)
	    material_consumption = 0  ->  rows MILK 20.0, LABEL 10.0

	The second is `get_bom_raw_materials` where the first is
	`get_unconsumed_raw_materials` — stock_entry.py picks between them on this very
	setting. So with it off the kiosk is handed the whole BOM, scaled to the
	quantity asked for, including material written off days ago; submitting that
	adds it to `consumed_qty` a second time, on top of whoever consumed it first.
	Nothing throws at any point.

	Which is why the check sits here, ahead of ERPNext. It ships off (default 0,
	measured off on genesis-test) — the ordinary state of a site not yet set up for
	the split, not an error condition.
	"""
	return bool(frappe.db.get_single_value("Manufacturing Settings", "material_consumption"))


def _assert_may_consume(work_order: str, item_list: list, role_scoped: bool) -> None:
	"""Refuse a consumption entry that writes off material this caller does not own.

	The whole point of the split is that pouring and packing are counted per
	person. Nothing in ERPNext enforces it — `Work Order Item.consumed_qty` simply
	accumulates whatever any entry names — so an operator posting the other role's
	lines would move that material onto their own document and out of the packer's,
	and both KPIs would be wrong with no trace of why.

	Lines nobody has given a role to are refused separately and by name. They are
	not an operator's to guess at: v98 leaves the role empty rather than defaulting
	it, so an empty role means the question is still open and belongs to the shift
	lead. A manager (`role_scoped=False`) posts what they like — deciding on behalf
	of the floor is exactly their job.
	"""
	if not _material_consumption_enabled():
		frappe.throw(
			_(
				"Materials cannot be written off per operator on this site yet. "
				"Switch on 'Allow Continuous Material Consumption' in Manufacturing Settings."
			)
		)
	if not item_list:
		# An empty list would otherwise reach ERPNext as "consume everything the BOM
		# says", which is the other role's material too.
		frappe.throw(_("Select the materials to write off."))
	if not role_scoped:
		return

	row = frappe.db.get_value("Work Order", work_order, list(_wo_operator_columns()), as_dict=True)
	role = _wo_role_of(row)
	codes = list(dict.fromkeys(it.get("item_code") for it in item_list))
	roles = _item_roles(codes)
	undecided = [c for c in codes if not roles.get(c)]
	if undecided:
		frappe.throw(
			_("Nobody has decided which operator these materials belong to yet: {0}").format(
				", ".join(undecided)
			)
		)
	foreign = [c for c in codes if roles.get(c) != role]
	if foreign:
		frappe.throw(
			_("These materials are the other operator's to write off, not yours: {0}").format(
				", ".join(foreign)
			)
		)


# ----- BOMs ----------------------------------------------------------------


@frappe.whitelist()
def list_boms(company: str, search: str = "", item: str | None = None, limit: int = 100):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(name LIKE %(s)s OR item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	if item:
		conds.append("item = %(item)s")
		params["item"] = item
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, item, item_name, quantity, uom, is_active, is_default,
		       total_cost, currency, docstatus, modified
		FROM `tabBOM`
		WHERE {where}
		ORDER BY is_default DESC, modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def bom_detail(name: str):
	_assert_can_read("BOM", name)
	_require_mfg_manager()
	if not name or not frappe.db.exists("BOM", name):
		frappe.throw(f"Unknown BOM: {name}")
	doc = frappe.get_doc("BOM", name)
	items = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"qty": flt(r.qty),
			"uom": r.uom or r.stock_uom,
			"stock_qty": flt(r.stock_qty),
			"rate": flt(r.rate),
			"amount": flt(r.amount),
			"bom_no": r.bom_no,
		}
		for r in (doc.items or [])
	]
	return {
		"name": doc.name,
		"item": doc.item,
		"item_name": doc.item_name,
		"quantity": flt(doc.quantity),
		"uom": doc.uom,
		"company": doc.company,
		"currency": doc.currency,
		"is_active": doc.is_active,
		"is_default": doc.is_default,
		"with_operations": doc.with_operations,
		"total_cost": flt(doc.total_cost),
		"raw_material_cost": flt(doc.raw_material_cost),
		"operating_cost": flt(doc.operating_cost),
		"docstatus": doc.docstatus,
		"items": items,
	}


@frappe.whitelist()
def bom_materials(company: str, bom_no: str, qty: float = 1, exploded: int = 0):
	"""BOM raw-material lines scaled to a target finished-goods qty.

	Unlike bom_detail (manager-only, BOM-native quantity), this is available to
	operators too and returns the components already multiplied out for the WO
	qty they're about to start — so the create/start modal can preview exactly
	what will be transferred before anything is posted.

	`exploded=1` returns the fully-exploded LEAF raw materials (BOM Explosion
	Items) instead of the top-level components — so a mix/sub-assembly like
	'Smes' resolves down to the real ingredients (sut, qogoz, korobka…). That's
	what a shop-floor operator actually transfers."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg()
	if not bom_no or not frappe.db.exists("BOM", bom_no):
		frappe.throw(f"Unknown BOM: {bom_no}")
	doc = frappe.get_doc("BOM", bom_no)
	if doc.company != company:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	base = flt(doc.quantity) or 1
	factor = flt(qty) / base if flt(qty) > 0 else 1
	src = (doc.get("exploded_items") or []) if int(exploded or 0) else (doc.items or [])
	items = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"qty": flt(r.stock_qty or getattr(r, "qty", 0)) * factor,
			"uom": getattr(r, "stock_uom", None) or getattr(r, "uom", None),
			"rate": flt(r.rate),
			"amount": flt(r.amount) * factor,
			"bom_no": getattr(r, "bom_no", None),
		}
		for r in src
	]
	return {
		"bom_no": doc.name,
		"item": doc.item,
		"item_name": doc.item_name,
		"base_qty": base,
		"target_qty": flt(qty),
		"uom": doc.uom,
		"currency": doc.currency,
		"total_cost": flt(doc.total_cost) * factor,
		"items": items,
	}


@frappe.whitelist()
def wo_transfer_preview(work_order: str):
	"""The exact Material-Transfer-for-Manufacture rows ERPNext itself would build
	for this Work Order — item, qty, uom, source + target warehouse. The operator
	kiosk seeds its transfer list from this so it matches ERPNext 1:1 (the WO's
	required materials with the right quantities and warehouses), regardless of BOM
	nesting. Operators are not handed required_items by the API, so this computes
	them the same way ERPNext does. Operator (own WO) or manager."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	try:
		se = make_stock_entry(work_order, "Material Transfer for Manufacture")
	except Exception as e:  # preview must never hard-fail the kiosk
		frappe.log_error(title="Kassa/mfg: wo_transfer_preview failed", message=f"wo={work_order} err={e}")
		return {"items": [], "from_warehouse": None, "to_warehouse": None}
	stub = se if isinstance(se, dict) else se.as_dict()
	from_wh = to_wh = None
	items = []
	for r in stub.get("items") or []:
		s_wh, t_wh = r.get("s_warehouse"), r.get("t_warehouse")
		from_wh = from_wh or s_wh
		to_wh = to_wh or t_wh
		items.append(
			{
				"item_code": r.get("item_code"),
				"item_name": r.get("item_name")
				or frappe.db.get_value("Item", r.get("item_code"), "item_name"),
				"qty": flt(r.get("qty")),
				"uom": r.get("uom") or r.get("stock_uom"),
				"s_warehouse": s_wh,
				"t_warehouse": t_wh,
			}
		)
	return {"items": items, "from_warehouse": from_wh, "to_warehouse": to_wh}


@frappe.whitelist()
def wo_consumption_preview(work_order: str):
	"""What this caller may still write off — ERPNext's own pending list, narrowed
	to the role they hold on this Work Order.

	The twin of `wo_transfer_preview`, and narrower on purpose. Transfer is one trip
	to the shop floor and carries both roles' material at once; consumption is
	counted per person, so the pouring operator must not be shown the label rolls
	they will then tap through by habit.

	The list itself is ERPNext's, built by the same `make_stock_entry` that builds
	the document the operator posts a moment later — so what the kiosk offers and
	what the entry contains cannot drift apart, and already-consumed quantities drop
	out without us tracking them.

	`unassigned_item_count` is the lines nobody has given a role to. They appear in
	nobody's list and are refused if posted anyway (`_assert_may_consume`), so the
	count is the only thing that keeps them from going quiet — it is what the shift
	lead is meant to see and clear. Managers get those rows themselves.

	Operator (own WO) or manager."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	is_manager = _is_mfg_manager()
	if not is_manager:
		_require_own_work_order(work_order)

	# Resolved before anything can fail: the caller's role is a fact about the Work
	# Order, not about whether ERPNext could build a list. Dropping it on the way out
	# of an empty preview blanks the role badge and the "the rest of this order is
	# X's" line in the kiosk for a reason that has nothing to do with either.
	role = (
		None
		if is_manager
		else _wo_role_of(
			frappe.db.get_value("Work Order", work_order, list(_wo_operator_columns()), as_dict=True)
		)
	)
	empty = {"items": [], "from_warehouse": None, "role": role, "unassigned_item_count": 0, "enabled": False}
	if not _material_consumption_enabled():
		# Not an error: the site is not set up for the split, and the kiosk shows the
		# single-document flow instead of two write-off buttons. Returning nothing is
		# also the safe answer — with the setting off ERPNext would build this list
		# from the full BOM rather than from what is actually left in WIP
		# (`_material_consumption_enabled`), so the rows would be a lie.
		return empty
	try:
		se = make_stock_entry(work_order, _SE_CONSUMPTION)
	except Exception as e:  # preview must never hard-fail the kiosk
		# Routinely reached, not only on breakage: ERPNext refuses the stub once the
		# order is fully produced (fg_completed_qty falls to 0), which is exactly the
		# state a finished order is in when an operator reopens it.
		frappe.log_error(title="Kassa/mfg: wo_consumption_preview failed", message=f"wo={work_order} err={e}")
		return {**empty, "enabled": True}

	stub = se if isinstance(se, dict) else se.as_dict()
	rows = [r for r in (stub.get("items") or []) if not r.get("is_finished_item")]
	roles = _item_roles([r.get("item_code") for r in rows])
	from_wh = next((r.get("s_warehouse") for r in rows if r.get("s_warehouse")), None)

	items = [
		{
			"item_code": r.get("item_code"),
			"item_name": r.get("item_name") or frappe.db.get_value("Item", r.get("item_code"), "item_name"),
			"qty": flt(r.get("qty")),
			"uom": r.get("uom") or r.get("stock_uom"),
			"s_warehouse": r.get("s_warehouse"),
			"operator_role": roles.get(r.get("item_code")) or None,
		}
		for r in rows
		if is_manager or (role and roles.get(r.get("item_code")) == role)
	]
	return {
		"items": items,
		"from_warehouse": from_wh,
		"role": role,
		"unassigned_item_count": len([r for r in rows if not roles.get(r.get("item_code"))]),
		"enabled": True,
	}


@frappe.whitelist()
def create_bom(
	company: str,
	item: str,
	quantity: float,
	items: list | str,
	uom: str | None = None,
	is_default: int = 0,
	submit: int = 0,
):
	"""Create a Bill of Materials. `items` is a list of
	{item_code, qty, uom?, rate?, bom_no?}."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
	if not item or not frappe.db.exists("Item", item):
		frappe.throw(f"Unknown FG item: {item}")
	if flt(quantity) <= 0:
		frappe.throw("Quantity must be positive.")

	if isinstance(items, str):
		items = json.loads(items or "[]")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one raw material line is required.")

	for it in items:
		if not (it or {}).get("item_code"):
			frappe.throw("Each line needs an item_code.")
		if flt((it or {}).get("qty")) <= 0:
			frappe.throw("Each line needs a positive qty.")

	doc = frappe.new_doc("BOM")
	doc.company = company
	doc.item = item
	doc.quantity = flt(quantity)
	if uom:
		doc.uom = uom
	doc.is_active = 1
	doc.is_default = 1 if int(is_default or 0) else 0

	for it in items:
		row = doc.append("items", {})
		row.item_code = it["item_code"]
		row.qty = flt(it.get("qty"))
		if it.get("uom"):
			row.uom = it["uom"]
		if it.get("rate") not in (None, ""):
			row.rate = flt(it["rate"])
		if it.get("bom_no"):
			row.bom_no = it["bom_no"]

	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def submit_bom(name: str):
	_assert_can_write("BOM", name, "submit")
	_require_mfg_manager()
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus != 0:
		frappe.throw("BOM is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_bom(name: str):
	_assert_can_write("BOM", name, "cancel")
	_require_mfg_manager()
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted BOMs can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


# ----- Work Orders ---------------------------------------------------------


_WO_STATUSES = ("Draft", "Not Started", "In Process", "Completed", "Stopped", "Closed", "Cancelled")


@frappe.whitelist()
def list_work_orders(
	company: str,
	status: str | None = None,
	search: str = "",
	limit: int = 100,
):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg()
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if status and status in _WO_STATUSES:
		conds.append("status = %(status)s")
		params["status"] = status
	if search:
		conds.append("(name LIKE %(s)s OR production_item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	assignee_cols = _wo_operator_columns()
	# Operators see only WOs assigned to themselves; managers see all. Assigned in
	# EITHER role — the packer has to reach the same order as the pourer.
	if not _is_mfg_manager():
		conds.append("(" + " OR ".join(f"`{col}` = %(user)s" for col in assignee_cols) + ")")
		params["user"] = frappe.session.user
	where = " AND ".join(conds)
	assignee_select = "".join(f"{col}, " for col in assignee_cols)
	return frappe.db.sql(
		f"""
		SELECT name, production_item, item_name, bom_no, qty, produced_qty,
		       material_transferred_for_manufacturing AS transferred_qty,
		       status, planned_start_date, planned_end_date, fg_warehouse,
		       wip_warehouse, {assignee_select}docstatus, modified
		FROM `tabWork Order`
		WHERE {where}
		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def work_order_detail(name: str):
	_assert_can_read("Work Order", name)
	_require_mfg()
	if not name or not frappe.db.exists("Work Order", name):
		frappe.throw(f"Unknown Work Order: {name}")
	doc = frappe.get_doc("Work Order", name)
	is_manager = _is_mfg_manager()
	is_warehouse = _is_warehouse_role()

	# IDOR guard: operators may only view their own WOs, but managers and warehouse staff can view any WO.
	if not (is_manager or is_warehouse or _is_wo_assignee(doc)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	item_roles = _item_roles([r.item_code for r in (doc.required_items or [])])
	required = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"required_qty": flt(r.required_qty),
			"transferred_qty": flt(r.transferred_qty),
			"consumed_qty": flt(r.consumed_qty),
			"source_warehouse": r.source_warehouse,
			"operator_role": item_roles.get(r.item_code) or None,
			# Rates reveal BOM cost data — only managers see them.
			**({"rate": flt(r.rate), "amount": flt(r.amount)} if is_manager else {}),
		}
		for r in (doc.required_items or [])
	]
	my_role = _wo_role_of(doc)
	payload: dict = {
		"name": doc.name,
		"production_item": doc.production_item,
		"item_name": doc.item_name,
		"qty": flt(doc.qty),
		"produced_qty": flt(doc.produced_qty),
		"transferred_qty": flt(doc.material_transferred_for_manufacturing),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"planned_start_date": str(doc.planned_start_date) if doc.planned_start_date else None,
		"planned_end_date": str(doc.planned_end_date) if doc.planned_end_date else None,
		"fg_warehouse": doc.fg_warehouse,
		"wip_warehouse": doc.wip_warehouse,
		"source_warehouse": doc.source_warehouse,
		"company": doc.company,
		# The deviation panel totals in money because litres, kilograms and pieces
		# cannot be added; the reader has to know which money. A Work Order carries
		# no currency of its own, so it is the company's.
		"currency": frappe.get_cached_value("Company", doc.company, "default_currency"),
		"operator": doc.get("operator") or None,
		"packaging_operator": doc.get("packaging_operator") or None,
		"batch_no": doc.get("custom_batch_no") or None,
		"batch_mfg_date": str(doc.custom_batch_mfg_date) if doc.get("custom_batch_mfg_date") else None,
		"batch_expiry": str(doc.custom_batch_expiry) if doc.get("custom_batch_expiry") else None,
	}
	# bom_no reveals BOM structure — managers only.
	if is_manager:
		payload["bom_no"] = doc.bom_no
		payload["timeline"] = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": name},
			fields=["name", "content", "owner", "creation", "comment_by"],
			order_by="creation desc",
		)
	#: Which of the two roles the caller holds here, and how many material lines
	#: belong to neither. v98 ships `custom_operator_role` empty on every existing
	#: Item, so on day one that count is every line — which is the point: an
	#: undecided line has to be visible on the screen, not defaulted onto whichever
	#: operator happens to open the order.
	payload["my_role"] = my_role
	# Manager-only, and not because of the money: the panel answers "who ran over
	# plan", which is a question about a named person's shift. `_role_deviation`
	# withholds the cost on its own, but the whole comparison belongs upstairs.
	if is_manager:
		payload["role_deviation"] = _role_deviation(required, with_cost=True)
	payload["unassigned_item_count"] = len(_unassigned_rows(required, item_roles))
	# Managers and warehouse users stage the transfer, which is one document for the
	# whole order, so they keep the whole list — and an undecided line is theirs.
	# An operator gets only the lines their own role writes off: hand a pourer the
	# label rows and that loss lands on the wrong person's KPI, silently.
	if is_manager or is_warehouse:
		payload["required_items"] = required
	elif my_role:
		payload["required_items"] = _rows_for_role(required, item_roles, my_role)
	return payload


@frappe.whitelist()
def create_work_order(
	company: str,
	production_item: str,
	qty: float,
	bom_no: str | None = None,
	planned_start_date: str | None = None,
	fg_warehouse: str | None = None,
	wip_warehouse: str | None = None,
	source_warehouse: str | None = None,
	operator: str | None = None,
	packaging_operator: str | None = None,
	submit: int = 0,
):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
	if not production_item or not frappe.db.exists("Item", production_item):
		frappe.throw(f"Unknown item: {production_item}")
	if flt(qty) <= 0:
		frappe.throw("Quantity must be positive.")
	for candidate in (operator, packaging_operator):
		if candidate and not frappe.db.exists("User", candidate):
			frappe.throw(_("Unknown user: {0}").format(candidate))
	_assert_distinct_operators(operator, packaging_operator)

	if not bom_no:
		bom_no = frappe.db.get_value(
			"BOM",
			{"item": production_item, "is_default": 1, "is_active": 1, "docstatus": 1},
			"name",
		)
		if not bom_no:
			frappe.throw(f"No default active BOM exists for {production_item}.")

	doc = frappe.new_doc("Work Order")
	doc.company = company
	doc.production_item = production_item
	doc.bom_no = bom_no
	doc.qty = flt(qty)
	if planned_start_date:
		doc.planned_start_date = planned_start_date
	if fg_warehouse:
		doc.fg_warehouse = fg_warehouse
	if wip_warehouse:
		doc.wip_warehouse = wip_warehouse
	if source_warehouse:
		doc.source_warehouse = source_warehouse
	if operator:
		doc.operator = operator
	if packaging_operator:
		_require_wo_operator_column("packaging_operator")
		doc.packaging_operator = packaging_operator

	doc.set_work_order_operations()
	doc.get_items_and_operations_from_bom()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def submit_work_order(name: str):
	"""Release a Work Order from Draft → Not Started. Manager-only action."""
	_assert_can_write("Work Order", name, "submit")
	_require_mfg_manager()
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 0:
		frappe.throw("Work Order is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def stop_work_order(name: str, reason: str = "Production Stopped"):
	_assert_can_write("Work Order", name, "write")
	from erpnext.manufacturing.doctype.work_order.work_order import stop_unstop

	_require_mfg()
	if not _is_mfg_manager():
		_require_own_work_order(name)
	stop_unstop(name, "Stopped")
	_log_wo_event(name, f"Work Order paused: {reason}")
	return {"name": name, "status": frappe.db.get_value("Work Order", name, "status")}


@frappe.whitelist()
def resume_work_order(name: str):
	"""Resume a previously stopped Work Order."""
	_assert_can_write("Work Order", name, "write")
	from erpnext.manufacturing.doctype.work_order.work_order import stop_unstop

	_require_mfg()
	if not _is_mfg_manager():
		_require_own_work_order(name)
	stop_unstop(name, "Resumed")
	_log_wo_event(name, "Work Order resumed")
	return {"name": name, "status": frappe.db.get_value("Work Order", name, "status")}


@frappe.whitelist()
def close_work_order(name: str):
	"""Finalize a completed Work Order. Manager-only."""
	_assert_can_write("Work Order", name, "write")
	_require_mfg_manager()
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted Work Orders can be closed.")
	doc.status = "Closed"
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def make_work_order_stock_entry(
	work_order: str,
	purpose: str,
	qty: float | None = None,
	scrap_qty: float | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	items: str | None = None,
	batch_no: str | None = None,
	mfg_date: str | None = None,
	expiry_date: str | None = None,
):
	"""Generate and submit a Stock Entry for material transfer or manufacture.

	`scrap_qty` is accepted for the Manufacture purpose and recorded as
	process loss (operator-reported rejects). On Manufacture, an optional
	`batch_no` (+ mfg/expiry) is stamped on the Work Order for lot traceability
	(Faz 4a) — informational only, does not touch the stock batch engine."""
	import json

	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry
	from erpnext.stock.get_item_details import get_conversion_factor

	_require_mfg()
	if purpose not in _SE_PURPOSES:
		frappe.throw(f"Unsupported purpose: {purpose}")
	is_manager = _is_mfg_manager()
	if not is_manager:
		_require_own_work_order(work_order)

	item_list: list = []
	if items:
		try:
			item_list = json.loads(items)
		except Exception:
			frappe.throw("Invalid items format.")

	# Parsed before the document is built: a consumption entry that names the wrong
	# role's material must be refused before anything is inserted, not unwound after.
	if purpose == _SE_CONSUMPTION:
		_assert_may_consume(work_order, item_list, role_scoped=not is_manager)
	elif purpose == "Material Transfer for Manufacture":
		# The first stock document of the order, and the last moment a missing
		# assignee is cheap to fix: after this the material is in WIP and somebody
		# has to write it off under a name.
		_assert_roles_are_both_or_neither(work_order)

	doc = make_stock_entry(work_order, purpose, qty=flt(qty) if qty else None)
	stub = doc if isinstance(doc, dict) else doc.as_dict()
	se = frappe.get_doc(stub)

	if purpose == "Manufacture" and scrap_qty and flt(scrap_qty) > 0:
		se.process_loss_qty = flt(scrap_qty)

	if items:
		if from_warehouse:
			se.from_warehouse = from_warehouse
		if to_warehouse:
			se.to_warehouse = to_warehouse

		se.set("items", [])
		for it in item_list:
			row = se.append("items", {})
			row.item_code = it["item_code"]
			row.qty = flt(it["qty"])
			row.s_warehouse = it.get("s_warehouse") or from_warehouse or se.from_warehouse
			row.t_warehouse = it.get("t_warehouse") or to_warehouse or se.to_warehouse
			uom = it.get("uom")
			if uom:
				row.uom = uom
			# set_missing_values() does NOT populate conversion_factor, only validates it.
			row.conversion_factor = (
				get_conversion_factor(it["item_code"], uom or None).get("conversion_factor") or 1.0
			)
			row.allow_zero_valuation_rate = 1
		se.set_missing_values()
	else:
		if from_warehouse:
			se.from_warehouse = from_warehouse
		if to_warehouse:
			se.to_warehouse = to_warehouse
		for item in se.items:
			if from_warehouse and purpose in ("Material Transfer for Manufacture", "Material Issue"):
				item.s_warehouse = from_warehouse
			if to_warehouse and purpose in ("Material Transfer for Manufacture", "Material Receipt"):
				item.t_warehouse = to_warehouse
			item.allow_zero_valuation_rate = 1

	if purpose == _SE_CONSUMPTION:
		# ERPNext's make_stock_entry puts fg_warehouse on the header for every
		# purpose that is not a transfer (work_order.py, the `else` branch), and its
		# own get_items() then leaves each row's t_warehouse empty — measured on
		# genesis-test, 2026-08-25. Consumed material leaves WIP and does not arrive
		# anywhere, so that is right. The `items` override above is what breaks it:
		# it fills every row from `se.to_warehouse`, which would receipt raw milk
		# into finished goods and value the order twice.
		se.to_warehouse = None
		for row in se.items:
			row.t_warehouse = None

	assert_stock_entry_valuation_sane(se)
	se.insert(ignore_permissions=False)
	se.submit()

	if purpose == "Material Transfer for Manufacture":
		_log_wo_event(work_order, "Work Order started (materials transferred)")
	elif purpose == _SE_CONSUMPTION:
		# Named per person on purpose: this is the record that says whose number the
		# write-off landed on, and it is the only one a manager can read back after
		# the fact without joining Stock Entry Detail to the item catalogue.
		what = ", ".join(f"{it['item_code']} x {flt(it.get('qty'))}" for it in item_list)
		_log_wo_event(work_order, f"Materials written off by {frappe.session.user}: {what}")
	elif purpose == "Manufacture":
		if (batch_no or "").strip():
			_stamp_wo_batch(work_order, batch_no, mfg_date, expiry_date)
		batch_note = f", Batch: {batch_no}" if (batch_no or "").strip() else ""
		_log_wo_event(
			work_order, f"Work Order finished. Produced: {flt(qty)}, Rejects: {flt(scrap_qty)}{batch_note}"
		)

	return {"name": se.name, "purpose": purpose, "docstatus": se.docstatus}


@frappe.whitelist()
def assign_work_order_operator(name: str, operator: str = "", packaging_operator: str = ""):
	"""Set both shop-floor operator roles on this Work Order. Manager-only.

	Both roles are written in one call because they are validated against each
	other. Assigning them one at a time cannot express a swap: going from
	(A pours, B packs) to (B pours, A packs) passes through a state where B holds
	both, and a per-role endpoint would refuse the second half of the very move it
	was asked to make. The pair is the unit the constraint is about, so the pair is
	the unit that gets written.

	An empty string clears that role — the "— Remove operator —" option in the SPA.
	"""
	_assert_can_write("Work Order", name, "write")
	_require_mfg_manager()
	if not frappe.db.exists("Work Order", name):
		frappe.throw(f"Unknown Work Order: {name}")
	assignment = {"operator": operator or None, "packaging_operator": packaging_operator or None}
	for who in assignment.values():
		if who and not frappe.db.exists("User", who):
			frappe.throw(_("Unknown user: {0}").format(who))
	_assert_distinct_operators(assignment["operator"], assignment["packaging_operator"])

	for field, who in assignment.items():
		if who:
			_require_wo_operator_column(field)
		if field in _wo_operator_columns():
			frappe.db.set_value("Work Order", name, field, who)
	return {"name": name, **assignment}


# ----- Batch / lot traceability (Faz 4a) -----------------------------------
#
# One Work Order == one production batch. We stamp the lot number + mfg/expiry
# on the WO (custom fields, patch v53) and derive genealogy from the WO's own
# submitted Stock Entries — no change to ERPNext's Batch/Bundle stock engine, so
# it's safe for every tenant and dormant until a WO is given a batch number.


def _suggest_batch_no(doc) -> str:
	"""'<ITEM>-<YYYYMMDD>' with a -N suffix when the day already has batches."""
	from frappe.utils import nowdate

	base = f"{doc.production_item}-{getdate(doc.planned_start_date or nowdate()).strftime('%Y%m%d')}"
	existing = frappe.db.count("Work Order", {"custom_batch_no": ["like", f"{base}%"]})
	return base if not existing else f"{base}-{existing + 1}"


@frappe.whitelist()
def suggest_wo_batch(work_order: str):
	"""A suggested batch id + default mfg/expiry for the finish dialog.

	Expiry defaults to mfg + Item.shelf_life_in_days when the item defines one."""
	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	doc = frappe.get_doc("Work Order", work_order)
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	mfg = today()
	shelf = frappe.db.get_value("Item", doc.production_item, "shelf_life_in_days")
	expiry = frappe.utils.add_days(mfg, int(shelf)) if shelf and int(shelf) > 0 else None
	return {
		"batch_no": doc.get("custom_batch_no") or _suggest_batch_no(doc),
		"mfg_date": (doc.get("custom_batch_mfg_date") and str(doc.custom_batch_mfg_date)) or mfg,
		"expiry_date": (doc.get("custom_batch_expiry") and str(doc.custom_batch_expiry)) or expiry,
	}


def _stamp_wo_batch(work_order, batch_no, mfg_date=None, expiry_date=None) -> None:
	"""Set the batch custom fields on a (possibly submitted) Work Order."""
	frappe.db.set_value(
		"Work Order",
		work_order,
		{
			"custom_batch_no": (batch_no or "").strip() or None,
			"custom_batch_mfg_date": mfg_date or None,
			"custom_batch_expiry": expiry_date or None,
		},
	)


@frappe.whitelist()
def set_wo_batch(work_order: str, batch_no: str, mfg_date: str | None = None, expiry_date: str | None = None):
	"""Record the production batch/lot for a Work Order. Operator (own WO) or manager."""
	_assert_can_write("Work Order", work_order, "write")
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	if not (batch_no or "").strip():
		frappe.throw(_("Batch number is required."))
	_stamp_wo_batch(work_order, batch_no, mfg_date, expiry_date)
	return {"name": work_order, "batch_no": batch_no.strip()}


@frappe.whitelist()
def wo_genealogy(work_order: str):
	"""Backward traceability for a Work Order's batch: the raw materials
	(item, qty, source warehouse, voucher) that were transferred in, plus the
	produced batch header. Read from the WO's own submitted Stock Entries."""
	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	doc = frappe.get_doc("Work Order", work_order)
	if not (_is_mfg_manager() or _is_warehouse_role() or _is_wo_assignee(doc)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	consumed = frappe.db.sql(
		"""
		SELECT sed.item_code, sed.item_name, sed.qty, sed.uom,
		       sed.s_warehouse AS warehouse, se.name AS stock_entry, se.posting_date
		FROM `tabStock Entry` se
		JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE se.work_order = %(wo)s AND se.docstatus = 1
		  AND se.purpose = 'Material Transfer for Manufacture'
		ORDER BY se.posting_date, sed.idx
		""",
		{"wo": work_order},
		as_dict=True,
	)
	for c in consumed:
		c["qty"] = flt(c["qty"])
	return {
		"work_order": doc.name,
		"produced": {
			"item_code": doc.production_item,
			"item_name": doc.item_name,
			"qty": flt(doc.produced_qty),
			"batch_no": doc.get("custom_batch_no") or None,
			"mfg_date": str(doc.custom_batch_mfg_date) if doc.get("custom_batch_mfg_date") else None,
			"expiry_date": str(doc.custom_batch_expiry) if doc.get("custom_batch_expiry") else None,
		},
		"consumed": consumed,
	}


@frappe.whitelist()
def list_operators(company: str):
	"""Users with Manufacturing User or Manager role. Manager-only."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_mfg_manager()
	_require_company(company)
	return frappe.db.sql(
		"""
		SELECT DISTINCT u.name, u.full_name, u.user_image
		FROM `tabUser` u
		JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE hr.role IN ('Manufacturing User', 'Manufacturing Manager')
		  AND u.enabled = 1
		  AND u.name != 'Administrator'
		ORDER BY u.full_name ASC
		""",
		as_dict=True,
	)


@frappe.whitelist()
def manufacturable_items(company: str, search: str = "", limit: int = 50):
	"""Items that have at least one submitted, active BOM in this company."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
	conds = ["b.company = %(company)s", "b.is_active = 1", "b.docstatus = 1"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(i.item_code LIKE %(s)s OR i.item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT DISTINCT i.name AS item_code, i.item_name, i.stock_uom
		FROM `tabItem` i
		JOIN `tabBOM` b ON b.item = i.name
		WHERE {where} AND i.disabled = 0
		ORDER BY i.item_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


def _log_wo_event(work_order: str, text: str):
	"""Log a timestamped event comment on the Work Order."""
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Work Order",
			"reference_name": work_order,
			"content": text,
			"comment_email": frappe.session.user,
			"comment_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)


# ------------------ RFID & PIN Authentication ------------------

# Legacy salt — kept ONLY as a fallback so badge/PIN records hashed before the
# per-site secret was introduced keep matching. New deployments must set a random
# `stabler_rfid_salt` in site_config.json; see _kiosk_salt().
_LEGACY_RFID_SALT = "stabler_rfid_salt"


def _kiosk_salt() -> str:
	"""Per-site RFID/PIN salt from site_config, falling back to the legacy constant.

	The constant is public (it shipped in source), so it provides no secrecy — set
	`stabler_rfid_salt` in site_config.json to a random value per site."""
	return frappe.conf.get("stabler_rfid_salt") or _LEGACY_RFID_SALT


def _verify_kiosk_token() -> None:
	"""Gate the guest badge/PIN endpoints behind a device-level shared secret.

	badge_login/pin_login are `allow_guest=True` and mint a full session, so they
	MUST authenticate the calling kiosk before doing any work. The secret lives in
	site_config.json (`stabler_kiosk_token`) and is sent by the kiosk in the
	`X-Stabler-Kiosk-Token` header (header, not a body/query param, so it does not
	land in access logs). Fails closed if the secret is not configured."""
	import hmac

	expected = frappe.conf.get("stabler_kiosk_token")
	if not expected:
		# Misconfigured site → refuse rather than silently allowing open access.
		frappe.throw(_("Kiosk login is not configured on this site."), frappe.PermissionError)
	provided = ""
	try:
		provided = frappe.get_request_header("X-Stabler-Kiosk-Token") or ""
	except Exception:
		provided = ""
	if not provided or not hmac.compare_digest(str(provided), str(expected)):
		frappe.throw(_("Invalid kiosk credentials."), frappe.PermissionError)


def get_hashes(val: str) -> list[str]:
	"""Return plain value and its salted/unsalted SHA256 hashes."""
	import hashlib

	if not val:
		return []
	res = [val]
	# Unsalted SHA256
	res.append(hashlib.sha256(val.encode("utf-8")).hexdigest())
	# Salted SHA256 (per-site salt, legacy fallback for old records)
	res.append(hashlib.sha256((val + _kiosk_salt()).encode("utf-8")).hexdigest())
	return res


def match_employee_badge(uid: str):
	"""Find active employee by RFID badge UID."""
	if not uid:
		return None
	employees = frappe.get_all(
		"Employee", fields=["name", "user_id", "attendance_device_id"], filters={"status": "Active"}
	)
	uid_options = get_hashes(uid)
	for emp in employees:
		device_id = (emp.attendance_device_id or "").strip()
		if not device_id:
			continue
		# Check colon-separated e.g. "card_uid:pin"
		if ":" in device_id:
			card_part = device_id.split(":", 1)[0].strip()
		else:
			card_part = device_id

		if card_part in uid_options:
			return emp
		for h in get_hashes(card_part):
			if h in uid_options:
				return emp
	return None


def match_employee_pin(employee_id: str, pin: str):
	"""Find active employee by ID and match their PIN."""
	if not employee_id or not pin:
		return None
	if not frappe.db.exists("Employee", employee_id):
		return None
	emp = frappe.get_doc("Employee", employee_id)
	if emp.status != "Active":
		return None

	device_id = (emp.attendance_device_id or "").strip()
	if not device_id or ":" not in device_id:
		return None

	pin_part = device_id.split(":", 1)[1].strip()
	pin_options = get_hashes(pin)

	if pin_part in pin_options:
		return emp
	for h in get_hashes(pin_part):
		if h in pin_options:
			return emp
	return None


@frappe.whitelist(allow_guest=True)
def badge_login(uid: str):
	import hashlib

	_verify_kiosk_token()
	if not uid:
		frappe.throw(_("Badge UID is required."), frappe.ValidationError)

	ip = frappe.local.ip
	# Per-IP AND per-badge lockout: per-IP alone is defeated by rotating source IPs,
	# so also throttle attempts against a specific (low-entropy) card UID.
	uid_key = f"badge_login_fail:uid:{hashlib.sha256(uid.encode('utf-8')).hexdigest()}"
	fail_key = f"badge_login_fail:{ip}"
	fails = frappe.cache().get_value(fail_key) or 0
	uid_fails = frappe.cache().get_value(uid_key) or 0
	if fails >= 5 or uid_fails >= 5:
		frappe.throw(_("Too many failed attempts. Please try again in 5 minutes."), frappe.PermissionError)

	emp = match_employee_badge(uid)
	if not emp:
		frappe.cache().set_value(fail_key, fails + 1, expires_in_sec=300)
		frappe.cache().set_value(uid_key, uid_fails + 1, expires_in_sec=300)
		frappe.get_doc(
			{
				"doctype": "Activity Log",
				"subject": "Failed Badge Login",
				"status": "Failure",
				"operation": "Badge Login",
				"remark": f"IP: {ip}, Scan UID: {uid[:4]}***",
			}
		).insert(ignore_permissions=True)
		frappe.throw(_("Card not recognized"), frappe.PermissionError)

	if not emp.user_id:
		frappe.throw(_("Employee has no linked user account."), frappe.PermissionError)

	frappe.cache().delete_key(fail_key)
	frappe.cache().delete_key(uid_key)

	from frappe.auth import LoginManager

	login_manager = LoginManager()
	login_manager.login_as(emp.user_id)

	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"subject": f"Successful Badge Login: {emp.user_id}",
			"status": "Success",
			"operation": "Badge Login",
			"user": emp.user_id,
		}
	).insert(ignore_permissions=True)

	return {
		"message": "Logged in",
		"user": emp.user_id,
		"employee": emp.name,
		"full_name": frappe.db.get_value("User", emp.user_id, "full_name"),
	}


@frappe.whitelist(allow_guest=True)
def pin_login(employee: str, pin: str):
	import hashlib

	_verify_kiosk_token()
	if not employee or not pin:
		frappe.throw(_("Employee ID and PIN are required."), frappe.ValidationError)

	ip = frappe.local.ip
	# Per-IP AND per-employee lockout: the employee id is enumerable and the PIN is
	# short, so a per-IP-only throttle is trivially bypassed by rotating IPs.
	emp_key = f"pin_login_fail:emp:{hashlib.sha256(employee.encode('utf-8')).hexdigest()}"
	fail_key = f"pin_login_fail:{ip}"
	fails = frappe.cache().get_value(fail_key) or 0
	emp_fails = frappe.cache().get_value(emp_key) or 0
	if fails >= 5 or emp_fails >= 5:
		frappe.throw(_("Too many failed attempts. Please try again in 5 minutes."), frappe.PermissionError)

	emp = match_employee_pin(employee, pin)
	if not emp:
		frappe.cache().set_value(fail_key, fails + 1, expires_in_sec=300)
		frappe.cache().set_value(emp_key, emp_fails + 1, expires_in_sec=300)
		frappe.get_doc(
			{
				"doctype": "Activity Log",
				"subject": "Failed PIN Login",
				"status": "Failure",
				"operation": "PIN Login",
				"remark": f"IP: {ip}, Employee: {employee}",
			}
		).insert(ignore_permissions=True)
		frappe.throw(_("Card not recognized"), frappe.PermissionError)

	if not emp.user_id:
		frappe.throw(_("Employee has no linked user account."), frappe.PermissionError)

	frappe.cache().delete_key(fail_key)
	frappe.cache().delete_key(emp_key)

	from frappe.auth import LoginManager

	login_manager = LoginManager()
	login_manager.login_as(emp.user_id)

	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"subject": f"Successful PIN Login: {emp.user_id}",
			"status": "Success",
			"operation": "PIN Login",
			"user": emp.user_id,
		}
	).insert(ignore_permissions=True)

	return {
		"message": "Logged in",
		"user": emp.user_id,
		"employee": emp.name,
		"full_name": frappe.db.get_value("User", emp.user_id, "full_name"),
	}


@frappe.whitelist(allow_guest=True)
def badge_logout():
	from frappe.auth import LoginManager

	LoginManager().logout()
	return {"message": "Success"}


def create_material_request_for_tomorrow_wo(doc, method=None):
	"""Hook function triggered on Work Order submit (doc_events).
	If planned_start_date is tomorrow or later, creates a Material Request for any shortages in wip_warehouse.
	"""
	from frappe.utils import add_days, getdate, today

	if not doc.wip_warehouse:
		return

	tomorrow = getdate(add_days(today(), 1))
	if getdate(doc.planned_start_date) < tomorrow:
		return

	# Check if a Material Request already exists for this Work Order to avoid duplicate creation
	if frappe.db.exists("Material Request", {"work_order": doc.name, "docstatus": ["!=", 2]}):
		return

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Transfer"
	mr.transaction_date = today()
	mr.company = doc.company
	mr.schedule_date = doc.planned_start_date
	mr.work_order = doc.name

	for item in doc.required_items:
		actual = (
			frappe.db.get_value(
				"Bin", {"item_code": item.item_code, "warehouse": doc.wip_warehouse}, "actual_qty"
			)
			or 0.0
		)
		needed = flt(item.required_qty)
		if actual < needed:
			shortage = needed - actual
			mr.append(
				"items",
				{
					"item_code": item.item_code,
					"qty": shortage,
					"warehouse": doc.wip_warehouse,
					"schedule_date": doc.planned_start_date,
				},
			)

	if mr.items:
		mr.insert(ignore_permissions=True)
		mr.submit()


@frappe.whitelist()
def update_work_order_materials(work_order: str, materials: str):
	"""Update required quantities of raw materials for a Work Order.
	`materials` is a JSON string containing a list of dicts: [{'item_code': '...', 'required_qty': 12.3}]

	Also triggers/re-runs Material Request creation for any updated shortages if the WO is scheduled for tomorrow/future.
	"""
	import json

	_require_mfg()

	doc = frappe.get_doc("Work Order", work_order)
	if not doc:
		frappe.throw(f"Unknown Work Order: {work_order}")

	# Operators can only edit their own assigned Work Orders
	if not _is_mfg_manager():
		_require_own_work_order(work_order)

	try:
		mat_list = json.loads(materials)
	except Exception:
		frappe.throw("Invalid materials format.")

	# Update the quantities in the child table directly
	for m in mat_list:
		item_code = m.get("item_code")
		new_qty = flt(m.get("required_qty"))

		# Update required_qty directly in db to bypass docstatus read-only restriction
		frappe.db.sql(
			"""
			UPDATE `tabWork Order Item`
			SET required_qty = %s
			WHERE parent = %s AND item_code = %s
			""",
			(new_qty, work_order, item_code),
		)

	# Log the event
	_log_wo_event(work_order, f"Raw materials manually adjusted by {frappe.session.user}")

	# Reload document to reflect database changes
	doc.reload()

	# If it's a tomorrow or future WO, create/update Material Request for any new shortages
	from frappe.utils import add_days, getdate, today

	tomorrow = getdate(add_days(today(), 1))
	if doc.wip_warehouse and getdate(doc.planned_start_date) >= tomorrow:
		# Cancel existing draft/submitted Material Request for this WO and create a fresh one with updated shortages
		existing_mrs = frappe.get_all(
			"Material Request", filters={"work_order": doc.name, "docstatus": ["!=", 2]}, pluck="name"
		)
		for mr_name in existing_mrs:
			try:
				mr_doc = frappe.get_doc("Material Request", mr_name)
				if mr_doc.docstatus == 1:
					mr_doc.cancel()
				elif mr_doc.docstatus == 0:
					frappe.delete_doc("Material Request", mr_name)
			except Exception:
				pass

		# Create fresh MR
		mr = frappe.new_doc("Material Request")
		mr.material_request_type = "Transfer"
		mr.transaction_date = today()
		mr.company = doc.company
		mr.schedule_date = doc.planned_start_date
		mr.work_order = doc.name

		for item in doc.required_items:
			actual = (
				frappe.db.get_value(
					"Bin", {"item_code": item.item_code, "warehouse": doc.wip_warehouse}, "actual_qty"
				)
				or 0.0
			)
			needed = flt(item.required_qty)
			if actual < needed:
				shortage = needed - actual
				mr.append(
					"items",
					{
						"item_code": item.item_code,
						"qty": shortage,
						"warehouse": doc.wip_warehouse,
						"schedule_date": doc.planned_start_date,
					},
				)

		if mr.items:
			mr.insert(ignore_permissions=True)
			mr.submit()

	return {"ok": True}
