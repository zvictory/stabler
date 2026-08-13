"""Guards for hand-linking a transport/service bill to a Commercial Invoice (W1/W2).

Linking a Purchase Invoice to an import does two things: the bill shows up in the
CI's cost overview and its carriers-outstanding figure (``_related_import_bills``
already reads the four v46 refs), and since W3 its net total is capitalized onto
the import's containers, so it reaches stock valuation. That makes the write path
the whole control surface — the four Link fields carry ``read_only: 1``, which is
a Frappe Desk UI hint and blocks nothing on the server, and the SPA's copy of the
rules is decoration.

So the money-relevant properties are all structural, and each has a specific way
of going wrong:

* the module gate must run FIRST, or a tenant without imports can probe and
  write through an imports endpoint;
* a bill that already carries any ref is owned by the automation that stamped
  it — re-linking detaches it from the document that created it;
* a freight bill from the CI's own supplier is CIF, already inside the agreed
  goods price, and would be counted twice;
* an unlink after the cost reached a Landed Cost Voucher strands a capitalized
  cost whose source bill is no longer attributable;
* the candidate panel reports amounts, and amounts in this module are
  permission-masked.

Frappe-free: these assert structural properties of the source, so a refactor
that quietly drops a guard fails CI rather than production.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_bill_import_refs_source -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
IMPORTS = os.path.join(_ROOT, "api", "imports.py")
SETTINGS = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.py")
SETTINGS_JSON = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"stabler_imports_settings",
	"stabler_imports_settings.json",
)
COST_LINE_JSON = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"container_cost_line",
	"container_cost_line.json",
)
HOOKS = os.path.join(_ROOT, "stabler", "imports_module", "hooks.py")


def read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def body(src: str, name: str) -> str:
	"""Extract a top-level function body (up to the next top-level def/decorator)."""
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |#: |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def code(src: str, name: str) -> str:
	"""Function body with its docstring removed — for 'must NOT appear' assertions.

	These functions document what they deliberately avoid, so a prose mention of
	``doc.save()`` would otherwise fail the test that forbids calling it.
	"""
	text = body(src, name)
	m = re.search(r'"""', text)
	if not m:
		return text
	end = text.index('"""', m.end())
	return text[end + 3 :]


