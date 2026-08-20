import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from stabler.api._common import _assert_can_read, _assert_can_write
from stabler.api.imports import _assert_cost_visible, _latest_exchange_rate
from stabler.stabler.imports_module import lcv_math

#: Custom Field holding the chosen Landed Cost Voucher distribution basis on the
#: source document. Created on both source doctypes by patch
#: ``v88_lcv_distribution_method``.
DISTRIBUTION_FIELD = "custom_landed_cost_distribution"

#: The two source doctypes an LCV review runs on; both carry
#: ``DISTRIBUTION_FIELD``.
DISTRIBUTION_DOCTYPES = ("GRN Checklist", "Purchase Receipt")


def _company_of(doctype: str, name: str) -> str:
	return frappe.get_cached_value(doctype, name, "company")


def _persisted_distribution_method(document_type: str, document_name: str):
	"""Distribution basis stored on the source document, or ``None``.

	Read behind a column check because the Custom Field arrives with a patch: on
	a site whose migration has not run yet this must answer "nothing chosen", not
	take the whole landed-cost review screen down with an unknown-column error.
	"""
	if not frappe.db.has_column(document_type, DISTRIBUTION_FIELD):
		return None
	return frappe.db.get_value(document_type, document_name, DISTRIBUTION_FIELD)


def _receipt_names_for(document_type: str, document_name: str, review=None) -> tuple:
	"""``(doctype, names)`` the freeze rule looks at for this document.

	A Purchase Receipt is its own receipt. A GRN Checklist's receipts are whatever
	the review already reports, so the checklist → receipts mapping stays in the
	one place that owns it; a second mapping invented here is how the lock would
	quietly stop engaging the day that one changes.

	The doctype rides along because a GRN's stock document is a Purchase Receipt
	on the truck route and an ``update_stock`` Purchase Invoice on the CI route.
	A bare name cannot say which, and the join below filters on it — so assuming
	"Purchase Receipt" finds no submitted voucher on the invoice route and reports
	an unlocked basis for stock a voucher has already capitalized.
	"""
	if document_type == "Purchase Receipt":
		return "Purchase Receipt", [document_name]
	if review is None:
		from stabler.api.imports import get_landed_cost_review as imports_review

		review = imports_review(document_name)
	rows = [pr for pr in (review.get("purchase_receipts") or []) if pr.get("name")]
	kind = (rows[0].get("receipt_document_type") if rows else None) or "Purchase Receipt"
	return kind, [pr["name"] for pr in rows]


def _vouchers_on_receipts(receipt_names, docstatus, receipt_document_type="Purchase Receipt") -> list:
	"""``[{lcv, method}]`` of the vouchers in this docstatus against these receipts.

	Through ``tabLanded Cost Purchase Receipt``: that child table is the only link
	from a receipt back to its vouchers, and it is the same read the
	``existing_lcvs`` lookup below performs. One query serves both callers so the
	freeze and the re-stamp can never disagree about which vouchers stand against
	a document — two copies of this join is how one of them quietly stops
	engaging the day the other changes.
	"""
	names = [n for n in (receipt_names or []) if n]
	if not names:
		return []

	placeholders = ", ".join(["%s"] * len(names))
	return frappe.db.sql(
		"""
		SELECT DISTINCT lcpr.parent AS lcv, voucher.distribute_charges_based_on AS method
		FROM `tabLanded Cost Purchase Receipt` lcpr
		INNER JOIN `tabLanded Cost Voucher` voucher ON voucher.name = lcpr.parent
		WHERE lcpr.receipt_document IN ({placeholders})
			AND lcpr.receipt_document_type = %s
			AND voucher.docstatus = %s
		ORDER BY voucher.creation ASC, voucher.name ASC
	""".format(placeholders=placeholders),
		(*names, receipt_document_type, docstatus),
		as_dict=True,
	)


