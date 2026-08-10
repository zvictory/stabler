"""Imports-module status automation (frappe-facing orchestration layer).

Two status-driven side effects are wired here via ``doc_events`` (see the app
``hooks.py`` registration for Import Container / Import Truck):

* Import Container -> ARRIVED_AT_IRAN : enqueue a job that creates a DRAFT
  Payment Entry for the 70% goods advance (M2 — never a Purchase Invoice at
  arrival; billing follows receipt).
* Import Truck -> CROSSED_BORDER : create a DRAFT service Purchase Invoice for
  the cross-border trucking cost.

Every entry point starts with the M6 guard (``should_run``): no-op during ETL
(``frappe.flags.in_msaerp_migration``) and no-op for companies with the
``imports`` module disabled. Documents are NEVER auto-submitted — both the PE
and the PI are left as drafts for a human to review and submit.

All money math and run/skip decisions live in ``payment_math`` (frappe-free) so
they can be unit-tested without a bench.
"""

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, today

from stabler.stabler.imports_module import customs_fee_math, lcv_math, packing_service, receipt_math
from stabler.stabler.imports_module import payment_math as pm


def patch_payment_entry_references():
	"""Ensure PaymentEntry accepts Proforma Invoice as a valid reference doctype for Supplier.

	ERPNext/HRMS EmployeePaymentEntry strictly validates get_valid_reference_doctypes
	and requires ref_doc.docstatus == 1 / latest_data outstanding checks. Proforma
	Invoice is a non-submittable custom Stabler doctype. This patch allows
	Proforma Invoice references to pass Payment Entry validation smoothly.
	"""
	try:
		from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

		classes = [PaymentEntry]
		try:
			from hrms.overrides.employee_payment_entry import EmployeePaymentEntry

			classes.append(EmployeePaymentEntry)
		except ImportError:
			pass

		for cls in classes:
			if getattr(cls, "_stabler_pi_patched", False):
				continue
			cls._stabler_pi_patched = True

			_orig_get_valid = cls.get_valid_reference_doctypes

			def _make_get_valid(orig):
				def new_get_valid(self):
					res = list(orig(self) or ())
					if self.party_type == "Supplier" and "Proforma Invoice" not in res:
						res.append("Proforma Invoice")
					return tuple(res)

				return new_get_valid

			cls.get_valid_reference_doctypes = _make_get_valid(_orig_get_valid)

			def _make_pop_wrapper(orig):
				def wrapper(self):
					pi_refs = [
						r for r in (self.get("references") or []) if r.reference_doctype == "Proforma Invoice"
					]
					if pi_refs:
						self.references = [
							r for r in self.references if r.reference_doctype != "Proforma Invoice"
						]
					try:
						return orig(self)
					finally:
						if pi_refs:
							self.references.extend(pi_refs)

				return wrapper

			if hasattr(cls, "validate_reference_documents"):
				cls.validate_reference_documents = _make_pop_wrapper(cls.validate_reference_documents)
			if hasattr(cls, "validate_allocated_amount"):
				cls.validate_allocated_amount = _make_pop_wrapper(cls.validate_allocated_amount)

	except Exception:
		pass


patch_payment_entry_references()


def _imports_enabled(company) -> bool:
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	return bool(module_map_for(company).get("imports"))


def _should_run(doc) -> bool:
	"""M6 guard applied to a document (migration flag + per-company toggle)."""
	return pm.should_run_automation(
		bool(frappe.flags.in_msaerp_migration),
		_imports_enabled(getattr(doc, "company", None)),
	)


# ---------------------------------------------------------------------------
# Commercial Invoice: STUFFED -> GRN Checklist (DRAFT)
# ---------------------------------------------------------------------------


def on_commercial_invoice_update(doc, method=None):
	"""doc_events on_update for Commercial Invoice. Auto-creates GRN on STUFFED status."""
	if not _should_run(doc):
		return
	if not doc.has_value_changed("status"):
		return
	before = doc.get_doc_before_save()
	old_status = before.status if before else None
	if old_status != "STUFFED" and doc.status == "STUFFED":
		create_grn_for_ci_hook(doc)


def create_grn_for_ci_hook(ci):
	"""Create a GRN Checklist from a Commercial Invoice (idempotent, hook version)."""
	return packing_service.create_or_get_grn(ci, ignore_permissions=True)


# ---------------------------------------------------------------------------
# Import Container: ARRIVED_AT_IRAN -> 70% advance Payment Entry (DRAFT)
# ---------------------------------------------------------------------------


