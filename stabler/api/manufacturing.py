"""Manufacturing module — BOMs, Work Orders, Production Plan basics."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

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


_BULK_ASSIGN_CLOSED = ("Completed", "Closed", "Cancelled")


def _partition_bulk_assign(names, rows, company: str) -> tuple[list[str], list[dict]]:
	"""Split the requested ids into "will be assigned" and "will not, and here is why".

	Pure and separate from the endpoint so the one property the whole gesture rests
	on can be held without a database: **every id the caller sent comes back exactly
	once**, in one list or the other. A sweep that quietly drops four ids out of
	thirty returns the same cheerful success as one that touched all thirty.

	A finished order is refused rather than swept. Changing the operator on a
	Completed or Closed Work Order rewrites who is credited for a shift that is
	already over, against which per-role consumption entries are already posted.
	The detail panel still allows it one order at a time, which is where a
	deliberate correction belongs.
	"""
	by_name = {row["name"]: row for row in rows}
	assign: list[str] = []
	skipped: list[dict] = []
	seen: set[str] = set()
	for name in names:
		if name in seen:  # a double-clicked checkbox is one order, not two writes
			continue
		seen.add(name)
		row = by_name.get(name)
		if row is None:
			# Absent from the query result, so nothing further down would ever
			# mention it: thirty sent, twenty-eight assigned, two typos silent.
			skipped.append({"name": name, "reason": _("No longer exists")})
		elif row.get("company") != company:
			# One app, seven businesses. A foreign id here is a bug or an attempt,
			# and either way the answer is to name it rather than drop it.
			skipped.append({"name": name, "reason": _("Belongs to another company")})
		elif cint(row.get("docstatus")) == 2:
			# `docstatus` is the truth about a cancelled document; `status` is a
			# field somebody can leave stale.
			skipped.append({"name": name, "reason": _("Cancelled")})
		elif row.get("status") in _BULK_ASSIGN_CLOSED:
			skipped.append({"name": name, "reason": _("Already {0}").format(_(row["status"]))})
		else:
			assign.append(name)
	return assign, skipped


def _bulk_pair_after(row, assignment: dict) -> dict:
	"""The operator pair an order would end up with once the bulk dialog is applied.

	A role the manager left empty keeps whoever is already on the order. This is
	deliberately unlike `assign_work_order_operator`, where an empty box clears the
	role: on one order that is the "— Remove operator —" choice, but across a
	selection it would read a manager's silence about packing as an instruction to
	strip every packer.
	"""
	return {field: assignment.get(field) or row.get(field) for field in _WO_FIELD_ROLE}


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


#: The Work Order columns holding an unconfirmed finish (patch v99). The payload
#: is one field because it is only ever read back into the dialog that wrote it;
#: the author and the time are separate columns because they are the two things
#: somebody else asks about a draft, and because the server must own them.
_WO_DRAFT_FIELDS = ("custom_finish_draft", "custom_finish_draft_at", "custom_finish_draft_by")

#: What a caller may put inside the draft. Anything else it sends is dropped —
#: `saved_by` in particular, which the server writes as a column of its own.
_FINISH_DRAFT_NUMBERS = ("produced_qty", "scrap_qty")
_FINISH_DRAFT_STRINGS = ("batch_no", "mfg_date", "expiry_date")


def _wo_draft_columns() -> tuple[str, ...]:
	"""The draft columns that actually exist on this site (patch v99).

	Same shape as `_wo_operator_columns`, same reason: between a code deploy and
	the `bench migrate` behind it, naming a column that is not there takes the
	kiosk down for every operator on the site.
	"""
	return tuple(f for f in _WO_DRAFT_FIELDS if frappe.db.has_column("Work Order", f))


def _require_wo_draft_columns() -> None:
	"""Refuse to *save* a draft the site cannot hold.

	Reading degrades quietly — no columns means no draft, and the dialog opens
	blank, which is what it did before v99. Writing must not: an operator who has
	walked the pallet and pressed save has to be told the count did not land, in
	the moment, while the pallet is still there. This is the v94 lesson that v97
	restated — a write that reports success and goes nowhere is worse than an
	error, because nothing ever says so.
	"""
	if len(_wo_draft_columns()) != len(_WO_DRAFT_FIELDS):
		frappe.throw(_("This site is not migrated for unconfirmed finishes yet."))


def _clear_finish_draft(work_order: str) -> None:
	"""Drop the draft. Silent on an unmigrated site: the absence of the feature is
	not a reason to refuse the document that closes the order."""
	columns = _wo_draft_columns()
	if not columns:
		return
	for field in columns:
		frappe.db.set_value("Work Order", work_order, field, None, update_modified=False)


def _encode_finish_draft(
	produced_qty=0,
	scrap_qty=0,
	batch_no: str | None = None,
	mfg_date: str | None = None,
	expiry_date: str | None = None,
) -> str:
	"""The dialog's contents as one field. Named arguments rather than a passthrough
	dict: whatever a caller adds beyond these five is not stored, so a crafted
	payload cannot smuggle an author or a timestamp in beside them."""
	import json

	return json.dumps(
		{
			"produced_qty": flt(produced_qty),
			"scrap_qty": flt(scrap_qty),
			"batch_no": (batch_no or "").strip() or None,
			"mfg_date": (mfg_date or "").strip() or None,
			"expiry_date": (expiry_date or "").strip() or None,
		}
	)


def _decode_finish_draft(row) -> dict | None:
	"""The draft on this Work Order row, or None when there is not one.

	None covers three different situations on purpose, because the kiosk does the
	same thing in all of them — offers a blank finish dialog:

	  * the site has not run v99 and the columns do not exist yet;
	  * nobody has saved a draft;
	  * the field holds something that is not a draft. It is editable in Desk and
	    outlives schema changes, and an operator cannot fix JSON. Losing one draft
	    is better than taking the kiosk down for a shift over one bad row.

	What it is *not* allowed to cover is a legitimate zero. Nothing good and forty
	rejects is a real shift, and the one you least want to make somebody count
	twice — so emptiness is tested on the field, never on the numbers inside it.

	`saved_at` and `saved_by` are read from the row's own columns, never from the
	payload: with two operators on one order, "whose count is this" decides whether
	the person reading it confirms or re-counts.
	"""
	import json

	raw = (row.get("custom_finish_draft") or "").strip()
	if not raw:
		return None
	try:
		payload = json.loads(raw)
	except Exception:
		return None
	if not isinstance(payload, dict):
		return None
	draft = {k: flt(payload.get(k)) for k in _FINISH_DRAFT_NUMBERS}
	draft.update({k: payload.get(k) or None for k in _FINISH_DRAFT_STRINGS})
	draft["saved_at"] = str(row.get("custom_finish_draft_at") or "") or None
	draft["saved_by"] = row.get("custom_finish_draft_by") or None
	return draft


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


def _assert_roles_are_both_or_neither(work_order: str, purpose: str) -> None:
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
	# `purpose` is required rather than defaulted, and the reason is a bug this
	# already had: one guard now serves two buttons, and the first version reused
	# the transfer sentence for both, so an operator who pressed Finish was told
	# that materials "cannot be transferred" — a gesture they had not performed, on
	# a kiosk with no Desk access to go looking on. A default would let the next
	# caller reintroduce exactly that, silently. Making it required costs one
	# argument and forces whoever adds the third button to pick the verb.
	if purpose == "Manufacture":
		message = _("The order cannot be finished until both operator roles are assigned. Missing: {0}")
	else:
		message = _("Materials cannot be transferred until both operator roles are assigned. Missing: {0}")
	# The role name goes after a colon rather than inside the sentence: it is a
	# stored value ("Production"/"Packaging"), and inlining an English word into
	# the middle of a translated clause reads as a bug in every other language.
	frappe.throw(message.format(", ".join(missing)))


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

	codes = list(dict.fromkeys(it.get("item_code") for it in item_list))
	undecided, foreign = _lines_not_yours(work_order, codes)
	if undecided:
		frappe.throw(
			_("Nobody has decided which operator these materials belong to yet: {0}").format(
				", ".join(undecided)
			)
		)
	if foreign:
		frappe.throw(
			_("These materials are the other operator's to write off, not yours: {0}").format(
				", ".join(foreign)
			)
		)


def _lines_not_yours(work_order: str, codes: list[str]) -> tuple[list[str], list[str]]:
	"""Which of these item codes are not the caller's to touch on this Work
	Order: `(undecided, foreign)`.

	Two lists and not one because they are two different problems with two
	different fixes. A foreign line belongs to the other operator and the caller
	should leave it alone; an undecided line belongs to nobody yet, because v98
	deliberately filled in no roles, and it is the shift lead who has to answer
	it. Telling an operator to "leave the other operator's line alone" about a
	line that has no operator sends them to a colleague who does not exist.

	Split out so `_assert_may_consume` and `update_work_order_materials` decide
	from one answer. They phrase their refusals differently — writing material
	off and rewriting a planned quantity are not the same act, and the message
	has to say which one was refused — but the question underneath is identical,
	and answering it twice is how the two drift apart.
	"""
	row = frappe.db.get_value("Work Order", work_order, list(_wo_operator_columns()), as_dict=True)
	role = _wo_role_of(row)
	roles = _item_roles(codes)
	undecided = [c for c in codes if not roles.get(c)]
	foreign = [c for c in codes if roles.get(c) and roles.get(c) != role]
	return undecided, foreign


def _unconsumed_material_rows(work_order: str) -> list[dict] | None:
	"""Every raw-material line ERPNext still considers unconsumed on this Work
	Order, each tagged with the role that owns it — the computation behind
	`wo_consumption_preview` (which narrows it to the caller's own role) and
	behind `_assert_sweep_is_acknowledged` (which asks the opposite question:
	what has the OTHER role left behind). One call to ERPNext, read two ways,
	rather than two independent guesses at "what is left" that could drift apart.

	Returns None when the site's consumption setting is off:
	`_material_consumption_enabled` measures why an "unconsumed" answer cannot be
	trusted in that state — ERPNext hands back the whole BOM, not what is
	actually left — so a caller must be able to tell "not applicable here" apart
	from "genuinely nothing pending" ([]).
	"""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	if not _material_consumption_enabled():
		return None
	try:
		se = make_stock_entry(work_order, _SE_CONSUMPTION)
	except Exception as e:  # must never hard-fail a preview or a Finish
		frappe.log_error(
			title="Kassa/mfg: _unconsumed_material_rows failed", message=f"wo={work_order} err={e}"
		)
		return []
	stub = se if isinstance(se, dict) else se.as_dict()
	rows = [r for r in (stub.get("items") or []) if not r.get("is_finished_item")]
	roles = _item_roles([r.get("item_code") for r in rows])
	return [
		{
			"item_code": r.get("item_code"),
			"item_name": r.get("item_name") or frappe.db.get_value("Item", r.get("item_code"), "item_name"),
			"qty": flt(r.get("qty")),
			"uom": r.get("uom") or r.get("stock_uom"),
			"s_warehouse": r.get("s_warehouse"),
			"operator_role": roles.get(r.get("item_code")) or None,
		}
		for r in rows
	]


def _assert_consumption_setting_still_holds(work_order: str) -> None:
	"""Refuse to finish an order whose material was already written off per role
	while the site's continuous-consumption setting is now off.

	`Manufacturing Settings.material_consumption` decides which list ERPNext
	builds the Manufacture entry from — `get_unconsumed_raw_materials` when it is
	on, `get_bom_raw_materials` when it is off. On an order the operators have
	already written off, that is the difference between nothing left and the
	whole BOM again, and `Work Order Item.consumed_qty` simply accumulates the
	second helping. Nothing raises. Measured genesis-test 2026-08-26 on
	MFG-WO-2026-00009, two submitted consumption entries against it:

	    material_consumption=1 -> Manufacture stub raw rows: []
	    material_consumption=0 -> Manufacture stub raw rows: [MILK 2.0, LABEL 1.0]

	Narrowed to orders that actually carry submitted consumption entries, and not
	to the setting alone: with the setting off and no per-role write-offs behind
	it, ERPNext lists the BOM once and counts it once. That is the single-document
	flow every tenant who has not adopted the split still runs on, and refusing it
	would take manufacturing away from all of them to fix a bug they cannot have.

	Refused rather than repaired. The setting is wrong for every order on the
	site; dropping the duplicate rows from this one document would hide that and
	leave the rest to rot.
	"""
	if _material_consumption_enabled():
		return
	if not frappe.db.exists(
		"Stock Entry", {"work_order": work_order, "purpose": _SE_CONSUMPTION, "docstatus": 1}
	):
		return
	frappe.throw(
		# Worded to match the two sibling refusals about this same switch: name
		# the checkbox in English (that is the label in the desk, untranslated by
		# ERPNext) and the screen in the reader's language. A manager who is told
		# "consumption is off" still has to go looking; one who is told which box
		# does not.
		_(
			"This order's material has already been written off per operator, but "
			"'Allow Continuous Material Consumption' is switched off in Manufacturing "
			"Settings — finishing now would count that material a second time. Ask a "
			"manager to switch it back on."
		)
	)


class SweepNotAcknowledged(frappe.ValidationError):
	"""Raised by `_assert_sweep_is_acknowledged`, and given its own class so a
	caller can tell this refusal apart from every other reason a Finish fails.

	The kiosk needs that: this is the one refusal with an exit — tick the box,
	post anyway — and the only thing it can match on. The message cannot serve:
	it is translated into five languages, so matching its text works in English
	and silently strands the operator in the other four. `frappe.response`
	carries the class name back on V1 (`utils/response.py:52`), unconditionally,
	traceback suppression included.
	"""


def _sweep_risk_of(rows: list[dict], my_role: str | None) -> list[dict]:
	"""The sweep predicate itself, over rows somebody has already fetched.

	Split out from `_sweep_risk_rows` so the two places that ask the question
	share one answer: `wo_consumption_preview` warns the operator before they
	type a count, `_assert_sweep_is_acknowledged` refuses after. Written twice
	they drift — the kiosk lists the label rolls, the server refuses over the
	milk, and the operator ticks a box that does not unblock them. It is also
	the only way the preview can answer without a second `make_stock_entry`
	round trip for rows it is already holding.
	"""
	return [r for r in rows if r.get("operator_role") and r.get("operator_role") != my_role]


def _sweep_risk_rows(work_order: str, my_role: str | None) -> list[dict]:
	"""Unconsumed rows a Manufacture entry would sweep onto this caller's
	document without the role that owns them ever writing them off — every
	role-owned row that is not `my_role`.

	`my_role=None` is how a manager is represented here (they hold no role of
	their own), and it correctly names every role-owned row: none of them is
	"theirs" either, so the sweep is just as invisible to a manager posting on
	the floor's behalf as it is to the other operator. A row nobody has given a
	role to is not named here in either direction — that is `_unassigned_rows`'
	open question, not a cross-role sweep.
	"""
	return _sweep_risk_of(_unconsumed_material_rows(work_order) or [], my_role)


def _assert_sweep_is_acknowledged(work_order: str, my_role: str | None, acknowledge_sweep: bool) -> None:
	"""Refuse to finish an order while the other role's material is still
	sitting unconsumed, unless the caller has been shown the list and confirmed
	anyway.

	This is the failure `_assert_roles_are_both_or_neither` cannot see: a FULLY
	assigned order, both boxes filled, where the two operators are simply
	running at different speeds — the ordinary state of an order mid-shift, not
	a misconfiguration. ERPNext does not tell the difference either —
	`Work Order Item.consumed_qty` accumulates whatever entry names it — so
	posting here sweeps whatever the other role has not yet written off onto
	this caller's document. Measured live, genesis-test 2026-08-25: a fully
	assigned order, consumption on, the pourer finished after writing off only
	his own milk — MAT-STE-2026-00037 carries PROBE-LABEL, consumed_qty
	0.0 -> 10.0, on the pourer's document, and the packer's deviation panel
	scored a clean on-plan shift for an order he never touched.

	Server-side because the kiosk is not the only caller of this endpoint — a
	UI-only warning is a courtesy, not the fix.
	"""
	if acknowledge_sweep:
		return
	sweep = _sweep_risk_rows(work_order, my_role)
	if not sweep:
		return
	# item_name, not item_code: this reaches an operator on the kiosk mid-shift,
	# and the kiosk's own materials list (`ManufacturingOperatorBoard.vue`) shows
	# item_name as the primary label everywhere, item_code only as a small
	# reference underneath. `_assert_may_consume`'s refusals name item_code
	# instead — a real, pre-existing divergence, not one this change resolves.
	names = ", ".join(r.get("item_name") or r.get("item_code") for r in sweep)
	frappe.throw(
		_(
			"Finishing now will also write off material the other operator has not "
			"consumed yet: {0}. Confirm to include it on your document anyway."
		).format(names),
		exc=SweepNotAcknowledged,
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
	empty = {
		"items": [],
		"from_warehouse": None,
		"role": role,
		"unassigned_item_count": 0,
		"sweep_risk": [],
		"enabled": False,
	}
	rows = _unconsumed_material_rows(work_order)
	if rows is None:
		# Not an error: the site is not set up for the split, and the kiosk shows the
		# single-document flow instead of two write-off buttons.
		return empty
	# `rows == []` also covers ERPNext refusing the stub once the order is fully
	# produced (fg_completed_qty falls to 0) — routinely reached, not only on
	# breakage, and `enabled: True` here is what tells the kiosk this order really
	# has nothing left rather than that the site is unset up for the split.

	from_wh = next((r.get("s_warehouse") for r in rows if r.get("s_warehouse")), None)
	items = [r for r in rows if is_manager or (role and r.get("operator_role") == role)]
	return {
		"items": items,
		"from_warehouse": from_wh,
		"role": role,
		"unassigned_item_count": len([r for r in rows if not r.get("operator_role")]),
		# The complement of `items`, and the reason it rides this payload rather
		# than its own endpoint: it is the same `rows`, already paid for. The
		# kiosk shows it in the Finish dialog so the operator meets the sweep as
		# a warning they can act on — call the other operator, wait ten minutes —
		# instead of as `_assert_sweep_is_acknowledged`'s refusal after the
		# pallet is already counted.
		"sweep_risk": _sweep_risk_of(rows, role),
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
	is_manager = _is_mfg_manager()
	# Operators see only WOs assigned to themselves; managers see all. Assigned in
	# EITHER role — the packer has to reach the same order as the pourer.
	if not is_manager:
		conds.append("(" + " OR ".join(f"`{col}` = %(user)s" for col in assignee_cols) + ")")
		params["user"] = frappe.session.user
	where = " AND ".join(conds)
	assignee_select = "".join(f"{col}, " for col in assignee_cols)
	# The kiosk reads its whole board from here, so the draft banner has to arrive
	# with the rows. Optional for the same reason the assignee columns are: v99 may
	# not have run yet.
	draft_cols = _wo_draft_columns()
	draft_select = "".join(f"{col}, " for col in draft_cols)
	rows = frappe.db.sql(
		f"""
		SELECT name, production_item, item_name, bom_no, qty, produced_qty,
		       material_transferred_for_manufacturing AS transferred_qty,
		       status, planned_start_date, planned_end_date, fg_warehouse,
		       wip_warehouse, {assignee_select}{draft_select}docstatus, modified
		FROM `tabWork Order`
		WHERE {where}
		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	# The card on the kiosk board shows a Required Materials block, role-scoped the
	# same way `work_order_detail` scopes it — an operator sees only their own
	# role's lines, a manager sees the lot. One bulk query for every row on the
	# page rather than a Work Order document load per row, which is what a naive
	# per-row `frappe.get_doc(...).required_items` would cost: 100 rows would mean
	# 100 extra document loads on every board poll.
	names = [row["name"] for row in rows]
	item_rows = (
		frappe.get_all(
			"Work Order Item",
			filters={"parent": ["in", names]},
			fields=[
				"parent",
				"item_code",
				"item_name",
				"required_qty",
				"transferred_qty",
				"consumed_qty",
				"source_warehouse",
				*(["rate", "amount"] if is_manager else []),
			],
			order_by="parent, idx",
			ignore_permissions=True,  # rows already scoped to WOs this user may see, above
		)
		if names
		else []
	)
	item_roles = _item_roles([r["item_code"] for r in item_rows])
	items_by_wo: dict[str, list] = {}
	for r in item_rows:
		items_by_wo.setdefault(r["parent"], []).append(
			{
				"item_code": r["item_code"],
				"item_name": r["item_name"],
				"required_qty": flt(r["required_qty"]),
				"transferred_qty": flt(r["transferred_qty"]),
				"consumed_qty": flt(r["consumed_qty"]),
				"source_warehouse": r["source_warehouse"],
				"operator_role": item_roles.get(r["item_code"]) or None,
				# Rates reveal BOM cost data — only managers see them.
				**({"rate": flt(r["rate"]), "amount": flt(r["amount"])} if is_manager else {}),
			}
		)
	for row in rows:
		row["finish_draft"] = _decode_finish_draft(row)
		for col in draft_cols:
			row.pop(col, None)
		wo_items = items_by_wo.get(row["name"], [])
		row["required_items"] = (
			wo_items if is_manager else _rows_for_role(wo_items, item_roles, _wo_role_of(row))
		)
	return rows


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
	# Managers see it as well as operators: "what is sitting unconfirmed right now"
	# is a shift lead's question, and it is the reason the draft lives on the order
	# rather than in one tablet's storage.
	payload["finish_draft"] = _decode_finish_draft(doc)
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
		# The operator names are not filtered along with the lines, so without
		# this the detail page reads the other role as somebody assigned to a
		# stage with no work on it — the mis-set-BOM warning, fired falsely on
		# every order this user opens.
		payload["items_scoped_to_role"] = my_role
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
	acknowledge_sweep: bool = False,
):
	"""Generate and submit a Stock Entry for material transfer or manufacture.

	`scrap_qty` is accepted for the Manufacture purpose and recorded as
	process loss (operator-reported rejects). On Manufacture, an optional
	`batch_no` (+ mfg/expiry) is stamped on the Work Order for lot traceability
	(Faz 4a) — informational only, does not touch the stock batch engine.

	`acknowledge_sweep` confirms the caller has been shown, and accepts, that
	finishing now will also write off the other role's unconsumed material
	(`_assert_sweep_is_acknowledged`). Default False on purpose: the guard is a
	safety net against a stale or failed client-side preview, not just a prompt,
	so the server must still refuse when the flag is simply absent."""
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
		_assert_roles_are_both_or_neither(work_order, purpose)
	elif purpose == "Manufacture":
		# First, because it outranks the other two: they are questions about this
		# order, and this is a question about the site. An order can be perfectly
		# assigned and perfectly written off and still be double-counted here, and
		# so can every other order on the site — which is why the message sends
		# somebody to the setting rather than to this order.
		_assert_consumption_setting_still_holds(work_order)
		# D1 (P0): this guard used to run only on the transfer branch, so a
		# half-assigned order (the never-named role could not even open the order
		# to write anything off) reached ERPNext's Manufacture entry unchecked.
		# ERPNext sweeps every unconsumed line onto whoever posts this document —
		# the packer's kilograms land on the pourer's Stock Entry, with no
		# attribution the deviation panel can later untangle.
		#
		# Caller-blind on purpose, including managers: unlike `_assert_may_consume`
		# (which asks "whose lines may you touch?" and rightly exempts a manager,
		# who is not claiming a role), this guard asks "is this order in a fit
		# state to post at all?" — a property of the order, not of who is pressing
		# the button. A half-assigned order yields the same unattributable document
		# whichever of them posts it, so there is nothing to exempt. The escape
		# hatch for a manager is to assign both roles first, which is one action
		# and makes the record true — not to post around the gap.
		_assert_roles_are_both_or_neither(work_order, purpose)
		# Part 3 (the actual P0): a FULLY assigned order reaches this point on
		# every ordinary shift — the two operators simply running at different
		# speeds — and the guard above cannot see that, because both boxes are
		# filled. ERPNext cannot see it either: consumed_qty just accumulates
		# whatever entry names it, so posting here sweeps whatever the other role
		# has not yet written off onto this caller's document. Measured live,
		# genesis-test 2026-08-25: MAT-STE-2026-00037 carries PROBE-LABEL that the
		# packer never touched.
		my_role = (
			None
			if is_manager
			else _wo_role_of(
				frappe.db.get_value("Work Order", work_order, list(_wo_operator_columns()), as_dict=True)
			)
		)
		_assert_sweep_is_acknowledged(work_order, my_role, acknowledge_sweep)

	# D4 (P0): a Manufacture entry with process loss has to be ASKED FOR as
	# good+scrap. ERPNext validates `fg_completed_qty == fg row qty +
	# process_loss_qty` and throws otherwise (stock_entry.py:747) — so setting
	# process_loss_qty while leaving the finished-goods row whole did not
	# miscount, it made Finish fail outright, in ERPNext's words, in front of an
	# operator who typed a reject count on a tablet. The only way through was to
	# lie about the rejects. Measured genesis-test 2026-08-26 on
	# MFG-WO-2026-00009: loss=0 submits, loss=0.2 throws.
	#
	# `qty` is GOOD units here — the kiosk labels it so and defaults it to the
	# target remaining — while `fg_completed_qty` is what was attempted. Raising
	# the attempt is not a trick to satisfy the check: the raw material for the
	# rejected units really was used, and ERPNext scales consumption off
	# fg_completed_qty. Measured with this shape: fg_completed_qty 10, fg row 8,
	# process_loss_qty 2, Work Order.produced_qty 0 -> 8. Only good units count
	# toward the plan, which is why the two figures are separate at all.
	loss = flt(scrap_qty) if (purpose == "Manufacture" and scrap_qty and qty) else 0.0
	attempted = (flt(qty) + loss) if qty else None
	doc = make_stock_entry(work_order, purpose, qty=attempted)
	stub = doc if isinstance(doc, dict) else doc.as_dict()
	se = frappe.get_doc(stub)

	if loss > 0:
		se.process_loss_qty = loss
		for row in se.items:
			# The finished-goods row only. A raw line reduced here would unpick the
			# consumption the operators already recorded.
			if cint(getattr(row, "is_finished_item", 0)):
				row.qty = flt(qty)

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
		# The count is on a submitted stock document now, so it is not unconfirmed
		# any more. Left behind, the banner outlives the order it describes and the
		# next operator re-enters numbers that are already posted.
		_clear_finish_draft(work_order)
		if (batch_no or "").strip():
			_stamp_wo_batch(work_order, batch_no, mfg_date, expiry_date)
		batch_note = f", Batch: {batch_no}" if (batch_no or "").strip() else ""
		_log_wo_event(
			work_order, f"Work Order finished. Produced: {flt(qty)}, Rejects: {flt(scrap_qty)}{batch_note}"
		)

	return {"name": se.name, "purpose": purpose, "docstatus": se.docstatus}