def _locking_voucher(receipt_names, receipt_document_type="Purchase Receipt") -> tuple:
	"""``(voucher, basis)`` of the submitted LCV that froze the distribution basis.

	Only ``docstatus == 1`` freezes anything: a draft has capitalized nothing yet,
	and a cancelled voucher has already given back what it capitalized, so neither
	constrains the next one. The earliest submitted voucher wins — it is the one
	whose basis every later netting in ``apply_gtd_customs_precedence`` is
	measured against.
	"""
	rows = _vouchers_on_receipts(receipt_names, lcv_math.LOCKING_DOCSTATUS, receipt_document_type)
	if not rows:
		return None, None
	return rows[0].get("lcv"), rows[0].get("method")


def _restamp_drafts(receipt_names, method: str, receipt_document_type="Purchase Receipt") -> list:
	"""Put the chosen basis on every DRAFT voucher standing against these receipts.

	The choice is persisted on the source document, but a draft carries the basis
	it was BUILT with, and ``submit_landed_cost_voucher`` posts a draft as it
	stands. On the imports route the draft is built by a background job at GRN
	submit — before any human can open this screen — so by the time the operator
	picks a basis the draft already exists with the default one. Without this the
	screen reports one basis and the ledger uses another: freight the operator
	spread by weight gets capitalized by value, per-item valuations are wrong for
	every item whose value-per-kg differs from the average, and nothing anywhere
	says so.

	Saving is what redistributes. ``LandedCostVoucher.validate`` calls
	``set_applicable_charges_on_item``, which reads this field — so the amounts
	are recomputed, not just the label.

	Only drafts. A submitted voucher is what ``_locking_voucher`` refuses to let
	the basis change under, and this function is unreachable in that case anyway:
	``set_distribution_method`` throws on a locked state before calling it.
	"""
	restamped = []
	for row in _vouchers_on_receipts(receipt_names, 0, receipt_document_type):
		if lcv_math.normalize_distribution_method(row.get("method")) == method:
			continue
		voucher = frappe.get_doc("Landed Cost Voucher", row["lcv"])
		voucher.distribute_charges_based_on = method
		voucher.save()
		restamped.append(voucher.name)
	return restamped


def distribution_state(
	document_type: str,
	document_name: str,
	receipt_names=None,
	review=None,
	receipt_document_type=None,
) -> dict:
	"""Effective distribution basis for a document, and whether it is frozen.

	``locked`` is a server-side fact, not a UI hint: ``set_distribution_method``
	refuses on it, so a client that never renders the lock still cannot change the
	basis out from under a submitted voucher.
	"""
	if receipt_names is None:
		resolved_type, receipt_names = _receipt_names_for(document_type, document_name, review)
		receipt_document_type = receipt_document_type or resolved_type
	locked_by, locked_method = _locking_voucher(receipt_names, receipt_document_type or "Purchase Receipt")
	persisted = _persisted_distribution_method(document_type, document_name)
	return {
		"method": lcv_math.resolve_distribution_method(persisted, locked_method),
		"locked": bool(locked_by),
		"locked_by": locked_by,
		"options": list(lcv_math.DISTRIBUTION_METHODS),
	}


def effective_distribution_method(
	document_type: str, document_name: str, receipt_names=None, receipt_document_type=None
) -> str:
	"""Basis a voucher for this document must be built on.

	The single entry point for every build path — this one and
	``imports_module/hooks.py`` — so the persisted choice and the freeze rule
	cannot be honored on one route and skipped on the other. Pass
	``receipt_names`` when they are already known (a build path always knows
	them): it saves the lookup and keeps this callable mid-submit, before the
	review of a GRN Checklist can be assembled.
	"""
	return distribution_state(
		document_type,
		document_name,
		receipt_names=receipt_names,
		receipt_document_type=receipt_document_type,
	)["method"]