class SetBillImportRefsGateOrderTest(unittest.TestCase):
	"""The seven gates of set_bill_import_refs, and the order they must run in."""

	def setUp(self):
		self.body = body(read(IMPORTS), "set_bill_import_refs")

	def test_module_gate_runs_before_any_other_check(self):
		# The imports module is opt-in per company and owned by one tenant. If
		# any check ran before _assert_imports_access, a company with imports
		# OFF would get a different error depending on the state of another
		# tenant's bill — that is a probe, and the write that follows would be
		# an imports write on a non-imports tenant.
		gate = self.body.index("_assert_imports_access(company)")
		for later in (
			"_assert_can_write(",
			"docstatus",
			"_assert_hand_linkable_supplier(",
			"_assert_not_ci_supplier(",
			"frappe.db.set_value(",
		):
			self.assertLess(
				gate,
				self.body.index(later),
				f"{later} runs before the imports module gate",
			)

	def test_record_level_write_permission_is_checked(self):
		# @frappe.whitelist() gates the METHOD, not the record: without this the
		# endpoint writes any Purchase Invoice whose name the caller can guess.
		self.assertIn('_assert_can_write("Purchase Invoice", purchase_invoice)', self.body)

	def test_a_submitted_bill_may_still_be_linked(self):
		# Draft-only was the original rule and it was wrong: a transporter's bill
		# is routinely submitted and paid before anyone attributes it, and there
		# was then no way back. Submitting changes nothing this endpoint cares
		# about — the write is a db.set_value on a traceability Link and moves no
		# GL or valuation figure. Re-narrowing the gate to `!= 0` would silently
		# strand every bill that reached the ledger before the office got to it.
		self.assertNotIn("cint(bill.docstatus) != 0", self.body)

	def test_a_cancelled_bill_may_not_be_linked(self):
		# The half of gate 3 that must survive. Every read of these refs filters
		# `docstatus < 2`, so a cancelled bill's link renders nowhere — while
		# gate 4 below would lock the bill against ever being linked again. That
		# is an irreversible silent no-op, so it is refused at the door.
		self.assertIn("cint(bill.docstatus) == 2", self.body)
		self.assertIn("A cancelled bill cannot be linked to an import", self.body)

	def test_all_four_refs_must_be_empty(self):
		# GATE 4 — this is what keeps automation-created bills locked. The
		# import-expense automation, the truck-transport automation, the
		# CI->PInv conversion and the rebook path each stamp a ref as their own
		# bookkeeping; overwriting one detaches the bill from the document that
		# created it. Iterating _bill_import_refs (all four, including
		# custom_import_expense) rather than only the three settable ones is
		# the point: an expense bill is refused precisely because its ref is
		# not one a human may set.
		# Asserted as the whole loop header: iterating a SLICE of the four would
		# still contain the call, and the ref that would drop off the end is
		# custom_import_expense — the automation-owned one.
		# Pinned as one contiguous block, loop + condition + throw: asserting the
		# loop header alone leaves the gate neuterable (`if False:`) with the
		# test still green — measured, this assertion is what turns that red.
		self.assertIn(
			"for col, value in _bill_import_refs(purchase_invoice).items():\n"
			"\t\tif value:\n"
			"\t\t\tfrappe.throw(",
			self.body,
		)
		refs_body = body(read(IMPORTS), "_bill_import_refs")
		self.assertIn("rules.PI_REF_COLUMNS", refs_body)

	def test_ref_check_covers_a_column_absent_on_this_site(self):
		# _existing_pi_ref_columns only returns columns that exist. A missing
		# column must read as EMPTY, not vanish from the dict — otherwise gate
		# 4 iterates fewer keys and the KeyError surfaces as a crash instead of
		# a refusal.
		refs_body = body(read(IMPORTS), "_bill_import_refs")
		self.assertIn('(values.get(col) or "")', refs_body)

	def test_supplier_group_gate_is_applied(self):
		self.assertIn("_assert_hand_linkable_supplier(company, bill.supplier)", self.body)

	def test_same_supplier_as_the_ci_is_refused(self):
		# GATE 6 — freight billed by the seller is CIF: already inside the
		# agreed goods price. Linking it counts that cost twice, and it also
		# collides with the supplier-scoped reads that decide which Purchase
		# Invoice is THE goods invoice of the CI (one of which CANCELS the
		# invoice it picks).
		self.assertIn("_assert_not_ci_supplier(", self.body)
		self.assertIn("_ci_supplier_behind(targets)", self.body)

	def test_targets_are_company_scoped_and_readable(self):
		# A container name from another tenant is a perfectly valid name. The
		# company equality is what stops it being attached to this tenant's
		# payable; _assert_can_read is the row-level half of the same idea.
		self.assertIn("_company_of(doctype, value) != company", self.body)
		self.assertIn("_assert_can_read(doctype, value)", self.body)

	def test_write_does_not_go_through_doc_save(self):
		# doc.save() re-runs full Purchase Invoice validation over a draft the
		# user is still editing: it can fail on unrelated grounds or silently
		# recompute amounts. Setting a traceability Link touches no money field
		# and must not risk either.
		self.assertIn("frappe.db.set_value(", self.body)
		self.assertNotIn(".save(", code(read(IMPORTS), "set_bill_import_refs"))

	def test_endpoint_returns_no_monetary_amount(self):
		# Attribution only. This endpoint is reachable without cost visibility
		# (the refs themselves are permlevel 0), so its response must not become
		# a side channel for the cost figures the module masks elsewhere.
		returned = self.body[self.body.rindex("\treturn {") :]
		for money in ("grand_total", "outstanding_amount", "amount"):
			self.assertNotIn(money, returned)


