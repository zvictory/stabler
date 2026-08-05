"""Deleting a PI/CI — which links block and which ride along.

The business rule these pin: accounting blocks, operations cascade. A CI whose
payable, payment, landed cost, received stock or customs declaration is still
alive must NOT be deletable — deleting it would leave money in the ledger with
nothing behind it. Containers, trucks, freight bookings, vet certificates and
PO links are operational and may be removed, but only under an explicit
cascade. Anything this module has never heard of blocks: an unclassified link
is exactly the case that would silently orphan a record.
"""

from __future__ import annotations

import unittest

from stabler.api import _imports_delete as m

# The five accounting/official documents that must never be auto-deleted.
GL_DOCS = [
	("Purchase Invoice", 0),
	("Purchase Invoice", 1),
	("Payment Entry", 0),
	("Payment Entry", 1),
	("Landed Cost Voucher", 1),
	("GRN Checklist", 1),
	("Customs Declaration", 0),
]

CASCADE_DOCS = [
	"Import Container",
	"Import Truck",
	"Freight Booking",
	"Vet Certificate",
	"Commercial Invoice PO Link",
]


def R(name, docstatus=0, status=None):
	return {"name": name, "docstatus": docstatus, "status": status}


class GlDocumentAlwaysBlocksTest(unittest.TestCase):
	def test_every_accounting_document_blocks(self):
		for doctype, docstatus in GL_DOCS:
			with self.subTest(doctype=doctype, docstatus=docstatus):
				out = m.classify_impact({doctype: [R("X-1", docstatus)]})
				self.assertFalse(out["deletable"])
				self.assertEqual(len(out["blockers"]), 1)
				self.assertEqual(out["blockers"][0]["doctype"], doctype)
				self.assertEqual(out["blockers"][0]["name"], "X-1")
				self.assertEqual(out["cascade"], {})

	def test_cancelled_accounting_document_no_longer_blocks(self):
		# Cancelling the invoice is exactly the resolution path the blocker
		# message tells the owner to take — it has to actually unblock.
		for doctype in ("Purchase Invoice", "Payment Entry", "Landed Cost Voucher"):
			with self.subTest(doctype=doctype):
				out = m.classify_impact({doctype: [R("X-1", 2)]})
				self.assertTrue(out["deletable"])

	def test_cancelled_accounting_document_is_never_deleted_by_us(self):
		# It stops blocking, but the reversal stays in the ledger — this app
		# deletes no accounting document, cancelled or not.
		for doctype in ("Purchase Invoice", "Payment Entry", "Landed Cost Voucher"):
			with self.subTest(doctype=doctype):
				self.assertEqual(m.cascade_mode(doctype), "ignore")

	def test_customs_declaration_blocks_at_any_docstatus(self):
		for docstatus in (0, 1, 2):
			with self.subTest(docstatus=docstatus):
				out = m.classify_impact({"Customs Declaration": [R("GTD-1", docstatus)]})
				self.assertFalse(out["deletable"])
				self.assertEqual(out["blockers"][0]["code"], m.CUSTOMS_DECLARED)


