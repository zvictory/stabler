"""Structural guards for deleting a Proforma / Commercial Invoice.

Delete is the one CRUD verb that cannot be undone, so the contract is: the
endpoint never deletes on the first call. It reports what would happen
(``dry_run=1``, the default), the screen shows that report, and only an
explicit red confirmation calls back with ``dry_run=0``. An accounting document
in the way is a named blocker the owner has to clear first — never something
this code cancels on their behalf.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
RULES = os.path.join(_ROOT, "api", "_imports_delete.py")
CI_FORM = os.path.join(_ROOT, "public", "js", "pages", "imports", "CommercialInvoiceForm.vue")
PI_FORM = os.path.join(_ROOT, "public", "js", "pages", "imports", "ProformaForm.vue")
IMPACT = os.path.join(_ROOT, "public", "js", "composables", "deleteImpact.js")

# Anything that changes the database. A dry run must reach none of them.
MUTATIONS = (".delete(", "delete_doc(", "db_set(", "db.set_value(", ".cancel(", ".save(", ".insert(")

ENDPOINTS = ("delete_commercial_invoice", "delete_proforma_invoice", "unlink_proforma_from_ci")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def vue_fn(src, name):
	"""The body of one Vue handler — a global index() would match the other
	confirms already on these forms and prove nothing."""
	start = src.index(f"async function {name}(")
	end = src.index("\n}\n", start)
	return src[start:end]


class EndpointGateTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)

	def test_all_three_are_whitelisted(self):
		for fn in ENDPOINTS:
			with self.subTest(fn=fn):
				self.assertRegex(self.src, rf"@frappe\.whitelist\(\)\ndef {fn}\(")

	def test_all_three_are_imports_gated(self):
		for fn in ENDPOINTS:
			with self.subTest(fn=fn):
				self.assertIn("_assert_imports_access(company)", body(self.src, fn))

	def test_deletes_check_the_delete_permission_not_just_the_login(self):
		# @frappe.whitelist() only proves the caller is signed in; the record
		# itself has to be theirs to delete.
		self.assertIn(
			'_assert_can_write("Commercial Invoice", name, "delete")',
			body(self.src, "delete_commercial_invoice"),
		)
		self.assertIn(
			'_assert_can_write("Proforma Invoice", name, "delete")',
			body(self.src, "delete_proforma_invoice"),
		)

	def test_deletes_are_cost_gated(self):
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			with self.subTest(fn=fn):
				self.assertIn("_assert_cost_visible()", body(self.src, fn))

	def test_company_of_the_record_is_verified(self):
		# Without it the company argument is decoration and any signed-in user
		# could delete another tenant's document by name.
		self.assertIn("belongs to a different company", body(self.src, "delete_commercial_invoice"))
		self.assertIn("belongs to a different company", body(self.src, "delete_proforma_invoice"))


class DryRunIsTheDefaultTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)

	def test_both_deletes_default_to_dry_run_and_no_cascade(self):
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			with self.subTest(fn=fn):
				self.assertRegex(self.src, rf"def {fn}\([^)]*cascade: int = 0")
				self.assertRegex(self.src, rf"def {fn}\([^)]*dry_run: int = 1")

	def test_dry_run_returns_before_any_mutation(self):
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			fn_body = body(self.src, fn)
			plan_return = fn_body.index("if cint(dry_run):")
			for token in MUTATIONS:
				if token not in fn_body:
					continue
				with self.subTest(fn=fn, token=token):
					self.assertLess(
						plan_return,
						fn_body.index(token),
						"dry_run must short-circuit before any mutation",
					)

	def test_the_dry_run_branch_itself_writes_nothing(self):
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			fn_body = body(self.src, fn)
			branch = fn_body[fn_body.index("if cint(dry_run):") : fn_body.index('if plan["blockers"]:')]
			for token in MUTATIONS:
				with self.subTest(fn=fn, token=token):
					self.assertNotIn(token, branch)


class BlockersStopTheDeleteTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)

	def test_a_blocker_throws_instead_of_deleting(self):
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			fn_body = body(self.src, fn)
			with self.subTest(fn=fn):
				self.assertIn('if plan["blockers"]:', fn_body)
				# The reason the classifier wrote — never a generic "cannot delete".
				self.assertIn('frappe.throw(plan["blockers"][0]["reason"])', fn_body)
				self.assertLess(fn_body.index('if plan["blockers"]:'), fn_body.index("_apply_cascade("))

	def test_no_endpoint_cancels_an_accounting_document_to_clear_its_own_way(self):
		# Cancelling a live payable is the owner's decision, in the invoice
		# screen, with their eyes on the ledger — not a delete side effect.
		for fn in ENDPOINTS:
			with self.subTest(fn=fn):
				self.assertNotIn(".cancel(", body(self.src, fn))

	def test_cascade_zero_removes_nothing(self):
		guard = body(self.src, "_assert_cascade_allowed")
		self.assertIn('if plan["cascade"] and not cint(cascade):', guard)
		self.assertIn("frappe.throw(", guard)
		for fn in ("delete_commercial_invoice", "delete_proforma_invoice"):
			fn_body = body(self.src, fn)
			with self.subTest(fn=fn):
				self.assertLess(
					fn_body.index("_assert_cascade_allowed(plan, cascade)"),
					fn_body.index("_apply_cascade("),
				)

	def test_children_go_before_the_parent_in_one_transaction(self):
		for fn, doctype in (
			("delete_commercial_invoice", "Commercial Invoice"),
			("delete_proforma_invoice", "Proforma Invoice"),
		):
			fn_body = body(self.src, fn)
			with self.subTest(fn=fn):
				self.assertLess(
					fn_body.index("_apply_cascade("),
					fn_body.index(f'frappe.delete_doc("{doctype}"'),
				)
				self.assertIn("frappe.db.rollback()", fn_body)
				self.assertIn("for_update=True", fn_body)


class ProformaDeleteKeepsTheShipmentTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)

	def test_ci_rows_are_blanked_not_deleted(self):
		# A shipment that physically happened must survive its proforma being
		# deleted; it just loses the agreement link.
		self.assertEqual(read(RULES).count('"Commercial Invoice": "detach"'), 1)
		cascade = body(self.src, "_apply_cascade")
		self.assertIn('if mode == "detach":', cascade)
		self.assertIn("frappe.db.set_value(doctype, name, field, None", cascade)
		self.assertIn('"Commercial Invoice": "custom_proforma_invoice"', self.src)
		self.assertIn('"Commercial Invoice Item": "custom_proforma_invoice"', self.src)

	def test_a_detach_never_falls_through_to_a_delete(self):
		cascade = body(self.src, "_apply_cascade")
		detach = cascade[cascade.index('if mode == "detach":') : cascade.index("else:")]
		self.assertNotIn("delete_doc", detach)

	def test_a_cancelled_accounting_document_is_skipped_not_deleted(self):
		cascade = body(self.src, "_apply_cascade")
		self.assertIn('if mode == "ignore":', cascade)
		self.assertLess(cascade.index('if mode == "ignore":'), cascade.index("delete_doc"))


class ReferenceScanTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)
		self.scan = body(self.src, "_ci_reference_rows")

	def test_one_query_per_doctype_never_per_record(self):
		# A CI with 40 containers must cost the same number of queries as one
		# with 2 — the loop is over the doctype tuple, not over rows.
		loop = self.scan[
			self.scan.index("for doctype in _CI_LINK_DOCTYPES:") : self.scan.index("# The live payable")
		]
		self.assertEqual(loop.count("frappe.get_all("), 1)
		self.assertEqual(loop.count("frappe.db.sql("), 0)

	def test_dependent_lookups_are_batched_with_in_filters(self):
		self.assertIn('"custom_import_container": ["in", containers]', self.scan)
		self.assertIn('filters={"parent": ["in", grns]}', self.scan)
		self.assertIn('filters={"name": ["in", lcvs]', self.scan)

	def test_the_scan_only_reads(self):
		for token in MUTATIONS:
			with self.subTest(token=token):
				self.assertNotIn(token, self.scan)
				self.assertNotIn(token, body(self.src, "_proforma_reference_rows"))

	def test_the_live_payable_is_found_by_both_columns(self):
		# convert_ci_to_purchase_invoice writes the CI name into bill_no;
		# custom_commercial_invoice does not exist on every site. Matching only
		# one of them would report an invoiced CI as freely deletable.
		self.assertIn("pi.bill_no = %(ci)s", self.scan)
		self.assertIn('has_column("Purchase Invoice", "custom_commercial_invoice")', self.scan)
		self.assertIn("pi.docstatus < 2", self.scan)

	def test_optional_columns_are_guarded(self):
		proforma = body(self.src, "_proforma_reference_rows")
		self.assertIn('has_column("Commercial Invoice Item", "custom_proforma_invoice")', proforma)
		self.assertIn('has_column("Commercial Invoice", "custom_proforma_invoice")', proforma)


class UnlinkTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "unlink_proforma_from_ci")

	def test_it_is_the_inverse_of_the_link_and_invents_no_new_bypass(self):
		self.assertIn("pi.commercial_invoice = None", self.body)
		self.assertIn("if pi.status == _proforma.SUPERSEDED:", self.body)
		self.assertIn("pi.status = _proforma.CONFIRMED", self.body)
		# Boşluk-bağımsız: `update_modified=False` argümanıyla çağrı 110 karakteri
		# aştığı için biçimlendirici onu üç satıra böldü ve tek satırlık literale
		# çakılı assertIn kırmızıya döndü. Aranan şey CI'ın alanının None'a
		# çekilmesi; çağrının kaç satıra yayıldığı testin konusu değil. Regex her
		# iki biçimi de kabul ediyor, yoksa satırlar tekrar birleşince aynı test
		# ters yönde kırılırdı.
		self.assertRegex(
			self.body,
			r'frappe\.db\.set_value\(\s*"Commercial Invoice",\s*target,'
			r'\s*"custom_proforma_invoice",\s*None',
		)

	def test_unlinking_the_wrong_pair_is_refused(self):
		self.assertIn("linked != commercial_invoice", self.body)
		self.assertIn("frappe.throw(", self.body)

	def test_it_is_idempotent(self):
		self.assertIn('"changed": False', self.body)

	def test_it_deletes_nothing(self):
		for token in (".delete(", "delete_doc("):
			with self.subTest(token=token):
				self.assertNotIn(token, self.body)


class FormsAskBeforeTheyActTest(unittest.TestCase):
	def setUp(self):
		self.ci = read(CI_FORM)
		self.pi = read(PI_FORM)

	def test_both_forms_plan_then_confirm_then_act(self):
		for label, src in (("ci", self.ci), ("pi", self.pi)):
			fn = vue_fn(src, "openDeletePlan")
			act = vue_fn(src, "confirmDelete")
			with self.subTest(form=label):
				self.assertIn("dry_run: 1", fn)
				self.assertNotIn("dry_run: 0", fn)
				self.assertIn("await confirm(", act)
				self.assertIn("dry_run: 0", act)
				self.assertLess(act.index("await confirm("), act.index("dry_run: 0"))
				self.assertIn("danger: true", act)

	def test_the_delete_button_stays_dead_while_anything_blocks(self):
		for label, src in (("ci", self.ci), ("pi", self.pi)):
			with self.subTest(form=label):
				self.assertIn(':disabled="!canDelete || deleting"', src)
				# The reason travels with the disabled button, not into a log.
				self.assertIn("blockerText(deleteBlockers[0])", src)

	def test_cascade_is_opt_in_on_screen(self):
		for label, src in (("ci", self.ci), ("pi", self.pi)):
			fn = vue_fn(src, "openDeletePlan")
			with self.subTest(form=label):
				self.assertIn("deleteCascade.value = false", fn)
				self.assertIn('v-model="deleteCascade"', src)
				self.assertIn("cascade: deleteCascade.value ? 1 : 0", vue_fn(src, "confirmDelete"))

	def test_every_blocker_is_named_and_linked_to_the_screen_that_clears_it(self):
		for label, src in (("ci", self.ci), ("pi", self.pi)):
			with self.subTest(form=label):
				self.assertIn("recordRoute(b.doctype, b.name)", src)
				self.assertIn("blockerText(b)", src)

	def test_the_report_says_detach_where_it_detaches(self):
		# "will be deleted" next to a row that is only unlinked would mislead
		# the owner at the exact moment they decide.
		self.assertIn("cascade_modes", read(API))
		self.assertIn('modes[doctype] === "detach"', read(IMPACT))
		for label, src in (("ci", self.ci), ("pi", self.pi)):
			with self.subTest(form=label):
				self.assertIn("row.detach ?", src)

	def test_the_ci_form_can_undo_a_proforma_link(self):
		fn = vue_fn(self.ci, "unlinkProforma")
		self.assertIn("stabler.api.imports.unlink_proforma_from_ci", fn)
		self.assertIn("await confirm(", fn)
		self.assertLess(fn.index("await confirm("), fn.index("unlink_proforma_from_ci"))

	def test_no_desk_links(self):
		for label, src in (("ci", self.ci), ("pi", self.pi), ("impact", read(IMPACT))):
			with self.subTest(file=label):
				self.assertNotIn('"/app', src)


if __name__ == "__main__":
	unittest.main()