class SameSupplierGuardTest(unittest.TestCase):
	"""The CIF guard must not be bypassable by linking the container instead."""

	def test_ci_is_resolved_through_container_and_truck(self):
		# A container or a truck implies its CI just as directly as the CI ref
		# does. If the guard only looked at the CI argument, the identical
		# double-count would be reachable by picking the container.
		#
		# The resolution moved into _ci_behind when W3 needed the CI itself (to
		# find the containers a bill is split over) and not only its supplier.
		src = body(read(IMPORTS), "_ci_behind")
		self.assertIn('frappe.db.get_value("Import Container"', src)
		self.assertIn('frappe.db.get_value("Import Truck"', src)
		self.assertIn('"commercial_invoice"', src)
		self.assertIn("_ci_behind(refs)", body(read(IMPORTS), "_ci_supplier_behind"))

	def test_guard_compares_against_the_ci_supplier(self):
		src = body(read(IMPORTS), "_assert_not_ci_supplier")
		self.assertIn("supplier == ci_supplier", src)
		self.assertIn("frappe.throw(", src)

	def test_unresolvable_ci_does_not_silently_pass_as_a_match(self):
		# No CI behind the targets => nothing to double-count against. The
		# guard must skip, not throw: refusing here would block linking a bill
		# to a bare container that carries no CI yet.
		src = body(read(IMPORTS), "_assert_not_ci_supplier")
		self.assertIn("if ci_supplier and supplier == ci_supplier:", src)


class SupplierGroupGateTest(unittest.TestCase):
	"""Unset configuration must mean OFF, never 'anything goes'."""

	def setUp(self):
		self.body = body(read(IMPORTS), "_assert_hand_linkable_supplier")

	def test_empty_group_list_refuses(self):
		# This predicate is the only thing between the import cost picture and
		# an arbitrary payable. The sibling ci_supplier_groups reader treats an
		# empty list as "no restriction"; copying that polarity here would let
		# any supplier's bill be attributed to an import on every tenant that
		# has not configured the field — which is all of them at go-live.
		# The throw must be the FIRST statement under `if not groups:`. Asserting
		# only that both strings appear would accept an early `return` with the
		# refusal stranded further down — which is exactly the "unset means no
		# restriction" polarity this test exists to forbid.
		self.assertRegex(self.body, r"if not groups:\n\t\tfrappe\.throw\(")

	def test_membership_is_required(self):
		self.assertIn("supplier_group not in groups", self.body)

	def test_groups_come_from_company_config_not_a_constant(self):
		# C3: tenant variance lives in config. A literal group name here would
		# ship one tenant's vocabulary to the other six.
		self.assertIn("imports_transport_supplier_groups_for(company)", self.body)