class GrnChecklistTest(unittest.TestCase):
	def test_submitted_grn_blocks_because_stock_arrived(self):
		out = m.classify_impact({"GRN Checklist": [R("GRN-1", 1)]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["blockers"][0]["code"], m.STOCK_RECEIVED)

	def test_draft_grn_cascades(self):
		out = m.classify_impact({"GRN Checklist": [R("GRN-2", 0)]})
		self.assertTrue(out["deletable"])
		self.assertEqual(out["cascade"], {"GRN Checklist": ["GRN-2"]})

	def test_draft_and_submitted_grn_split_in_one_pass(self):
		out = m.classify_impact({"GRN Checklist": [R("GRN-1", 1), R("GRN-2", 0)]})
		self.assertFalse(out["deletable"])
		self.assertEqual([b["name"] for b in out["blockers"]], ["GRN-1"])
		self.assertEqual(out["cascade"], {"GRN Checklist": ["GRN-2"]})

	def test_cancelled_grn_still_blocks_fail_closed(self):
		out = m.classify_impact({"GRN Checklist": [R("GRN-3", 2)]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["blockers"][0]["code"], m.LINKED_DOCUMENT)


class CascadeTest(unittest.TestCase):
	def test_operational_children_cascade_and_do_not_block(self):
		refs = {dt: [R(f"{dt}-1")] for dt in CASCADE_DOCS}
		out = m.classify_impact(refs)
		self.assertTrue(out["deletable"])
		self.assertEqual(out["blockers"], [])
		self.assertEqual(sorted(out["cascade"]), sorted(CASCADE_DOCS))

	def test_ci_rows_are_detached_not_deleted(self):
		# Deleting a PI must not destroy shipment history; the CI keeps the row
		# and only loses its agreement link.
		self.assertEqual(m.cascade_mode("Commercial Invoice"), "detach")
		self.assertEqual(m.cascade_mode("Commercial Invoice Item"), "detach")
		self.assertEqual(m.cascade_mode("Import Container"), "delete")

	def test_pi_side_refs_cascade(self):
		out = m.classify_impact({"Commercial Invoice": [R("CI-1")], "Commercial Invoice Item": [R("row-1")]})
		self.assertTrue(out["deletable"])
		self.assertEqual(
			out["cascade"], {"Commercial Invoice": ["CI-1"], "Commercial Invoice Item": ["row-1"]}
		)


class NoReferencesTest(unittest.TestCase):
	def test_empty_refs_are_deletable(self):
		out = m.classify_impact({})
		self.assertTrue(out["deletable"])
		self.assertEqual(out["blockers"], [])
		self.assertEqual(out["cascade"], {})

	def test_none_and_empty_lists_are_deletable(self):
		out = m.classify_impact({"Import Container": [], "Purchase Invoice": None})
		self.assertTrue(out["deletable"])
		self.assertEqual(out["blockers"], [])
		self.assertEqual(out["cascade"], {})


class FailClosedTest(unittest.TestCase):
	def test_unknown_doctype_blocks_instead_of_being_ignored(self):
		out = m.classify_impact({"Some Future Doctype": [R("SFD-1")]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["blockers"][0]["code"], m.LINKED_DOCUMENT)
		self.assertEqual(out["cascade"], {})

	def test_linked_proforma_blocks_and_names_the_unlink_route(self):
		out = m.classify_impact({"Proforma Invoice": [R("PI-1")]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["blockers"][0]["code"], m.LINKED_PROFORMA)
		self.assertIn("unlink", out["blockers"][0]["reason"].lower())

	def test_import_expense_is_not_silently_cascaded(self):
		out = m.classify_impact({"Import Expense": [R("IMP-EXP-1")]})
		self.assertFalse(out["deletable"])


class BlockerShapeTest(unittest.TestCase):
	def test_every_blocker_carries_a_named_reason(self):
		refs = {dt: [R(f"{dt}-1", ds)] for dt, ds in GL_DOCS}
		refs["Some Future Doctype"] = [R("SFD-1")]
		refs["Proforma Invoice"] = [R("PI-1")]
		out = m.classify_impact(refs)
		self.assertTrue(out["blockers"])
		for b in out["blockers"]:
			with self.subTest(doctype=b["doctype"]):
				self.assertTrue((b.get("reason") or "").strip(), "blocker reason must never be empty")
				self.assertIn(b["name"], b["reason"], "the reason must name the offending record")
				self.assertTrue((b.get("code") or "").strip())

	def test_blocker_and_cascade_coexist(self):
		out = m.classify_impact({"Purchase Invoice": [R("PINV-1", 1)], "Import Container": [R("CNT-1")]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["cascade"], {"Import Container": ["CNT-1"]})

	def test_missing_docstatus_is_treated_as_draft(self):
		out = m.classify_impact({"Purchase Invoice": [{"name": "PINV-9"}]})
		self.assertFalse(out["deletable"])
		self.assertEqual(out["blockers"][0]["code"], m.LIVE_PAYABLE)


if __name__ == "__main__":
	unittest.main()