@frappe.whitelist()
def get_landed_cost_review(document_type: str, document_name: str, rate=None):
	"""Unified whitelisted endpoint for LCV review.

	Supports both:
	- document_type="GRN Checklist" (Imports Flow)
	- document_type="Purchase Receipt" (Tender/General Purchasing Flow)
	"""
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		from stabler.api.imports import get_landed_cost_review as imports_review

		review = imports_review(document_name, rate)
		# The imports flow owns every other key in that payload; the distribution
		# basis is decided here so both flows answer in one shape and one client
		# renders both.
		review["distribution"] = distribution_state("GRN Checklist", document_name, review=review)
		return review

	elif document_type == "Purchase Receipt":
		if not frappe.db.exists("Purchase Receipt", document_name):
			frappe.throw(_("Unknown Purchase Receipt: {0}").format(document_name))

		_assert_can_read("Purchase Receipt", document_name)
		_assert_cost_visible()

		pr = frappe.get_doc("Purchase Receipt", document_name)
		company_currency = frappe.get_cached_value("Company", pr.company, "default_currency") or "UZS"

		# Get distinct linked Purchase Orders
		po_names = list(
			set(
				[
					d.purchase_order
					for d in pr.items
					if d.purchase_order and frappe.db.exists("Purchase Order", d.purchase_order)
				]
			)
		)

		# Read customized setting includes from the PR
		custom_settings = {}
		if pr.get("custom_landed_cost_settings"):
			try:
				custom_settings = json.loads(pr.custom_landed_cost_settings)
			except Exception:
				pass
		includes = custom_settings.get("includes", {})

		# Find existing LCVs referencing this Purchase Receipt to mark consumed/vouchered components
		lcvs = frappe.db.sql(
			"""
			SELECT parent
			FROM `tabLanded Cost Purchase Receipt`
			WHERE receipt_document = %s
		""",
			(document_name,),
			as_dict=True,
		)

		consumed_descriptions = set()
		existing_lcvs = []
		for item in lcvs:
			lcv_name = item.parent
			lcv_doc = frappe.get_doc("Landed Cost Voucher", lcv_name)

			existing_lcvs.append(
				{
					"lcv": lcv_name,
					"note": lcv_doc.get("note") or "",
					"posted_on": str(lcv_doc.creation) if lcv_doc.creation else None,
					"docstatus": cint(lcv_doc.docstatus),
					"total": flt(lcv_doc.total_taxes_and_charges),
					"posting_date": str(lcv_doc.posting_date) if lcv_doc.posting_date else None,
				}
			)

			if lcv_doc.docstatus == 1:
				for tax in lcv_doc.taxes or []:
					consumed_descriptions.add(tax.description)

		from stabler.api.tender import _parse_landed

		raw_lines = []
		idx = 1
		for po_name in po_names:
			po_charges_raw = frappe.db.get_value("Purchase Order", po_name, "custom_landed_charges")
			po_charges = _parse_landed(po_charges_raw)
			for charge in po_charges:
				label = charge.get("label") or charge.get("type") or "Other"
				amount = charge.get("amount") or 0.0

				consumed = label in consumed_descriptions

				# Check custom setting first, default to True
				include_in_landed_cost = 1
				if label in includes:
					include_in_landed_cost = 1 if includes[label] else 0

				raw_lines.append(
					{
						"row_name": label,  # Use label as the identifier
						"cost_component": label,
						"description": f"PO: {po_name} - {label}",
						"currency": company_currency,
						"amount": amount,
						"amount_uzs": amount,
						"include_in_landed_cost": include_in_landed_cost,
						"lcv_ref": "vouchered" if consumed else "",
						"consumed": consumed,
					}
				)
				idx += 1

		# Rate preview conversions
		rates = {}
		usd_rate = 1.0
		rate_as_of = None
		rate_overridden = False
		if rate not in (None, ""):
			try:
				usd_rate = flt(rate)
				if usd_rate > 0:
					rates["USD"] = usd_rate
					rate_overridden = True
			except Exception:
				pass

		# ``rates`` stays empty in practice: every PO charge line above is built in
		# ``company_currency``, so nothing here needs converting and the override is
		# inert. It is wired anyway so a foreign-currency PO charge cannot silently
		# land at a 1:1 rate the day one appears.
		components, agg_warnings = lcv_math.aggregate_components(
			raw_lines, rates, company_currency, translate=_
		)
		preview_components = [{"component": k, "amount": round(v, 2)} for k, v in sorted(components.items())]
		preview_total = round(sum(components.values()), 2)

		warnings = []
		warnings.extend(agg_warnings)
		if pr.docstatus != 1:
			warnings.append(_("Purchase Receipt must be Submitted to create a Landed Cost Voucher."))
		if not preview_components:
			warnings.append(_("No unconsumed landed-cost lines to voucher."))

		containers = []
		if raw_lines:
			containers.append(
				{
					"container": "po_charges",
					"container_number": _("Purchase Order Landed Charges"),
					"cost_lines": raw_lines,
				}
			)

		return {
			"grn": {
				"name": pr.name,
				"company": pr.company,
				"company_currency": company_currency,
				"commercial_invoice": pr.get("custom_commercial_invoice") or "",
				"supplier": pr.supplier,
				"warehouse": pr.items[0].warehouse if pr.items else "",
				"docstatus": cint(pr.docstatus),
				"receipt_status": "Completed" if pr.docstatus == 1 else "Draft",
				"completion_date": str(pr.posting_date) if pr.posting_date else None,
				"received_total_kg": sum(flt(d.qty) for d in pr.items),
				"received_total_boxes": 0,
			},
			"purchase_receipts": [
				{
					"name": pr.name,
					"supplier": pr.supplier,
					"posting_date": str(pr.posting_date) if pr.posting_date else None,
					"grand_total": flt(pr.grand_total),
					# Company-currency twin of grand_total. The per-kg card sums the
					# receipt leg against voucher totals, which are already base
					# amounts; without this it would add USD to UZS.
					"base_grand_total": flt(pr.base_grand_total),
					"currency": pr.currency,
					"docstatus": cint(pr.docstatus),
				}
			]
			if pr.docstatus == 1
			else [],
			"existing_lcvs": existing_lcvs,
			"containers": containers,
			"distribution": distribution_state(
				"Purchase Receipt", document_name, receipt_names=[document_name]
			),
			"gtd": None,
			"preview": {
				"exchange_rate": usd_rate,
				"rate_as_of": str(rate_as_of) if rate_as_of else None,
				"rate_overridden": rate_overridden,
				"components": preview_components,
				"total": preview_total,
				"warnings": warnings,
				"can_create": bool(preview_components and pr.docstatus == 1),
			},
		}