class ClearBillImportRefsTest(unittest.TestCase):
	"""The unlink path may only undo what the link path could have done."""

	def setUp(self):
		self.body = body(read(IMPORTS), "clear_bill_import_refs")

	def test_module_and_write_gates_come_first(self):
		gate = self.body.index("_assert_imports_access(company)")
		self.assertLess(gate, self.body.index("_assert_can_write("))
		self.assertLess(gate, self.body.index("frappe.db.set_value("))

	def test_expense_owned_bill_cannot_be_unlinked(self):
		# A non-empty custom_import_expense means the Import Expense automation
		# raised this bill. Clearing it would orphan the expense's own record of
		# which invoice settles it.
		self.assertIn('refs["custom_import_expense"]', self.body)

	def test_goods_invoice_cannot_be_unlinked(self):
		# Supplier == the CI's supplier means this is the goods invoice, owned
		# by the conversion that created it — not a hand-link.
		self.assertIn("ci_supplier and supplier == ci_supplier", self.body)

	def test_vouchered_cost_refuses_and_names_the_voucher(self):
		# Once the cost is inside a Landed Cost Voucher, unlinking strands a
		# capitalized amount whose source bill is no longer attributable to the
		# import. Naming the LCV is what makes the refusal actionable — mirrors
		# the toggle_cost_line_include refusal.
		self.assertIn("lcv_ref", self.body)
		self.assertIn("already vouchered", self.body)
		self.assertIn('vouchered[0]["lcv_ref"]', self.body)

	def test_voucher_check_is_guarded_by_has_column(self):
		# Container Cost Line has no purchase_invoice column today; that link is
		# a later work package. Querying it unguarded would make EVERY unlink
		# fail with a SQL error on all seven sites. The guard must wrap the
		# query, so the check switches itself on the day the column lands.
		self.assertIn('has_column("Container Cost Line", "purchase_invoice")', self.body)
		guard = self.body.index('has_column("Container Cost Line", "purchase_invoice")')
		self.assertLess(guard, self.body.index("SELECT cl.lcv_ref"))

	def test_a_bill_an_automation_still_points_at_cannot_be_unlinked(self):
		# The two refusals above both PASS for a tier-3 automation transport
		# bill: it consumes no expense (so custom_import_expense is empty) and
		# its supplier is the carrier, not the CI's. One click would then clear
		# the refs of a bill that Import Truck.transport_purchase_invoice still
		# points at — an orphan the truck can no longer explain. Ownership is the
		# back-pointer, so that is what is asked, not the ref columns.
		self.assertIn("_automation_owner_of_bill(purchase_invoice)", self.body)
		self.assertIn("if owned_by:\n\t\tfrappe.throw(", self.body)
		# And the gate runs before anything is written.
		self.assertLess(
			self.body.index("_automation_owner_of_bill("),
			self.body.index("frappe.db.set_value("),
		)

	def test_only_the_three_hand_linkable_refs_are_cleared(self):
		# custom_import_expense must never be nulled here: the bill carrying one
		# is already refused above, and listing it would make a future edit to
		# that refusal silently destructive.
		write = self.body[self.body.index("frappe.db.set_value(") :]
		self.assertIn("_HAND_LINKABLE_REFS", write)
		self.assertNotIn('"custom_import_expense"', write)


class AutomationOwnershipTest(unittest.TestCase):
	"""Who owns a bill is decided by the back-pointer, not by a ref column."""

	def setUp(self):
		self.src = read(IMPORTS)
		self.body = body(self.src, "_automation_owner_of_bill")

	def test_both_back_pointer_fields_are_consulted(self):
		# Measured across the doctype tree, these two are the whole set of
		# Link-to-Purchase-Invoice fields in the imports module. Dropping either
		# re-opens the orphan: the truck one is the tier-3 case that has no
		# expense ref to give it away.
		self.assertIn('("Import Truck", "transport_purchase_invoice")', self.src)
		self.assertIn('("Import Expense", "purchase_invoice")', self.src)
		self.assertIn("for doctype, back_ref in _AUTOMATION_BACK_REFS:", self.body)

	def test_the_query_is_by_back_pointer_not_by_name(self):
		# The question is "does any automation document point AT this bill", so
		# the filter is on the back-ref column with the bill as its value.
		self.assertIn('frappe.db.get_value(doctype, {back_ref: purchase_invoice}, "name")', self.body)

	def test_no_owner_returns_none_rather_than_refusing(self):
		# A hand-made bill has no owner and must stay unlinkable.
		self.assertIn("return None", self.body)


class LinkWritesDoNotBumpModifiedTest(unittest.TestCase):
	"""Both ref writes must leave `modified` alone — it is the form's save token."""

	def test_neither_write_touches_the_concurrency_timestamp(self):
		# These ref columns are not part of what the Purchase Invoice form
		# submits, but `modified` IS: purchasing.update_purchase_invoice passes
		# it to check_concurrency before loading the doc. Bumping it under an
		# open draft turns the user's next Save into a concurrency failure whose
		# only offered exit is Reload — discarding whatever was typed into a
		# money document. Asserted on both paths, since either one can run while
		# the same draft is open on screen.
		for fn in ("set_bill_import_refs", "clear_bill_import_refs"):
			with self.subTest(fn=fn):
				src = code(read(IMPORTS), fn)
				self.assertIn("update_modified=False", src)
				self.assertNotIn("update_modified=True", src)