@frappe.whitelist()
def save_finish_draft(
	work_order: str,
	produced_qty: float = 0,
	scrap_qty: float = 0,
	batch_no: str | None = None,
	mfg_date: str | None = None,
	expiry_date: str | None = None,
):
	"""Park an unconfirmed finish on the Work Order.

	Same permission shape as `update_work_order_materials`: an assigned operator on
	their own order, or a manager on any. Deliberately not narrowed to one role —
	one order has two operators and either of them may be the person who walks the
	pallet at the end of the shift.

	Zero produced is a legitimate draft. A shift that made nothing and rejected
	forty is a real thing to report, and refusing to store it is how it gets
	counted twice.
	"""
	from frappe.utils import now

	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	_require_wo_draft_columns()

	frappe.db.set_value(
		"Work Order",
		work_order,
		{
			"custom_finish_draft": _encode_finish_draft(
				produced_qty=produced_qty,
				scrap_qty=scrap_qty,
				batch_no=batch_no,
				mfg_date=mfg_date,
				expiry_date=expiry_date,
			),
			"custom_finish_draft_at": now(),
			"custom_finish_draft_by": frappe.session.user,
		},
		# A parked count is not a change to the order, and the kiosk list is ordered
		# by `modified` — bumping it would shuffle the board under the operator's
		# hand every time they saved.
		update_modified=False,
	)
	return {"name": work_order, "saved_by": frappe.session.user}