@frappe.whitelist()
def toggle_cost_line_include(
	document_type: str, document_name: str, container: str, row_name: str, include: int = 1
):
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		from stabler.api.imports import toggle_cost_line_include as imports_toggle

		return imports_toggle(container, row_name, include)

	elif document_type == "Purchase Receipt":
		_assert_can_write("Purchase Receipt", document_name)
		_assert_cost_visible()

		pr = frappe.get_doc("Purchase Receipt", document_name)
		custom_settings = {}
		if pr.get("custom_landed_cost_settings"):
			try:
				custom_settings = json.loads(pr.custom_landed_cost_settings)
			except Exception:
				pass
		includes = custom_settings.get("includes", {})

		# Here row_name is the charge label/component name
		includes[row_name] = bool(int(include))
		custom_settings["includes"] = includes

		pr.db_set("custom_landed_cost_settings", json.dumps(custom_settings))
		return {"status": "ok"}


@frappe.whitelist()
def set_distribution_method(document_type: str, document_name: str, method: str):
	"""Persist the basis the next Landed Cost Voucher distributes charges on.

	Refuses once a submitted voucher stands against these receipts. That refusal
	lives here rather than in the client because the reason is an accounting one:
	``apply_gtd_customs_precedence`` nets a late customs declaration against what
	earlier vouchers already capitalized, and those amounts were spread on the
	first voucher's basis. Cancelling that voucher reverses its valuation and
	unfreezes the choice — which is the operator's decision, not a silent one.

	Returns the same ``distribution`` dict ``get_landed_cost_review`` reports.
	"""
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))
	if document_type not in DISTRIBUTION_DOCTYPES:
		frappe.throw(_("Unsupported document type: {0}").format(document_type))
	if not frappe.db.exists(document_type, document_name):
		frappe.throw(_("Unknown {0}: {1}").format(document_type, document_name))

	_assert_can_write(document_type, document_name)
	_assert_cost_visible()

	try:
		method = lcv_math.validate_distribution_method(method)
	except ValueError:
		frappe.throw(
			_("Landed cost distribution must be one of: {0}.").format(
				", ".join(lcv_math.DISTRIBUTION_METHODS)
			)
		)

	receipt_type, receipt_names = _receipt_names_for(document_type, document_name)
	state = distribution_state(
		document_type, document_name, receipt_names=receipt_names, receipt_document_type=receipt_type
	)
	if state["locked"]:
		frappe.throw(
			_(
				"The landed cost distribution is frozen at {0} by submitted Landed Cost Voucher {1}. "
				"Cancel that voucher to change the basis — a later voucher on a different basis would "
				"net customs charges against amounts capitalized on the first one."
			).format(state["method"], state["locked_by"])
		)

	if not frappe.db.has_column(document_type, DISTRIBUTION_FIELD):
		frappe.throw(
			_("The landed cost distribution field is not installed on {0} yet.").format(document_type)
		)

	frappe.db.set_value(document_type, document_name, DISTRIBUTION_FIELD, method)
	# Persisting the choice is not enough: a draft built before it was made still
	# carries the basis it was built with, and Submit posts a draft as it stands.
	restamped = _restamp_drafts(receipt_names, method, receipt_type)

	state = distribution_state(
		document_type, document_name, receipt_names=receipt_names, receipt_document_type=receipt_type
	)
	state["restamped"] = restamped
	return state