class HandLinkedCarrierBillIsNotGoodsTest(unittest.TestCase):
	"""B1 — an attributed carrier bill must not be counted as goods."""

	def setUp(self):
		self.src = read(IMPORTS)

	def test_the_category_is_driven_by_the_configured_transport_groups(self):
		# A hand-linked carrier bill carries no truck ref, no expense ref and
		# ordinary item codes, so it fell through to "product": freight summed
		# into accounting.billed_goods, shrinking the gap, and dropped from the
		# carriers' billed total — the exact figure this feature exists to feed.
		# The flag comes from the SAME configured groups that authorize the link,
		# so nothing is bucketed as transport that could not have been linked as
		# transport (C3: config, never a tenant constant).
		enrich = body(self.src, "_enrich_bill_rows")
		self.assertIn('transport_supplier=r.get("supplier") in carriers', enrich)
		groups = body(self.src, "_transport_group_suppliers")
		self.assertIn("imports_transport_supplier_groups_for(company)", groups)

	def test_an_unconfigured_company_is_bucketed_exactly_as_before(self):
		# Empty set => every row arrives with the flag false, so the six tenants
		# that never configure this see byte-identical categories.
		groups = body(self.src, "_transport_group_suppliers")
		self.assertIn("if not company or not names:\n\t\treturn set()", groups)
		self.assertIn("if not groups:\n\t\treturn set()", groups)

	def test_the_lookup_is_one_query_for_the_whole_page(self):
		# Per-row it would be one Supplier read per bill on the CI cost overview.
		groups = body(self.src, "_transport_group_suppliers")
		self.assertIn('"name": ["in", list(names)]', groups)
		self.assertEqual(groups.count("frappe.get_all("), 1)

	def test_both_callers_pass_the_company_through(self):
		# _enrich_bill_rows defaults company to None (=> feature off). A caller
		# that forgets it silently restores the "product" bug for its whole page.
		for caller in ("_related_import_bills", "list_landed_cost_bills"):
			with self.subTest(caller=caller):
				src = body(self.src, caller)
				self.assertRegex(src, r"_enrich_bill_rows\(rows, .+, company\)")


