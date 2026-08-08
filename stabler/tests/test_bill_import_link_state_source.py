"""Guards for the PI-form picker's read endpoint, ``bill_import_link_state`` (W1).

The endpoint exists so the picker never offers an action the write path would
then refuse: it mirrors every non-target-dependent gate of
``set_bill_import_refs``/``clear_bill_import_refs`` and returns a verdict
instead of letting the UI guess. Two properties are the whole point of a
*read* endpoint sitting in front of a *write* one, and each fails differently
if dropped:

* it must never throw for a reason the write path also refuses on — a form
  that ships to every tenant (imports on or off) cannot surface a console
  error just because a company hasn't turned the module on;
* it must never leak an amount — the endpoint is reachable without cost
  visibility, so it must not become the one place that visibility is masked.

Frappe-free: these assert structural properties of the source, so a refactor
that quietly drops a guard fails CI rather than production.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_bill_import_link_state_source -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
IMPORTS = os.path.join(_ROOT, "api", "imports.py")


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

	The docstring documents what the function promises (including the words
	"no monetary amount"), so a prose mention would otherwise fail the test
	that forbids an actual money field in the code.
	"""
	text = body(src, name)
	m = re.search(r'"""', text)
	if not m:
		return text
	end = text.index('"""', m.end())
	return text[end + 3 :]