@frappe.whitelist()
def create_additional_lcv(document_type: str, document_name: str):
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		# The imports flow builds its voucher in ``imports_module/hooks.py``
		# (``_build_and_save_lcv``); that path resolves the basis through
		# ``effective_distribution_method`` as well, so the persisted choice and
		# the freeze rule hold on both routes into a Landed Cost Voucher.
		from stabler.api.imports import create_additional_lcv as imports_create

		return imports_create(document_name)

	elif document_type == "Purchase Receipt":
		_assert_can_write("Purchase Receipt", document_name)
		_assert_cost_visible()

		review = get_landed_cost_review(document_type, document_name)
		preview = review.get("preview") or {}
		components_list = preview.get("components") or []

		if not components_list:
			frappe.throw(_("No unconsumed landed-cost lines to voucher."))

		# Promoted Stabler Settings field
		expense_account = frappe.db.get_single_value(
			"Stabler Settings", "landed_cost_expense_account"
		) or frappe.db.get_single_value("Stabler Settings", "imports_lcv_expense_account")
		if not expense_account:
			pr_company = frappe.db.get_value("Purchase Receipt", document_name, "company")
			expense_account = frappe.db.get_value(
				"Account",
				{"company": pr_company, "account_type": "Expenses Included In Valuation", "is_group": 0},
				"name",
			) or frappe.db.get_value(
				"Account",
				{"company": pr_company, "root_type": "Expense", "is_group": 0},
				"name",
			)
		if not expense_account:
			frappe.throw(_("Please configure the Landed Cost Expense Account in Stabler Settings."))

		components = {c["component"]: c["amount"] for c in components_list}

		lcv_dict = lcv_math.build_lcv_payload(
			company=review["grn"]["company"],
			purchase_receipts=[document_name],
			components=components,
			expense_account=expense_account,
			# Resolved server-side, never taken from the caller: the basis a
			# follow-up voucher uses is frozen by whatever was submitted before it.
			distribute_based_on=effective_distribution_method(
				"Purchase Receipt", document_name, receipt_names=[document_name]
			),
		)

		if not lcv_dict:
			frappe.throw(_("Failed to build Landed Cost Voucher payload."))

		lcv = frappe.get_doc(lcv_dict)
		if hasattr(lcv, "get_items_from_purchase_receipts"):
			lcv.get_items_from_purchase_receipts()
		lcv.insert()

		frappe.db.set_value("Purchase Receipt", document_name, "custom_landed_cost_vouchered", 1)

		return {"status": "ok", "lcv": lcv.name}