def on_container_update(doc, method=None):
	"""doc_events on_update for Import Container. Enqueues the advance PE job."""
	if not _should_run(doc):
		return
	if not doc.has_value_changed("status"):
		return
	before = doc.get_doc_before_save()
	old_status = before.status if before else None
	if not pm.wants_advance_pe(old_status, doc.status):
		return
	frappe.enqueue(
		"stabler.stabler.imports_module.hooks.create_advance_pe",
		queue="default",
		enqueue_after_commit=True,
		container_name=doc.name,
	)


def create_advance_pe(container_name: str):
	"""Background job: create the DRAFT 70% advance Payment Entry for a container."""
	container = frappe.get_doc("Import Container", container_name)
	# Re-check the guard inside the job — company toggle / migration flag may
	# have changed between enqueue and execution.
	if not _should_run(container):
		return
	if container.status != "ARRIVED_AT_IRAN":
		return

	# Idempotency: stored link on the container, or an existing PE carrying the
	# 70PCT-<container> marker (covers a crash between insert and db_set).
	if container.get("advance_70_payment_entry"):
		return
	reference_no = pm.advance_reference_no(container_name)
	if frappe.db.exists("Payment Entry", {"reference_no": reference_no}):
		return

	if not container.supplier:
		frappe.logger("stabler.imports").warning(
			f"Import Container {container_name}: no supplier — cannot create 70% advance PE"
		)
		return

	po_rows = _linked_po_rows(container.commercial_invoice)
	if not po_rows:
		frappe.logger("stabler.imports").warning(
			f"Import Container {container_name}: no linked Purchase Orders — "
			"creating advance PE without references"
		)

	payload = pm.build_advance_pe_payload(
		company=container.company,
		supplier=container.supplier,
		currency=container.get("currency") or "USD",
		total_amount=flt(container.total_amount),
		po_rows=po_rows,
		container_name=container_name,
	)
	payload["reference_date"] = today()
	payload["posting_date"] = today()

	pe = frappe.get_doc(payload)
	# Best-effort account resolution; ERPNext's set_missing_values fills the rest.
	_apply_pay_accounts(pe, container.company, container.supplier)
	pe.insert(ignore_permissions=True)  # DRAFT — NEVER submit here.

	container.db_set("advance_70_payment_entry", pe.name)
	frappe.db.commit()


def _linked_po_rows(commercial_invoice) -> list[dict]:
	"""POs linked to a CI via Commercial Invoice PO Link, with grand_total weights."""
	if not commercial_invoice:
		return []
	links = frappe.get_all(
		"Commercial Invoice PO Link",
		filters={"commercial_invoice": commercial_invoice},
		pluck="purchase_order",
	)
	rows: list[dict] = []
	seen: set = set()
	for po in links:
		if not po or po in seen:
			continue
		seen.add(po)
		grand_total = frappe.db.get_value("Purchase Order", po, "grand_total") or 0
		rows.append({"purchase_order": po, "grand_total": grand_total})
	return rows


def _apply_pay_accounts(pe, company, supplier) -> None:
	"""Fill paid_to (party payable) and paid_from (a company bank/cash) best-effort.

	Fully defensive: ERPNext's own set_missing_values fills whatever is left, and
	the PE stays a draft regardless, so a missing default here is never fatal.
	"""
	try:
		from erpnext.accounts.party import get_party_account

		pe.paid_to = get_party_account("Supplier", supplier, company)
	except Exception:
		pass
	try:
		paid_from = frappe.get_cached_value(
			"Company", company, "default_bank_account"
		) or frappe.get_cached_value("Company", company, "default_cash_account")
		if paid_from:
			pe.paid_from = paid_from
	except Exception:
		pass


# ---------------------------------------------------------------------------
# Import Truck: CROSSED_BORDER -> cross-border transport Purchase Invoice (DRAFT)
# ---------------------------------------------------------------------------


def on_truck_update(doc, method=None):
	"""doc_events on_update for Import Truck. Creates the transport PI."""
	if not _should_run(doc):
		return
	if not doc.has_value_changed("status"):
		return
	before = doc.get_doc_before_save()
	old_status = before.status if before else None
	if not pm.wants_transport_pi(old_status, doc.status):
		return
	create_transport_pi(doc.name)


