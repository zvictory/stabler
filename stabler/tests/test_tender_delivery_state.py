"""One rule decides whether a contract has been delivered, and the server owns it.

Prompt 18's acceptance row C17: `status` is the server's classification, not the
client's. Measured 2026-09-02: `SalesOrderBoard.vue:95` computed

    status: Number(card.per_delivered) >= 100 ? "delivered" : "delivery_pending"

on the client and fed it to `filterTenderRows`. The rule was not WRONG — the
director dashboard already applied the identical `flt(so.per_delivered) >= 100`
in `api/tender.py` — which is the whole problem: two copies of one rule, in two
languages, with nothing holding them together. This is the same defect commit
`26481f1` removed from the customs queue one screen earlier; here it survived.

The rule now lives once, in `_funnel.py`, where the module already keeps its pure
classifications (`classify`, `bucket_so`). Frappe-free on purpose: it takes a
number and returns a word, so it needs no database and this module runs under
`make test`. That `so_board`'s payload really carries it through a live query is
`make test-bench` territory and is NOT claimed here.
"""

import ast
import os
import re
import unittest

from stabler.api import _funnel

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api", "tender.py")
BOARD = os.path.join(HERE, "..", "public", "js", "pages", "sales", "SalesOrderBoard.vue")


def _body(src: str, name: str) -> str:
	"""Source of one top-level function, from its `def` to the next top-level one."""
	m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
	assert m, f"{name} not found in api/tender.py"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestTheRuleItself(unittest.TestCase):
	def test_a_fully_delivered_order_is_delivered(self):
		# WHAT WOULD MAKE THIS FAIL: moving the boundary. 100 % delivered means
		# delivered; anything else is still owed to the customer. The threshold
		# is the one the director dashboard has always counted by, so changing
		# it here changes what the dashboard's own execution figures mean.
		self.assertEqual(_funnel.delivery_state(100), "delivered")
		self.assertEqual(_funnel.delivery_state(100.0), "delivered")
		self.assertEqual(_funnel.delivery_state(140), "delivered")

	def test_anything_short_of_the_whole_order_is_pending(self):
		# WHAT WOULD MAKE THIS FAIL: `>= 99` or a rounding step. 99.6 % delivered
		# is a line still outstanding — rounding it up would report a contract as
		# finished while the customer is still waiting for part of it.
		for value in (0, 1, 99, 99.6, 99.99):
			with self.subTest(value=value):
				self.assertEqual(_funnel.delivery_state(value), "delivery_pending")

	def test_a_missing_figure_is_pending_rather_than_an_error(self):
		# WHAT WOULD MAKE THIS FAIL: letting None through to a comparison. A
		# Sales Order row with no `per_delivered` is an order nothing has been
		# delivered against — the honest answer is "pending", and a TypeError
		# here would take the whole board down with it.
		for value in (None, "", "abc"):
			with self.subTest(value=value):
				self.assertEqual(_funnel.delivery_state(value), "delivery_pending")

	def test_the_words_are_the_ones_the_module_already_filters_by(self):
		# WHAT WOULD MAKE THIS FAIL: renaming the outputs. `delivered` and
		# `delivery_pending` are the module's shared vocabulary — the dashboard
		# counts under those keys and `tenderBoardFilters.js` matches `row.status`
		# against them, so a rename silently empties the filter instead of
		# breaking it.
		self.assertEqual(
			{_funnel.delivery_state(100), _funnel.delivery_state(0)}, {"delivered", "delivery_pending"}
		)


class TestOnlyOneCopyOfIt(unittest.TestCase):
	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.api = fh.read()

	def test_the_board_payload_carries_the_classification(self):
		# WHAT WOULD MAKE THIS FAIL: shipping the helper and leaving the payload
		# on ERPNext's own `status` string. The board's filter matches
		# `delivered`/`delivery_pending`; "To Deliver and Bill" matches neither,
		# so the filter would quietly return nothing at all.
		board = _body(self.api, "so_board")
		self.assertTrue(
			re.search(r'"status": _funnel\.delivery_state\(so\.per_delivered\)', board),
			"so_board must classify the order rather than forward ERPNext's status",
		)

	def test_the_dashboard_counts_by_the_same_helper(self):
		# WHAT WOULD MAKE THIS FAIL: the dashboard keeping its own inline
		# comparison. Two copies is what C17 is about, and leaving the older one
		# in place would mean the board and the director's execution figures can
		# disagree about the same order — the harder half of the bug to see,
		# because each screen is self-consistent.
		self.assertFalse(
			re.search(r"flt\(so\.per_delivered\) >= 100", self.api),
			"the dashboard still re-derives the delivery state inline",
		)
		self.assertIn("_funnel.delivery_state(so.per_delivered)", self.api)

	def test_every_function_that_calls_the_helper_can_actually_see_it(self):
		# WHAT WOULD MAKE THIS FAIL: calling `_funnel.x` from a function that
		# does not import it — a NameError at request time, on a line that reads
		# perfectly.
		#
		# This test exists because that is exactly what happened. `tender.py`
		# imports `_funnel` LOCALLY, inside four separate functions, and has no
		# module-level import at all; the first version of this change added
		# calls in two more functions and every source-text assertion above it
		# stayed green while both endpoints were broken. A regex cannot see
		# scope. The AST can.
		tree = ast.parse(self.api)

		def sees_funnel(node):
			return any(
				(isinstance(n, ast.ImportFrom) and any(a.name == "_funnel" for a in n.names))
				or (isinstance(n, ast.Import) and any("_funnel" in a.name for a in n.names))
				for n in ast.walk(node)
			)

		module_level = sees_funnel(
			ast.Module(
				body=[
					n
					for n in tree.body
					if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
				],
				type_ignores=[],
			)
		)
		blind = []
		for fn in tree.body:
			if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			uses = any(
				isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "_funnel"
				for n in ast.walk(fn)
			)
			if uses and not module_level and not sees_funnel(fn):
				blind.append(f"{fn.name} (line {fn.lineno})")
		self.assertEqual(blind, [], f"these call _funnel without importing it: {blind}")

	def test_the_client_no_longer_re_derives_it(self):
		# WHAT WOULD MAKE THIS FAIL: the ternary coming back to the .vue. A
		# client that recomputes a server fact is a second source of truth that
		# nobody updates when the first one changes — which is exactly how this
		# rule came to exist in two places.
		with open(BOARD, encoding="utf-8") as fh:
			board = fh.read()
		self.assertFalse(
			"per_delivered) >= 100" in board,
			"SalesOrderBoard.vue still classifies the delivery state itself",
		)


if __name__ == "__main__":
	unittest.main()