@frappe.whitelist()
def submit_landed_cost_voucher(name: str):
	"""Submit a draft Landed Cost Voucher directly from Stabler SPA.

	Refuses a draft whose basis disagrees with one already frozen by a submitted
	voucher on the same receipts. ``_restamp_drafts`` keeps the operator's choice
	and the draft in step while the basis is still changeable; this is the case it
	cannot cover, because ``set_distribution_method`` throws once a voucher is
	submitted and so never gets to touch a draft that predates the freeze. The
	basis is verified here rather than corrected: rewriting a voucher at submit
	time would post numbers the accountant never saw, which is the same defect
	pointing the other way.
	"""
	_assert_can_write("Landed Cost Voucher", name, "submit")
	_assert_cost_visible()

	if not name or not frappe.db.exists("Landed Cost Voucher", name):
		frappe.throw(_("Unknown Landed Cost Voucher: {0}").format(name))

	lcv = frappe.get_doc("Landed Cost Voucher", name)
	if lcv.docstatus != 0:
		frappe.throw(_("Only draft Landed Cost Vouchers can be submitted."))

	# Grouped by doctype rather than filtered down to the Purchase Receipt rows:
	# an invoice-backed voucher was reduced to an empty list here, so the lock it
	# should have been checked against could never fire and a second voucher on a
	# different basis submitted freely over stock the first had capitalized.
	rows_by_type: dict[str, list] = {}
	for row in lcv.get("purchase_receipts") or []:
		if row.receipt_document and row.receipt_document_type:
			rows_by_type.setdefault(row.receipt_document_type, []).append(row.receipt_document)
	locked_by = locked_method = None
	for kind, names in rows_by_type.items():
		locked_by, locked_method = _locking_voucher(names, kind)
		if locked_by:
			break
	frozen = lcv_math.normalize_distribution_method(locked_method)
	mine = lcv_math.normalize_distribution_method(lcv.distribute_charges_based_on)
	if frozen and mine != frozen:
		frappe.throw(
			_(
				"This voucher distributes on {0}, but {1} already froze the basis at {2} for the "
				"same receipts. Submitting it would net later customs charges against amounts "
				"capitalized on a different distribution. Cancel {1}, or rebuild this draft."
			).format(mine or lcv.distribute_charges_based_on, locked_by, frozen)
		)

	lcv.submit()
	return {
		"status": "ok",
		"name": lcv.name,
		"docstatus": lcv.docstatus,
		"distribute_charges_based_on": lcv.distribute_charges_based_on,
	}


@frappe.whitelist()
def cancel_landed_cost_voucher(name: str):
	"""Cancel a submitted Landed Cost Voucher directly from Stabler SPA.

	Cancelling reverses ERPNext's own valuation and GL postings (its
	``LandedCostVoucher.on_cancel``) and, through the ``on_cancel`` hook
	``release_cost_lines_for_lcv``, clears ``lcv_ref`` on every Container Cost
	Line the voucher consumed — so the money becomes vouchereable again.
	"""
	_assert_can_write("Landed Cost Voucher", name, "cancel")
	_assert_cost_visible()

	if not name or not frappe.db.exists("Landed Cost Voucher", name):
		frappe.throw(_("Unknown Landed Cost Voucher: {0}").format(name))

	lcv = frappe.get_doc("Landed Cost Voucher", name)
	if lcv.docstatus != 1:
		frappe.throw(_("Only submitted Landed Cost Vouchers can be cancelled."))

	lcv.cancel()
	return {"status": "ok", "name": lcv.name, "docstatus": lcv.docstatus}