def create_transport_pi(truck_name: str):
	"""Create the DRAFT cross-border transport Purchase Invoice for a truck."""
	truck = frappe.get_doc("Import Truck", truck_name)
	if not _should_run(truck):
		return
	if truck.status != "CROSSED_BORDER":
		return
	if truck.get("transport_purchase_invoice"):
		return
	# NB: no early return on a zero truck.transport_cost — a linked Import Expense
	# (tier 1/2) can drive the bill even when the truck carries no flat cost. The
	# tier resolver returns None when no source has a positive cost.

	reference_no = pm.transport_reference_no(truck_name)
	if frappe.db.exists("Purchase Invoice", {"bill_no": reference_no}):
		return

	# 3-tier transport cost source (Django signals.py:871): tier 1 an Import
	# Expense (category Transport) explicitly linked to this truck, tier 2 an
	# unlinked one matching the trucking company (auto-linked/consumed), tier 3
	# the truck's own flat transport_cost. The tier arithmetic is a pure function.
	tier1 = _first_unbilled_transport_expense(truck.commercial_invoice, truck=truck_name)
	tier2 = None
	if not tier1 and truck.trucking_company:
		tier2 = _first_unbilled_transport_expense(
			truck.commercial_invoice, supplier=truck.trucking_company, unlinked=True
		)
	source = pm.resolve_transport_source(
		tier1_expense=tier1,
		tier2_expense=tier2,
		truck_transport_cost=flt(truck.transport_cost),
		truck_supplier=truck.trucking_company,
		truck_currency=truck.get("transport_currency"),
	)
	if not source:
		frappe.logger("stabler.imports").info(
			f"Import Truck {truck_name}: no transport cost source found — skipping transport PI"
		)
		return
	if not source["supplier"]:
		frappe.logger("stabler.imports").warning(
			f"Import Truck {truck_name}: no trucking company/supplier — cannot create transport PI"
		)
		return

	_ensure_xborder_item()

	payload = pm.build_transport_pi_payload(
		company=truck.company,
		supplier=source["supplier"],
		currency=source["currency"],
		transport_cost=source["amount"],
		truck_name=truck_name,
		commercial_invoice=truck.commercial_invoice,
		import_expense=source.get("consume_expense"),
	)
	if payload is None:
		return
	payload["posting_date"] = today()
	payload["set_posting_time"] = 1

	pi = frappe.get_doc(payload)
	pi.insert(ignore_permissions=True)  # DRAFT — NEVER submit here.

	truck.db_set("transport_purchase_invoice", pi.name)
	# Mark the consumed Import Expense (tiers 1-2) as billed, and auto-link a
	# tier-2 (previously unlinked) expense to this truck (Django update()).
	if source["consume_expense"]:
		exp_updates = {"purchase_invoice": pi.name}
		if not frappe.db.get_value("Import Expense", source["consume_expense"], "truck"):
			exp_updates["truck"] = truck_name
		frappe.db.set_value("Import Expense", source["consume_expense"], exp_updates)
	frappe.db.commit()


def _first_unbilled_transport_expense(commercial_invoice, *, truck=None, supplier=None, unlinked=False):
	"""First not-yet-billed Import Expense (category Transport) for the tier lookup.

	Returns ``{"name", "amount", "supplier", "currency"}`` or ``None``. ``truck``
	pins tier 1 (explicitly linked); ``supplier`` + ``unlinked`` pins tier 2 (an
	expense for the trucking company with no truck link). "Not yet billed" means
	an empty ``purchase_invoice``.
	"""
	if not commercial_invoice:
		return None
	filters = {"commercial_invoice": commercial_invoice, "category": "Transport"}
	if truck is not None:
		filters["truck"] = truck
	if supplier is not None:
		filters["supplier"] = supplier
	if unlinked:
		filters["truck"] = ["in", ["", None]]
	rows = frappe.get_all(
		"Import Expense",
		filters=filters,
		fields=["name", "amount", "supplier", "currency", "purchase_invoice"],
		order_by="creation asc",
	)
	for r in rows:
		if (r.get("purchase_invoice") or "").strip():
			continue
		return {
			"name": r.name,
			"amount": r.amount,
			"supplier": r.supplier,
			"currency": r.currency,
		}
	return None


def _ensure_xborder_item() -> None:
	"""Defensive create of the service item (patch v43 is the primary creator)."""
	if frappe.db.exists("Item", pm.XBORDER_ITEM_CODE):
		return
	item_group = _pick_item_group()
	if not item_group:
		return
	doc = frappe.new_doc("Item")
	doc.item_code = pm.XBORDER_ITEM_CODE
	doc.item_name = pm.XBORDER_ITEM_CODE
	doc.item_group = item_group
	doc.stock_uom = "Nos"
	doc.is_stock_item = 0
	doc.is_purchase_item = 1
	doc.is_sales_item = 0
	doc.insert(ignore_permissions=True)


def _pick_item_group():
	for group in ("Services", "All Item Groups"):
		if frappe.db.exists("Item Group", group):
			return group
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name")


# ---------------------------------------------------------------------------
# Import Expense -> DRAFT service Purchase Invoice (non-transport categories)
# ---------------------------------------------------------------------------