@frappe.whitelist()
def discard_finish_draft(work_order: str):
	"""Throw the parked count away. Without this the only way out of a wrong draft
	is posting it, which is the one thing a wrong count must not do."""
	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	_clear_finish_draft(work_order)
	return {"name": work_order}


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


@frappe.whitelist()
def assign_work_order_operators_bulk(company: str, names, operator: str = "", packaging_operator: str = ""):
	"""Put the same operator pair on many Work Orders in one gesture. Manager-only.

	A shift lead sets one pouring/packing pair per line per shift. The gesture that
	matches that is "these fifteen orders, these two people", not fifteen trips
	through a detail panel — which is the version that gets abandoned halfway and
	leaves half a shift unassigned.

	Two rules make the sweep safe to hand somebody:

	* **A role left empty is left alone**, unlike the single-order endpoint where an
	  empty box clears it. Silence about packing is not an instruction to remove
	  every packer.
	* **Nothing is skipped silently.** Finished orders, ids from another company,
	  ids that no longer exist and orders where the new name would land the same
	  person in both roles all come back in `skipped` with a reason, and the caller
	  shows them. A bulk action that reports only its successes cannot be told apart
	  from one that worked.

	Partial success is the intended outcome, not a failure mode: fourteen assigned
	and one refused is a better answer than a throw that rolls back all fifteen
	because one order was closed yesterday.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()

	requested = names if isinstance(names, list) else json.loads(names or "[]")
	requested = [str(name) for name in requested if name]
	if not requested:
		frappe.throw(_("Select at least one Work Order."))

	assignment = {"operator": operator or None, "packaging_operator": packaging_operator or None}
	if not any(assignment.values()):
		# Clearing both roles across a selection would strand a shift's worth of
		# orders in one click, and no floor workflow asks for it. Removing an
		# operator stays a per-order decision.
		frappe.throw(_("Choose at least one operator to assign."))
	for who in assignment.values():
		if who:
			if not frappe.db.exists("User", who):
				frappe.throw(_("Unknown user: {0}").format(who))
	_assert_distinct_operators(assignment["operator"], assignment["packaging_operator"])
	for field, who in assignment.items():
		if who:
			_require_wo_operator_column(field)

	columns = _wo_operator_columns()
	rows = frappe.get_all(
		"Work Order",
		filters={"name": ["in", requested]},
		fields=["name", "company", "status", "docstatus", *columns],
	)
	assign, skipped = _partition_bulk_assign(requested, rows, company)

	by_name = {row["name"]: row for row in rows}
	writable = {field: who for field, who in assignment.items() if who and field in columns}
	assigned: list[str] = []
	for name in assign:
		after = _bulk_pair_after(by_name[name], assignment)
		if after["operator"] and after["operator"] == after["packaging_operator"]:
			# Only reachable when one box was filled and the counterpart already
			# held that person — a clash the manager could not see from the list.
			skipped.append(
				{
					"name": name,
					"reason": _("{0} would hold both roles here").format(after["operator"]),
				}
			)
			continue
		_assert_can_write("Work Order", name, "write")
		for field, who in writable.items():
			frappe.db.set_value("Work Order", name, field, who)
		assigned.append(name)
	return {"assigned": assigned, "skipped": skipped}


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
	# D8 (P0): this was "Transfer", which is not one of the six values the doctype
	# offers, so `insert` raised and the Work Order could not be SUBMITTED at all —
	# the manager lost the whole form, not a click. Measured genesis-test
	# 2026-08-26: Purpose cannot be "Transfer". It should be one of "Purchase",
	# "Material Transfer", "Material Issue", "Manufacture", "Subcontracting",
	# "Customer Provided".
	mr.material_request_type = "Material Transfer"
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
	is_manager = _is_mfg_manager()
	if not is_manager:
		_require_own_work_order(work_order)

	# D7 (P0): `required_qty` is the denominator the deviation panel scores people
	# against, and the SQL below goes around the docstatus lock on purpose — so on
	# a closed order nothing else refuses this. Rewriting the plan for a shift that
	# has already been scored rewrites the score, silently and after the fact.
	if cint(doc.docstatus) == 2 or doc.status in ("Completed", "Closed"):
		frappe.throw(_("This order is {0} — its plan can no longer be changed.").format(_(doc.status)))

	try:
		mat_list = json.loads(materials)
	except Exception:
		frappe.throw("Invalid materials format.")

	# D7 (P0), the other half: unscoped, one operator can move the OTHER one's bar
	# — raise the packer's plan and the packer looks efficient, lower it and the
	# packer looks wasteful, and the packer is never told. The kiosk has only sent
	# the caller's own lines since 238592a role-scoped `list_work_orders`, which is
	# exactly why this has to live here: the screen was never the guard.
	if not is_manager:
		codes = list(dict.fromkeys(m.get("item_code") for m in mat_list))
		undecided, foreign = _lines_not_yours(work_order, codes)
		if undecided:
			frappe.throw(
				_("Nobody has decided which operator these materials belong to yet: {0}").format(
					", ".join(undecided)
				)
			)
		if foreign:
			frappe.throw(
				_("These materials are the other operator's to plan, not yours: {0}").format(
					", ".join(foreign)
				)
			)

	# Update the quantities in the child table directly
	changes = []
	for m in mat_list:
		item_code = m.get("item_code")
		new_qty = flt(m.get("required_qty"))
		# Read before the write: the number being replaced is the whole point of
		# the audit line, and after the UPDATE it is gone from the row and from
		# every version table (raw SQL leaves no Version document behind either).
		old_qty = flt(
			frappe.db.get_value(
				"Work Order Item", {"parent": work_order, "item_code": item_code}, "required_qty"
			)
		)

		# Update required_qty directly in db to bypass docstatus read-only restriction
		frappe.db.sql(
			"""
			UPDATE `tabWork Order Item`
			SET required_qty = %s
			WHERE parent = %s AND item_code = %s
			""",
			(new_qty, work_order, item_code),
		)
		if old_qty != new_qty:
			changes.append(f"{item_code}: {old_qty} -> {new_qty}")

	# Log the event. Named, with the number it replaced: "Raw materials manually
	# adjusted by X" — the whole audit trail before this — says a number moved
	# without saying which, from what, or to what, so a plan quietly raised 20%
	# reads exactly like a typo corrected back. English like every other event on
	# this document: it is a record, not a screen.
	if changes:
		_log_wo_event(
			work_order,
			f"Raw materials manually adjusted by {frappe.session.user}: " + ", ".join(changes),
		)

	# Reload document to reflect database changes
	doc.reload()

	# If it's a tomorrow or future WO, create/update Material Request for any new shortages
	from frappe.utils import add_days, getdate, today

	tomorrow = getdate(add_days(today(), 1))
	forward_dated = doc.wip_warehouse and getdate(doc.planned_start_date) >= tomorrow

	# D9 (P0): this block cancels SUBMITTED Material Requests as a side effect of
	# someone correcting a quantity. That is a manager's decision — an approved
	# order to a warehouse is not an operator's to withdraw, and until D8 was
	# fixed the invalid purpose literal below was the only thing stopping the loop
	# from ever completing. An operator's plan change now lands and the request is
	# left standing; said out loud on the document, because a stale request nobody
	# is told about is its own quiet failure.
	if forward_dated and not is_manager:
		if frappe.db.exists("Material Request", {"work_order": doc.name, "docstatus": ["!=", 2]}):
			_log_wo_event(
				work_order,
				f"Plan changed by {frappe.session.user}; the existing material request was left as it "
				"stands. A manager must refresh it.",
			)
		return {"ok": True}

	if forward_dated:
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
			except Exception as e:
				# D9 (P0): this was `pass`. The loop exists to clear the way for a
				# fresh request, so continuing past a failed cancel leaves the old
				# one live and puts a second one beside it — the same material
				# ordered twice, from one edit, with nothing said. The throw rolls
				# back whatever the loop already cancelled, which is the only
				# consistent outcome available here.
				frappe.log_error(
					title="Kassa/mfg: could not clear a Material Request",
					message=f"wo={doc.name} mr={mr_name} err={e}",
				)
				frappe.throw(
					_(
						"The existing material request {0} could not be withdrawn, so the plan "
						"was not saved. Sort that request out first."
					).format(mr_name)
				)

		# Create fresh MR
		mr = frappe.new_doc("Material Request")
		mr.material_request_type = "Material Transfer"
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