class UnlinkedTransportBillsTest(unittest.TestCase):
	"""The candidate panel must not offer a row the write path would refuse."""

	def setUp(self):
		self.body = body(read(IMPORTS), "unlinked_transport_bills")

	def test_cost_visibility_is_asserted_before_any_amount_is_returned(self):
		# The panel reports grand_total and outstanding_amount. Cost figures in
		# this module are permission-masked (K3); without this gate the picker
		# becomes the one place a user without cost visibility reads them.
		self.assertIn("_assert_cost_visible()", self.body)
		self.assertLess(self.body.index("_assert_cost_visible()"), self.body.index("frappe.db.sql("))

	def test_module_gate_precedes_the_cost_gate(self):
		self.assertLess(
			self.body.index("_assert_imports_access(ci.company)"),
			self.body.index("_assert_cost_visible()"),
		)

	def test_every_ref_column_must_be_empty(self):
		# A bill already linked to ANOTHER Commercial Invoice must never appear
		# here: offering it invites a user to try, and the attempt is refused by
		# gate 4 with an error they cannot act on.
		self.assertIn("for col in _existing_pi_ref_columns():", self.body)
		self.assertIn("IS NULL OR pi.{col} = ''", self.body)

	def test_ci_supplier_is_excluded(self):
		self.assertIn("pi.supplier != %(ci_supplier)s", self.body)

	def test_supplier_group_filter_mirrors_the_write_gate(self):
		self.assertIn("s.supplier_group IN %(groups)s", self.body)
		self.assertIn("imports_transport_supplier_groups_for(ci.company)", self.body)

	def test_unconfigured_company_gets_no_candidates(self):
		# Same polarity as the write gate: unset => the feature is off, so the
		# panel is empty rather than listing every payable in the company.
		self.assertIn("if not groups:", self.body)
		self.assertIn('"configured": False', self.body)

	def test_truncation_is_reported_not_silent(self):
		# A capped list that looks complete is how a bill goes missing: the user
		# concludes it was never entered and enters it twice. Fetching cap+1 is
		# what makes the truncation detectable at all.
		self.assertIn("_UNLINKED_BILL_LIMIT + 1", self.body)
		self.assertIn("capped = len(rows) > _UNLINKED_BILL_LIMIT", self.body)
		self.assertIn('"capped": capped', self.body)

	def test_the_panel_offers_only_what_the_write_path_accepts(self):
		# The panel's own contract is "every gate that can be expressed as a
		# filter is one here". The two surfaces have to move together or the
		# picker lists a row whose click the write path refuses — the one failure
		# mode the docstring promises cannot happen. It has already happened once
		# in the other direction (panel `< 2` against a draft-only write gate),
		# which is why both halves are pinned in one test rather than two.
		self.assertIn("pi.docstatus < 2", self.body)
		self.assertNotIn("pi.docstatus = 0", self.body)
		self.assertIn("cint(bill.docstatus) == 2", body(read(IMPORTS), "set_bill_import_refs"))
		self.assertNotIn("cint(bill.docstatus) != 0", body(read(IMPORTS), "set_bill_import_refs"))

	def test_unlink_stays_open_after_submission(self):
		# Deliberate asymmetry, pinned so it cannot be "tidied" into symmetry:
		# linking creates an attribution, unlinking corrects a wrong one. A
		# docstatus gate here would freeze a mis-attributed bill on submission
		# with no way out. Money is protected by the voucher check instead.
		self.assertNotIn("docstatus", code(read(IMPORTS), "clear_bill_import_refs"))


class TransportSupplierGroupsSettingTest(unittest.TestCase):
	"""B1 — the per-company setting the whole feature keys off."""

	def setUp(self):
		self.body = body(read(SETTINGS), "imports_transport_supplier_groups_for")

	def test_reader_returns_empty_when_the_table_is_not_migrated(self):
		# This ships as a new child-table FIELD. Between the code landing and
		# `bench migrate` running on a site, reading it raises. Returning [] —
		# which every caller reads as "feature off" — keeps that window safe;
		# letting the exception escape would break the CI form for the tenants
		# that do not use the feature at all.
		# `return []` must be the handler's OWN body. The function has other
		# `return []` statements further down, so asserting one merely exists
		# somewhere after the except would still pass for a bare `raise`.
		self.assertRegex(self.body, r"except Exception:\n(?:\t\t#[^\n]*\n)*\t\treturn \[\]")

	def test_empty_company_short_circuits(self):
		self.assertIn("if not company:", self.body)

	def test_row_is_matched_per_company(self):
		# The field lives on the CHILD table, not on the Stabler Settings
		# Single: a Single field would give every company on a multi-company
		# site one shared list, so one tenant's transporters would authorize
		# another's bills.
		self.assertIn("candidate.company == company", self.body)
		self.assertIn("imports_transport_supplier_groups", self.body)

	def test_json_list_and_newlines_are_both_accepted(self):
		# Mirrors the sibling reader: an admin who pastes a JSON list must not
		# silently configure a single group whose name is '["Transport",'.
		self.assertIn('raw.startswith("[")', self.body)
		self.assertIn("json.loads(raw)", self.body)
		self.assertIn("raw.splitlines()", self.body)

	def test_no_default_group_list_anywhere(self):
		# Unset must mean OFF. A seeded default would authorize hand-linking on
		# all seven tenants the moment this deploys.
		self.assertNotIn("=  [", self.body)
		self.assertNotRegex(self.body, r"return \[['\"]")

	def test_field_exists_on_the_child_doctype(self):
		raw = read(SETTINGS_JSON)
		self.assertIn('"fieldname": "imports_transport_supplier_groups"', raw)
		self.assertIn('"istable": 1', raw)