def import_expense_on_update(doc, method=None):
	"""doc_events on_update for Import Expense.

	When a supplier and a positive amount are set (and no PI exists yet), create a
	DRAFT service Purchase Invoice. Transport-category expenses are billed by the
	truck CROSSED_BORDER hook (the 3-tier lookup) instead, so they are skipped
	here to avoid a double bill. Idempotent (stored link + bill_no marker).
	"""
	if not _should_run(doc):
		return
	if not pm.wants_expense_pi(doc.category, doc.supplier, doc.amount, doc.get("purchase_invoice")):
		return

	reference_no = pm.import_expense_reference_no(doc.name)
	if frappe.db.exists("Purchase Invoice", {"bill_no": reference_no}):
		return

	_ensure_import_service_item()

	payload = pm.build_import_expense_pi_payload(
		company=doc.company,
		supplier=doc.supplier,
		currency=doc.get("currency") or "USD",
		amount=flt(doc.amount),
		category=doc.category or "Other",
		description=doc.get("description") or "",
		expense_name=doc.name,
		commercial_invoice=doc.get("commercial_invoice"),
		container=doc.get("container"),
		truck=doc.get("truck"),
	)
	if payload is None:
		return
	payload["posting_date"] = today()
	payload["set_posting_time"] = 1

	pi = frappe.get_doc(payload)
	pi.insert(ignore_permissions=True)  # DRAFT — NEVER submit here.
	doc.db_set("purchase_invoice", pi.name)
	frappe.db.commit()


def _ensure_import_service_item() -> None:
	"""Defensive create of the Import Service item (patch v45 is the primary creator)."""
	if frappe.db.exists("Item", pm.IMPORT_SERVICE_ITEM_CODE):
		return
	item_group = _pick_item_group()
	if not item_group:
		return
	doc = frappe.new_doc("Item")
	doc.item_code = pm.IMPORT_SERVICE_ITEM_CODE
	doc.item_name = pm.IMPORT_SERVICE_ITEM_CODE
	doc.item_group = item_group
	doc.stock_uom = "Nos"
	doc.is_stock_item = 0
	doc.is_purchase_item = 1
	doc.is_sales_item = 0
	doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Truck Receipt -> partial Purchase Receipt (critique M7) + GRN recompute
# ---------------------------------------------------------------------------


def truck_receipt_before_submit(doc, method=None):
	"""Freeze expected packing before the receipt becomes submitted."""
	grn, _truck = _validate_truck_receipt_scope(doc)
	if not _should_run(grn):
		return
	_lock_grn_expected_snapshot(doc.grn_checklist)


def truck_receipt_on_submit(doc, method=None):
	"""doc_events on_submit for Truck Receipt.

	Synchronous (inside the submit transaction) so a failed Purchase Receipt
	rolls the Truck Receipt submit back atomically:
	  1. create + submit the partial Purchase Receipt (the stock event),
	  2. recompute the parent GRN Checklist from all submitted receipts,
	  3. advance the Import Truck to GRN_CREATED where the transition is legal.
	"""
	grn, _truck = _validate_truck_receipt_scope(doc)
	if not _should_run(grn):
		return
	_create_pr_for_truck_receipt(doc)
	recompute_grn_from_receipts(doc.grn_checklist)
	advance_truck_after_receipt(doc.truck)


def _validate_truck_receipt_scope(receipt):
	grn = frappe.get_doc("GRN Checklist", receipt.grn_checklist)
	truck = frappe.get_doc("Import Truck", receipt.truck)
	if receipt.company != grn.company:
		frappe.throw(frappe._("Truck Receipt company must match GRN company."))
	if truck.company != grn.company:
		frappe.throw(frappe._("Truck company must match GRN company."))
	if truck.commercial_invoice != grn.commercial_invoice:
		frappe.throw(frappe._("Truck Commercial Invoice must match GRN Commercial Invoice."))
	return grn, truck


def _lock_grn_expected_snapshot(grn_name: str) -> None:
	commercial_invoice = frappe.db.get_value("GRN Checklist", grn_name, "commercial_invoice")
	packing_service.lock_commercial_invoices([commercial_invoice])
	grn_state = frappe.db.get_value(
		"GRN Checklist",
		grn_name,
		["expected_snapshot_locked"],
		as_dict=True,
		for_update=True,
	)
	if grn_state.expected_snapshot_locked:
		return
	grn = frappe.get_doc("GRN Checklist", grn_name)
	summary = packing_service.summary_for_ci(grn.commercial_invoice, grn.company, for_update=True)
	if summary["status"] != "Ready":
		frappe.throw(
			frappe._(
				"Container packing lists must be complete and reconciled before the first "
				"Truck Receipt can be submitted."
			)
		)
	packing_service.replace_grn_expected_rows(grn, summary["expected_items"])
	grn.expected_snapshot_locked = 1
	grn.expected_snapshot_locked_at = now_datetime()
	with packing_service.allow_expected_snapshot_update():
		grn.save(ignore_permissions=True)