class BillImportLinkStateGateOrderTest(unittest.TestCase):
	"""The gates of bill_import_link_state, and the order they must run in."""

	def setUp(self):
		self.body = body(read(IMPORTS), "bill_import_link_state")

	def test_unknown_bill_is_the_only_hard_error(self):
		# Every other outcome is a returned verdict, not an exception — a form
		# that loads for every tenant cannot crash on a company where imports
		# is simply off. The unknown-name check must be the FIRST statement
		# after the docstring, ahead of every other gate.
		after_docstring = code(read(IMPORTS), "bill_import_link_state")
		self.assertRegex(
			after_docstring,
			r"^\n\tif not purchase_invoice or not frappe\.db\.exists\(\"Purchase Invoice\", purchase_invoice\):\n"
			r"\t\tfrappe\.throw\(",
		)

	def test_read_permission_is_checked_before_any_gate(self):
		# This is a READ endpoint (unlike the write path, no _assert_can_write):
		# it is reachable by anyone who may view the bill, not just edit it. But
		# it must still not disclose the ineligibility reason (which can name a
		# supplier group or another linked document) to someone who cannot read
		# the bill at all.
		gate = self.body.index('_assert_can_read("Purchase Invoice", purchase_invoice)')
		for later in (
			"module_map_for(company)",
			"cint(bill.docstatus)",
			"imports_transport_supplier_groups_for(",
			"rules.PI_REF_COLUMNS",
		):
			self.assertLess(gate, self.body.index(later), f"{later} runs before the read-permission gate")

	def test_module_off_is_silent_and_never_throws(self):
		# The Purchase Invoice form ships to every tenant, imports on or off.
		# An exception here would be a console error on every bill of every
		# non-imports company. Must return, not raise.
		self.assertIn('if not module_map_for(company).get("imports")', self.body)
		branch = self.body[self.body.index('if not module_map_for(company).get("imports")') :]
		branch = branch[: branch.index("return {") + len("return {")]
		self.assertNotIn("frappe.throw", branch)

	def test_a_user_without_an_imports_role_is_treated_as_module_off(self):
		# The write path calls _assert_imports_access, whose role half this
		# mirrors. Without it a purchasing-only user is shown the picker and the
		# Link click throws. It is mirrored rather than called because that
		# helper RAISES, and this endpoint must stay silent on the tenants that
		# have no imports at all — so the two halves share one silent branch.
		self.assertIn("_ADMIN_ROLES", self.body)
		self.assertIn("_IMPORTS_ROLES", self.body)
		self.assertIn("or not has_imports_role:", self.body)
		self.assertNotIn("_assert_imports_access(", self.body)

	def test_module_off_reports_no_reason_and_empty_refs(self):
		# Silent ineligibility: a reason string here would tell a user on a
		# non-imports tenant that a feature they cannot see is "not configured"
		# — a hint about functionality that does not exist for them.
		off = self.body[
			self.body.index('if not module_map_for(company).get("imports")') : self.body.index(
				"refs = _bill_import_refs(purchase_invoice)"
			)
		]
		self.assertIn('"reason": "",', off)
		self.assertIn('dict.fromkeys(rules.PI_REF_COLUMNS, "")', off)
		self.assertIn('"linked": False,', off)
		self.assertIn('"can_unlink": False,', off)

	def test_linked_is_computed_from_the_three_hand_linkable_refs_only(self):
		# custom_import_expense must NOT make "linked" true here: an
		# automation-owned bill is not a hand-link, and the picker's "linked"
		# summary branch is for undoing a HAND link, not an expense one.
		self.assertIn("linked = any(refs[col] for col, _dt in _HAND_LINKABLE_REFS)", self.body)

	def test_can_unlink_excludes_expense_owned_bills(self):
		# Mirrors clear_bill_import_refs's own refusal: an expense-owned bill
		# is linked (a ref is set) but must not offer an Unlink action that the
		# write path would then refuse.
		self.assertIn('linked and not refs["custom_import_expense"]', self.body)

	def test_can_unlink_excludes_a_bill_an_automation_points_at(self):
		# The second refusal of clear_bill_import_refs. A tier-3 automation
		# transport bill has an EMPTY custom_import_expense, so the rule above
		# does not cover it: without this the picker shows an Unlink button whose
		# click throws — the one failure mode this endpoint exists to prevent.
		self.assertIn("not _automation_owner_of_bill(purchase_invoice)", self.body)

	def test_only_a_draft_bill_is_eligible(self):
		# Same rule as set_bill_import_refs gate 3, expressed as a verdict
		# instead of a throw — and it must name the bill so a submitted PI's
		# owner understands why the picker will not offer linking.
		self.assertIn("cint(bill.docstatus) != 0", self.body)
		self.assertIn("Only a draft bill can be linked to an import.", self.body)

	def test_unconfigured_transport_groups_is_silent(self):
		# Same polarity as the write gate's _assert_hand_linkable_supplier: an
		# empty configured-groups list means the feature is off for this
		# company, not "every supplier qualifies". Silent — no reason string —
		# because this is invisible functionality, same as the module-off case.
		self.assertRegex(self.body, r'if not groups:\n(?:\t\t#[^\n]*\n)*\t\treturn _not_eligible\(""\)')

	def test_groups_come_from_company_config_not_a_constant(self):
		# C3: tenant variance lives in config, never a literal group name.
		self.assertIn("imports_transport_supplier_groups_for(company)", self.body)

	def test_supplier_not_in_group_is_ineligible_with_a_named_reason(self):
		self.assertIn("supplier_group not in groups", self.body)
		self.assertIn("is not one of the", self.body)

	def test_all_four_ref_columns_are_checked_not_only_the_three_settable_ones(self):
		# The picker must refuse an automation-owned bill (custom_import_expense
		# set) exactly as the write path's gate 4 does. Iterating
		# rules.PI_REF_COLUMNS (all four) rather than _HAND_LINKABLE_REFS
		# (three) is the point: dropping to the three-tuple would make this
		# endpoint call an expense-owned bill "eligible", and the write it then
		# offers would be refused on click.
		self.assertIn("for col in rules.PI_REF_COLUMNS:", self.body)
		loop = self.body[self.body.index("for col in rules.PI_REF_COLUMNS:") :]
		loop = loop[: loop.index("return {")]
		self.assertIn("is already linked to", loop)

	def test_success_result_is_not_a_permanent_linked_state(self):
		# Eligibility is a snapshot, not a write: the final "eligible" return
		# must not claim linked=True or can_unlink=True — those only become
		# true once set_bill_import_refs has actually run.
		success = self.body[self.body.rindex("return {") :]
		self.assertIn('"eligible": True,', success)
		self.assertIn('"linked": False,', success)
		self.assertIn('"can_unlink": False,', success)

	def test_endpoint_returns_no_monetary_amount(self):
		# Attribution only, and this state probe is reachable without cost
		# visibility (unlike unlinked_transport_bills, it asserts no
		# _assert_cost_visible at all) — so it must never become a side
		# channel for the cost figures the module masks elsewhere. Checked
		# against the docstring-stripped body: the docstring itself says
		# "no monetary amount" in prose, which must not trip this check.
		region = code(read(IMPORTS), "bill_import_link_state")
		for money in ("grand_total", "outstanding_amount", "amount"):
			self.assertNotIn(money, region)

	def test_docstring_states_the_never_throws_contract(self):
		# Pin the promise in prose too: a reviewer changing this function reads
		# the docstring before the gates, and the contract belongs there.
		self.assertIn("Never throws when the imports module is off", self.body)


if __name__ == "__main__":
	unittest.main()