class CapitalizationTest(unittest.TestCase):
	"""W3 — a linked bill reaches stock valuation, and only once.

	Until W3 this class asserted the opposite: linking was attribution only, and
	the whole landed-cost vocabulary was forbidden in the link path. That was the
	right shape while the two halves were unconnected, and the owner has since
	decided the carrier's invoice IS the cost. What the old tests were really
	protecting — the same freight reaching valuation twice, once hand-typed and
	once billed — is now protected by ``supersede_billed`` instead of by a wall,
	so the guards below are about the supersede being wired in everywhere the cost
	is computed, not about keeping the two sides apart.
	"""

	def setUp(self):
		self.src = read(IMPORTS)

	def test_the_bill_never_writes_a_cost_the_user_may_not_see(self):
		# C4: every cost figure in this module is permission-masked, and linking
		# now AUTHORS one. Without this the masking is a display convention that
		# any user can write around through the picker.
		src = body(self.src, "set_bill_import_refs")
		self.assertIn("_assert_cost_visible()", src)

	def test_the_permission_and_currency_gates_run_before_the_write(self):
		# A gate that fires after the ref write leaves the bill linked but never
		# costed — the one state no screen in this feature can explain.
		src = body(self.src, "set_bill_import_refs")
		write = src.index('frappe.db.set_value("Purchase Invoice", purchase_invoice, updates')
		self.assertLess(src.index("_assert_cost_visible()"), write)
		self.assertLess(src.index("_assert_capitalizable_currency("), write)

	def test_a_currency_the_valuation_cannot_convert_is_refused_not_guessed(self):
		# lcv_math.line_company_amount now resolves each currency against a
		# passed-in rates map. If a EUR bill lacks a EUR rate entry, it is
		# safely excluded with a warning, but this gate still refuses it upfront.
		src = body(self.src, "_assert_capitalizable_currency")
		self.assertIn('currency not in (company_currency, "USD")', src)
		self.assertIn("frappe.throw(", src)

	def test_only_the_net_total_is_capitalized(self):
		# VAT on a carrier's bill is a recoverable input credit and is excluded
		# from the landed cost everywhere else; capitalizing the gross would
		# inflate the cost of goods by the VAT rate.
		src = code(self.src, "_capitalize_linked_bill")
		self.assertIn('flt(bill.get("net_total"))', src)
		self.assertNotIn("grand_total", src)

	def test_the_component_comes_from_the_one_classifier(self):
		# A second opinion about what a bill is would let the cost book and the
		# bill list disagree about the same invoice.
		src = body(self.src, "_capitalize_linked_bill")
		self.assertIn("rules.bill_cost_component(", src)
		self.assertIn("rules.derive_bill_category(", src)
		# None means "this bill has no business in the valuation" — a fallback
		# component here would capitalize the goods invoice itself.
		self.assertIn("if not component:", src)
		self.assertIn("return [], []", src)

	def test_a_cost_already_vouchered_by_hand_is_not_capitalized_again(self):
		# stabler-wen: once an operator's estimate has been consumed by an LCV it
		# carries an lcv_ref, so supersede_billed can no longer drop it at build
		# time. Writing the bill's line anyway puts the same money into stock
		# valuation a second time. The link still goes through — refusing it would
		# cost the attribution too — but the second cost line must not be written,
		# and the skip must be visible instead of silent.
		src = body(self.src, "_capitalize_linked_bill")
		self.assertIn("lcv_math.vouchered_hand_line(", src)
		self.assertIn("warnings.append(", src)
		self.assertIn("return row_names, warnings", src)
		# The response has to carry them out: a warning the caller cannot read is
		# the same silence the defect had.
		self.assertIn('"warnings": warnings', body(self.src, "set_bill_import_refs"))

	def test_a_ci_level_bill_is_split_across_containers_by_weight(self):
		src = body(self.src, "_capitalize_linked_bill")
		# Both figures, named individually: pinning only "allocate_by_weight
		# appears" let a mutation split the base amount by weight and hand every
		# container the FULL transaction amount, which multiplies the bill by the
		# container count in exactly the currency the LCV reads.
		self.assertIn("parts = rules.allocate_by_weight(amount, containers)", src)
		self.assertIn(
			'base_parts = rules.allocate_by_weight(flt(bill.get("base_net_total")), containers)', src
		)
		resolver = body(self.src, "_containers_behind_refs")
		self.assertIn("_ci_behind(refs)", resolver)
		self.assertIn('"total_kg"', resolver)

	def test_unlinking_removes_exactly_what_linking_wrote(self):
		# A link that can be undone while its cost stays behind is how the same
		# freight ends up capitalized twice: unlink, re-link, two cost lines.
		src = body(self.src, "clear_bill_import_refs")
		self.assertIn('frappe.db.delete("Container Cost Line", {"purchase_invoice": purchase_invoice})', src)

	def test_the_vouchered_guard_still_precedes_the_delete(self):
		# Once a Landed Cost Voucher consumed the line the money is in stock
		# valuation; deleting the row would leave the valuation with no source.
		src = body(self.src, "clear_bill_import_refs")
		self.assertLess(
			src.index("already vouchered"),
			src.index('frappe.db.delete("Container Cost Line"'),
		)

	def test_the_hand_typed_line_is_superseded_wherever_the_cost_is_computed(self):
		# The preview is where the accountant decides. A preview that still shows
		# a line the voucher will drop is a preview of a document that does not
		# exist, and the two screens would disagree about the same import.
		self.assertIn("lcv_math.supersede_billed(", read(HOOKS))
		self.assertIn("lcv_math.supersede_billed(", body(self.src, "get_landed_cost_review"))

	def test_the_supersede_warnings_survive_a_gtd(self):
		# `components, warnings = apply_gtd_customs_precedence(...)` would REBIND
		# warnings and throw away every supersede message on any import that has
		# a cleared GTD — which is most of them.
		src = body(self.src, "get_landed_cost_review")
		self.assertIn("warnings.extend(gtd_warnings)", src)

	def test_the_two_server_owned_markers_survive_a_container_save(self):
		# The SPA sends cost lines back as a flat list with neither marker on
		# them. Losing lcv_ref re-vouchers a consumed line; losing
		# purchase_invoice detaches the bill and lets the hand-typed figure be
		# capitalized beside it — the double count this feature exists to stop.
		src = body(self.src, "_apply_container_payload")
		self.assertIn("existing_refs", src)
		self.assertIn('cl.get("purchase_invoice")', src)
		self.assertIn("line.purchase_invoice = purchase_invoice", src)

	def test_two_identical_lines_keep_their_own_links(self):
		# Keyed by (component, amount), two rows that share both would collapse
		# onto one link and one of the two bills would be silently freed.
		src = body(self.src, "_apply_container_payload")
		self.assertIn(".append(", src)
		self.assertIn(".pop(0)", src)

	def test_the_client_can_never_claim_a_line_is_billed_or_vouchered(self):
		src = body(self.src, "_clean_container_cost_lines")
		self.assertNotIn('"purchase_invoice"', src)
		self.assertNotIn('"lcv_ref"', src)

	def test_the_column_exists_on_the_child_doctype(self):
		raw = read(COST_LINE_JSON)
		self.assertIn('"fieldname": "purchase_invoice"', raw)
		# read_only, because the only legitimate author is the guarded endpoint.
		self.assertRegex(raw, r'"fieldname": "purchase_invoice",[\s\S]{0,200}?"read_only": 1')


if __name__ == "__main__":
	unittest.main()