def truck_receipt_on_cancel(doc, method=None):
	"""doc_events on_cancel for Truck Receipt. Blocks while the PR is live."""
	# Gate on the GRN's company, exactly like truck_receipt_on_submit — the receipt
	# and the GRN are guaranteed to share a company by _validate_truck_receipt_scope,
	# but that check only runs on submit, so read the authoritative side here.
	grn_company = frappe.db.get_value("GRN Checklist", doc.grn_checklist, "company")
	if not _should_run(frappe._dict(company=grn_company)):
		return
	if doc.get("purchase_receipt"):
		pr_docstatus = frappe.db.get_value("Purchase Receipt", doc.purchase_receipt, "docstatus")
		if pr_docstatus == 1:
			frappe.throw(
				frappe._(
					"Cancel the linked Purchase Receipt {0} before cancelling this Truck Receipt."
				).format(doc.purchase_receipt)
			)
	recompute_grn_from_receipts(doc.grn_checklist)


def _create_pr_for_truck_receipt(tr) -> None:
	"""Build + submit the partial Purchase Receipt for one Truck Receipt."""
	if tr.get("purchase_receipt"):
		return  # idempotent — already received
	grn = frappe.get_doc("GRN Checklist", tr.grn_checklist)
	supplier = grn.supplier or frappe.db.get_value("Commercial Invoice", grn.commercial_invoice, "supplier")
	if not supplier:
		frappe.logger("stabler.imports").warning(
			f"Truck Receipt {tr.name}: no supplier on GRN/CI — cannot create Purchase Receipt"
		)
		return

	warehouse = None
	if tr.truck:
		warehouse = frappe.db.get_value("Import Truck", tr.truck, "destination_warehouse")
	warehouse = warehouse or grn.warehouse

	po_item_rows = _po_item_rows_for_ci(grn.commercial_invoice)
	warnings: list[str] = []
	lines: list[dict] = []
	for it in tr.items or []:
		qty = receipt_math.good_qty(it.received_kg, it.condition)
		res = receipt_math.resolve_po_rate(it.grn_item_code, po_item_rows)
		if res["warning"]:
			warnings.append(res["warning"])
		batch_no = None
		if qty > 0:
			if frappe.db.get_value("Item", it.grn_item_code, "has_batch_no"):
				bname = receipt_math.batch_name(
					None, grn.commercial_invoice, it.grn_item_code, str(tr.arrival_date)
				)
				batch_no = _ensure_batch(bname, it.grn_item_code, it.get("expiry_date"))
			else:
				warnings.append(f"Item {it.grn_item_code} is not batch-tracked; received without a batch.")
		lines.append(
			receipt_math.build_pr_line(
				item_code=it.grn_item_code,
				qty=qty,
				rate=res["rate"],
				warehouse=warehouse,
				purchase_order=res["purchase_order"],
				purchase_order_item=res["purchase_order_item"],
				batch_no=batch_no,
			)
		)

	payload = receipt_math.build_pr_payload(
		company=tr.company,
		supplier=supplier,
		posting_date=str(tr.arrival_date),
		currency="USD",
		warehouse=warehouse,
		lines=lines,
		truck_receipt_name=tr.name,
	)
	if payload is None:
		if warnings:
			frappe.logger("stabler.imports").warning(
				f"Truck Receipt {tr.name}: nothing receivable (Good qty 0). {'; '.join(warnings)}"
			)
		return

	pr = frappe.get_doc(payload)
	pr.insert(ignore_permissions=True)
	pr.submit()  # the stock event
	tr.db_set("purchase_receipt", pr.name)
	if warnings:
		frappe.logger("stabler.imports").warning(
			f"Truck Receipt {tr.name} -> PR {pr.name}: {'; '.join(warnings)}"
		)


def _po_item_rows_for_ci(commercial_invoice) -> list[dict]:
	"""PO Item rows (name/item_code/rate) across the POs linked to the CI."""
	pos = frappe.get_all(
		"Commercial Invoice PO Link",
		filters={"commercial_invoice": commercial_invoice},
		pluck="purchase_order",
	)
	rows: list[dict] = []
	for po in {p for p in pos if p}:
		for r in frappe.get_all(
			"Purchase Order Item", filters={"parent": po}, fields=["name", "item_code", "rate"]
		):
			rows.append(
				{
					"purchase_order": po,
					"purchase_order_item": r.name,
					"item_code": r.item_code,
					"rate": r.rate,
				}
			)
	return rows


