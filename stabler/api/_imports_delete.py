"""Pure deletion-impact rules for Proforma / Commercial Invoice (Frappe-free).

Deleting an import document is never a plain cascade: some of what hangs off a
CI is *accounting* (a live payable, a payment, a landed cost, received stock, a
customs declaration) and some is *operations* (containers, trucks, freight,
vet certificates, PO links). The doctrine — see
``docs/plans/2026-07-29-pi-ci-full-crud.md`` — is "accounting blocks, operations
cascades": an accounting document is a named blocker the owner must resolve
first, an operational child rides along only with an explicit ``cascade=1``.

Kept Frappe-free so the classification unit-tests without a bench; the Frappe
layer (``api.imports.delete_commercial_invoice`` / ``delete_proforma_invoice``)
collects the references, calls :func:`classify_impact`, and applies the plan.

Fail-closed: a doctype this module does not know is counted as a blocker, never
silently ignored — an unclassified link is exactly the case that would leave an
orphan in the ledger.
"""

from __future__ import annotations

# Blocker codes — stable keys the UI translates; ``reason`` is the English
# fallback sentence that also feeds ``frappe.throw`` on a non-dry run.
LIVE_PAYABLE = "live_payable"
LIVE_PAYMENT = "live_payment"
LANDED_COST = "landed_cost"
STOCK_RECEIVED = "stock_received"
CUSTOMS_DECLARED = "customs_declared"
LINKED_PROFORMA = "linked_proforma"
LINKED_DOCUMENT = "linked_document"

# Cascade handling per doctype. "delete" removes the row; "detach" keeps the row
# and blanks its reference — deleting a PI must not destroy shipment history,
# the CI line simply loses its agreement link (the discrepancies screen already
# reports those as shipped-without-a-PI). "ignore" is the belt-and-braces case:
# a CANCELLED accounting document no longer blocks, but this app never deletes
# one either — the reversal has to stay in the ledger.
CASCADE_MODE = {
	"Import Container": "delete",
	"Import Truck": "delete",
	"Freight Booking": "delete",
	"Vet Certificate": "delete",
	"Commercial Invoice PO Link": "delete",
	"GRN Checklist": "delete",  # draft only — see _grn_bucket
	"Commercial Invoice": "detach",
	"Commercial Invoice Item": "detach",
	"Purchase Invoice": "ignore",
	"Payment Entry": "ignore",
	"Landed Cost Voucher": "ignore",
}

_CASCADE = frozenset(CASCADE_MODE)


def _docstatus(row: dict) -> int:
	try:
		return int(row.get("docstatus") or 0)
	except (TypeError, ValueError):
		return 0


def _blocker(doctype: str, name: str, code: str, reason: str) -> dict:
	return {"doctype": doctype, "name": name, "code": code, "reason": reason}


def _live_doc(doctype: str, row: dict, code: str, reason: str):
	"""Accounting document: blocks while it is not cancelled (docstatus < 2)."""
	if _docstatus(row) < 2:
		return _blocker(doctype, row.get("name"), code, reason.format(name=row.get("name")))
	return None


def _grn_bucket(row: dict):
	"""Draft GRN cascades; submitted GRN means stock arrived and blocks."""
	ds = _docstatus(row)
	if ds == 0:
		return None
	if ds == 1:
		return _blocker(
			"GRN Checklist",
			row.get("name"),
			STOCK_RECEIVED,
			"GRN Checklist {name} is submitted — stock was received. Cancel it first.".format(
				name=row.get("name")
			),
		)
	return _blocker(
		"GRN Checklist",
		row.get("name"),
		LINKED_DOCUMENT,
		"GRN Checklist {name} is cancelled and still linked — resolve it manually first.".format(
			name=row.get("name")
		),
	)


def _classify_row(doctype: str, row: dict):
	"""Return a blocker dict, or None when the row is safe to cascade."""
	if doctype == "Purchase Invoice":
		return _live_doc(
			doctype,
			row,
			LIVE_PAYABLE,
			"Purchase Invoice {name} is not cancelled — a live payable sits on the ledger. Cancel the invoice first.",
		)
	if doctype == "Payment Entry":
		return _live_doc(
			doctype,
			row,
			LIVE_PAYMENT,
			"Payment Entry {name} is not cancelled — money is already booked against this document. Cancel the payment first.",
		)
	if doctype == "Landed Cost Voucher":
		return _live_doc(
			doctype,
			row,
			LANDED_COST,
			"Landed Cost Voucher {name} is not cancelled — landed cost is spread over stock. Cancel it first.",
		)
	if doctype == "GRN Checklist":
		return _grn_bucket(row)
	if doctype == "Customs Declaration":
		return _blocker(
			doctype,
			row.get("name"),
			CUSTOMS_DECLARED,
			"Customs Declaration {name} exists — an official declaration is never deleted from here.".format(
				name=row.get("name")
			),
		)
	if doctype == "Proforma Invoice":
		return _blocker(
			doctype,
			row.get("name"),
			LINKED_PROFORMA,
			"Proforma Invoice {name} is still superseded by this invoice — unlink the proforma first.".format(
				name=row.get("name")
			),
		)
	if doctype in _CASCADE:
		return None
	return _blocker(
		doctype,
		row.get("name"),
		LINKED_DOCUMENT,
		"{doctype} {name} is linked and has no deletion rule — resolve it manually first.".format(
			doctype=doctype, name=row.get("name")
		),
	)


def classify_impact(refs: dict) -> dict:
	"""Split the documents referencing a PI/CI into blockers and cascade.

	``refs`` maps a doctype to the rows that point at the document being
	deleted: ``{"<Doctype>": [{"name": ..., "docstatus": ..., "status": ...}]}``.

	Returns ``{"blockers": [...], "cascade": {doctype: [names]}, "deletable": bool}``.
	``deletable`` is True only when nothing blocks; a non-empty ``cascade`` still
	needs the caller's explicit ``cascade=1``.
	"""
	blockers: list[dict] = []
	cascade: dict[str, list[str]] = {}

	for doctype in sorted(refs or {}):
		for row in refs[doctype] or []:
			row = row or {}
			blocker = _classify_row(doctype, row)
			if blocker:
				blockers.append(blocker)
			else:
				cascade.setdefault(doctype, []).append(row.get("name"))

	return {"blockers": blockers, "cascade": cascade, "deletable": not blockers}


def cascade_mode(doctype: str) -> str:
	"""How the Frappe layer applies a cascade row: "delete" or "detach"."""
	return CASCADE_MODE.get(doctype, "delete")