def _ensure_batch(batch_id: str, item_code: str, expiry_date) -> str:
	"""Create the ERPNext Batch on demand (idempotent), returning its id."""
	if frappe.db.exists("Batch", batch_id):
		return batch_id
	batch = frappe.new_doc("Batch")
	batch.batch_id = batch_id
	batch.item = item_code
	if expiry_date:
		batch.expiry_date = expiry_date
	batch.insert(ignore_permissions=True)
	return batch_id


def recompute_grn_from_receipts(grn_name) -> None:
	"""Re-aggregate GRN Checklist received qty from all submitted Truck Receipts.

	The GRN records the *physical* received quantity (all conditions, incl.
	damaged) — the Purchase Receipt separately books only Good-condition stock.
	"""
	if not grn_name:
		return
	grn = frappe.get_doc("GRN Checklist", grn_name)
	if not _should_run(grn):
		return
	receipts = frappe.get_all(
		"Truck Receipt", filters={"grn_checklist": grn_name, "docstatus": 1}, pluck="name"
	)
	agg: dict[str, list] = {}
	dates: list = []
	for name in receipts:
		tr = frappe.get_doc("Truck Receipt", name)
		if tr.arrival_date:
			dates.append(tr.arrival_date)
		for it in tr.items or []:
			boxes, kg = agg.get(it.grn_item_code, (0, 0.0))
			agg[it.grn_item_code] = (boxes + cint(it.received_boxes), kg + flt(it.received_kg))
	for row in grn.grn_items or []:
		boxes, kg = agg.get(row.item_code, (0, 0.0))
		row.received_boxes = boxes
		row.received_kg = round(kg, 2)
	grn.trucks_received_count = len(receipts)
	if dates:
		grn.first_receipt_date = min(dates)
	grn.flags.ignore_permissions = True
	grn.flags.ignore_validate_update_after_submit = True
	grn.save(ignore_permissions=True)  # validate() recomputes derived totals


def advance_truck_after_receipt(truck_name) -> None:
	"""Advance the Import Truck to GRN_CREATED when the transition is legal."""
	if not truck_name:
		return
	truck = frappe.get_doc("Import Truck", truck_name)
	if not _should_run(truck):
		return
	from stabler.stabler.doctype.import_truck.import_truck import _ALLOWED_TRANSITIONS

	if "GRN_CREATED" in _ALLOWED_TRANSITIONS.get(truck.status, set()):
		truck.status = "GRN_CREATED"
		truck.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# GRN Checklist submit gates + Landed Cost Voucher build (critique M8)
# ---------------------------------------------------------------------------


def grn_before_submit(doc, method=None):
	"""doc_events before_submit for GRN Checklist: received-kg + vet-cert gates."""
	if not _should_run(doc):
		return
	if flt(doc.received_total_kg) <= 0:
		frappe.throw(frappe._("GRN Checklist requires at least one received kg before it can be submitted."))
	if doc.get("vet_cert_override"):
		if not set(frappe.get_roles()).intersection(("Imports Manager", "System Manager")):
			frappe.throw(
				frappe._("Only an Imports Manager can override the veterinary certificate requirement.")
			)
		return
	from stabler.stabler.doctype.vet_certificate.vet_certificate import has_valid_vet_cert

	if not has_valid_vet_cert(doc.commercial_invoice):
		frappe.throw(frappe._("A valid veterinary certificate is required to complete this GRN."))


def grn_on_submit(doc, method=None):
	"""doc_events on_submit for GRN Checklist: enqueue the DRAFT LCV build."""
	if not _should_run(doc):
		return
	frappe.enqueue(
		"stabler.stabler.imports_module.hooks.create_landed_cost_voucher",
		queue="default",
		enqueue_after_commit=True,
		grn_name=doc.name,
	)


def create_landed_cost_voucher(grn_name: str):
	"""Background job: build the initial DRAFT Landed Cost Voucher for a GRN."""
	grn = frappe.get_doc("GRN Checklist", grn_name)
	if not _should_run(grn):
		return
	name = _build_and_save_lcv(grn, note="initial")
	frappe.db.commit()
	return name


@frappe.whitelist()
def create_additional_lcv(grn_name: str):
	"""Build an additional DRAFT LCV for late costs (multi-LCV, critique M8).

	Re-collects only the cost lines added/enabled since the last LCV (those with
	an empty ``lcv_ref``) so an additional voucher captures just the delta.
	"""
	grn = frappe.get_doc("GRN Checklist", grn_name)
	if not _should_run(grn):
		frappe.throw(frappe._("Imports module is not enabled for this company."))
	if grn.docstatus != 1:
		frappe.throw(frappe._("Submit the GRN Checklist before adding a Landed Cost Voucher."))
	name = _build_and_save_lcv(grn, note="additional")
	if not name:
		frappe.throw(frappe._("No unconsumed landed-cost lines to voucher."))
	frappe.db.commit()
	return name


def _build_and_save_lcv(grn, note: str):
	"""Collect cost lines -> DRAFT LCV -> append GRN ref -> mark lines consumed."""
	expense_account = frappe.db.get_single_value("Stabler Settings", "imports_lcv_expense_account")
	if not expense_account:
		frappe.throw(
			frappe._(
				"Set the imports landed-cost expense account in Stabler Settings "
				"before creating a Landed Cost Voucher."
			)
		)

	purchase_receipts = _submitted_prs_for_grn(grn.name)
	if not purchase_receipts:
		frappe.logger("stabler.imports").warning(
			f"GRN {grn.name}: no submitted Purchase Receipts — skipping LCV"
		)
		return None

	cost_lines = _collect_cost_lines(grn.commercial_invoice)

	# A carrier's own bill supersedes the hand-typed guess of the same cost on the
	# same container, exactly as the GTD supersedes the hand-typed duty below. The
	# dropped rows are deliberately NOT stamped with the LCV name: they were never
	# consumed, so they stay visible and unvouchered, and unlinking the bill brings
	# them back into the next voucher.
	cost_lines, bill_warnings = lcv_math.supersede_billed(cost_lines)
	for warning in bill_warnings:
		frappe.logger("stabler.imports").warning(f"GRN {grn.name}: {warning}")
	source_rows = [ln["name"] for ln in cost_lines]

	company_currency = frappe.get_cached_value("Company", grn.company, "default_currency")
	usd_rate = _completion_usd_rate(company_currency, grn.completion_date)
	components = lcv_math.aggregate_components(cost_lines, usd_rate, company_currency)

	# A cleared customs declaration (GTD) is the authoritative source of the
	# Uzbekistan import duty + excise: its figures REPLACE any cost-line Uzbek
	# duty (avoid double count); VAT is never capitalized. UZS = company currency.
	from stabler.stabler.doctype.customs_declaration.customs_declaration import approved_gtd_for_ci

	gtd = approved_gtd_for_ci(grn.commercial_invoice)
	if gtd is not None:
		components, warnings = lcv_math.apply_gtd_customs_precedence(
			components, gtd_duty=gtd[0], gtd_excise=gtd[1], gtd_present=True
		)
		for warning in warnings:
			frappe.logger("stabler.imports").warning(f"GRN {grn.name}: {warning}")

	if not components:
		frappe.logger("stabler.imports").info(f"GRN {grn.name}: no unconsumed landed costs")
		return None

	payload = lcv_math.build_lcv_payload(
		company=grn.company,
		purchase_receipts=purchase_receipts,
		components=components,
		expense_account=expense_account,
	)
	if payload is None:
		return None

	lcv = frappe.get_doc(payload)
	try:
		# Populate the Landed Cost Item rows so the charge distributes; the
		# accountant reviews and submits (valuation repost caution).
		lcv.get_items_from_purchase_receipts()
	except Exception:
		frappe.logger("stabler.imports").warning(
			f"GRN {grn.name}: could not auto-fill LCV items from receipts"
		)
	lcv.insert(ignore_permissions=True)  # DRAFT — NEVER submit here.

	grn.append("landed_cost_vouchers", {"lcv": lcv.name, "posted_on": today(), "note": note})
	grn.flags.ignore_validate_update_after_submit = True
	grn.save(ignore_permissions=True)

	for row_name in source_rows:
		frappe.db.set_value("Container Cost Line", row_name, "lcv_ref", lcv.name)
	return lcv.name


def _submitted_prs_for_grn(grn_name) -> list[str]:
	"""Submitted Purchase Receipt names from this GRN's submitted Truck Receipts."""
	receipts = frappe.get_all(
		"Truck Receipt",
		filters={"grn_checklist": grn_name, "docstatus": 1},
		pluck="purchase_receipt",
	)
	out: list[str] = []
	for pr in receipts:
		if pr and frappe.db.get_value("Purchase Receipt", pr, "docstatus") == 1:
			out.append(pr)
	return out


def _collect_cost_lines(commercial_invoice):
	"""Unconsumed Container Cost Lines across the CI's Import Containers.

	Returns the line dicts that feed ``lcv_math``. Each carries its own ``name``
	so the caller can stamp exactly the rows an LCV consumed — it used to return a
	parallel ``row_names`` list, which stopped being safe once ``supersede_billed``
	could drop a line from the middle: the two lists would silently fall out of
	step and stamp the wrong rows as vouchered.

	``container`` and ``purchase_invoice`` are what make that supersede possible —
	the first scopes it so containers cannot supersede each other, the second says
	which line came from a carrier's bill rather than an operator's keyboard.
	"""
	containers = frappe.get_all(
		"Import Container", filters={"commercial_invoice": commercial_invoice}, pluck="name"
	)
	line_dicts: list[dict] = []
	for container in containers:
		doc = frappe.get_doc("Import Container", container)
		for row in doc.cost_lines or []:
			if not row.include_in_landed_cost:
				continue
			if (row.get("lcv_ref") or "").strip():
				continue
			line_dicts.append(
				{
					"name": row.name,
					"container": container,
					"cost_component": row.cost_component,
					"currency": row.currency,
					"amount": row.amount,
					"include_in_landed_cost": row.include_in_landed_cost,
					"purchase_invoice": row.get("purchase_invoice"),
					"lcv_ref": row.get("lcv_ref"),
				}
			)
	return line_dicts


def _completion_usd_rate(company_currency, completion_date) -> float:
	"""USD -> company-currency rate for the GRN completion date (default 1.0)."""
	if company_currency == "USD":
		return 1.0
	try:
		from erpnext.setup.utils import get_exchange_rate

		rate = get_exchange_rate("USD", company_currency, completion_date or today())
		return float(rate) or 1.0
	except Exception:
		frappe.logger("stabler.imports").warning(
			f"Could not resolve USD->{company_currency} rate for {completion_date}; using 1.0"
		)
		return 1.0


# ---------------------------------------------------------------------------
# BRV customs-clearance fee (whitelisted): compute + optionally write CI fields
# ---------------------------------------------------------------------------


@frappe.whitelist()
def compute_customs_fee(commercial_invoice, off_hours=None, on_date=None, apply=0):
	"""Compute the BRV customs-clearance fee for a Commercial Invoice.

	Reads the CI docs_total (the declared USD value), resolves the BRV in force on
	``on_date`` (default the CI date / today) and the tier multiplier, and returns
	the fee breakdown. With ``apply=1`` the computed figures are written back to
	the CI (customs_fee, customs_fee_brv_used, customs_fee_multiplier,
	customs_fee_off_hours). The effective fee is ``customs_fee_override`` when set,
	else the computed fee — these are official figures kept at permlevel 0.
	"""
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	if not _should_run(ci):
		frappe.throw(frappe._("Imports module is not enabled for this company."))

	value_usd = flt(ci.get("docs_total")) or flt(ci.get("agreed_total"))
	if off_hours is None:
		off_hours = cint(ci.get("customs_fee_off_hours"))
	off_hours = bool(cint(off_hours))
	on_date = getdate(on_date or ci.get("ci_date") or today())

	settings_rows = frappe.get_all(
		"Stabler BRV Setting", fields=["effective_date", "value_uzs"], order_by="effective_date desc"
	)
	tiers = frappe.get_all(
		"Stabler Customs Fee Tier",
		fields=["min_value_usd", "max_value_usd", "multiplier"],
		order_by="min_value_usd asc",
	)
	for row in settings_rows:
		row["effective_date"] = getdate(row["effective_date"])

	brv = customs_fee_math.effective_brv(settings_rows, on_date)
	result = customs_fee_math.customs_fee(value_usd, tiers, brv, off_hours=off_hours)

	breakdown = {
		"value_usd": value_usd,
		"fee_uzs": float(result["fee_uzs"]),
		"multiplier": float(result["multiplier"]),
		"brv_value": float(result["brv_value"]),
		"base_fee": float(result["base_fee"]),
		"off_hours_surcharge": float(result["off_hours_surcharge"]),
		"off_hours": off_hours,
	}

	if cint(apply):
		ci.customs_fee = breakdown["fee_uzs"]
		ci.customs_fee_brv_used = breakdown["brv_value"]
		ci.customs_fee_multiplier = breakdown["multiplier"]
		ci.customs_fee_off_hours = 1 if off_hours else 0
		ci.flags.ignore_validate_update_after_submit = True
		ci.save(ignore_permissions=True)
		frappe.db.commit()

	override = flt(ci.get("customs_fee_override"))
	breakdown["effective_fee_uzs"] = override or breakdown["fee_uzs"]
	return breakdown
