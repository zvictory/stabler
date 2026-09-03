"""ADR-606 — ONE predetermined landed-charge list, defined once on the server.

Measured 2026-09-03: two client-side lists existed and did not overlap.
`PoControlBoard.vue` offered eleven lower-case keys (transport, customs,
certification, insurance, storage, declarant, legal, broker, loading, bank,
other) on a Purchase Order's landed line; `LandedChargesEditor.vue` offered six
Title-Case ones (Freight, Customs Duty, Handling & Terminal, Insurance, VAT,
Other) on a Supplier Quotation's estimate. The two screens describe THE SAME
COSTS at two moments — the estimate before the order, the plan after it — so a
plan-vs-actual comparison across them cannot be made at all: "Freight" and
"transport" are the same money under two names, and nothing in the system knows
it. Zafar's decision (ADR-606, §8 karar 3): one list, nine keys, defined on the
server, read by both editors.

Two rules carry the whole risk, and both are pinned here:

  * **Stored data is never rewritten.** The RAW shapes -- `raw_charge_line` /
    `sanitize_charge_lines` for quotations, `tender._raw_landed_lines` for PO
    lines -- keep whatever string a row already carries on disk. A migration
    that rewrote `broker` to `declarant` would be a one-way edit of accounting
    evidence for a rename.
  * **Canonicalisation happens on READ**, in the valued shape, through one alias
    table. In particular a legacy `"charge_type": "VAT"` line must keep being
    excluded from the capitalized landed total (IAS 2 §11) even though VAT is no
    longer a type at all -- it is the `is_recoverable_vat` flag now, and the
    alias forces that flag on so the exclusion survives the rename.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_landed_charge_types -v
"""

from __future__ import annotations

import csv
import importlib
import json
import re
import types
import unittest
from pathlib import Path

from stabler.api._landed import parse_landed_charges, raw_charge_line, sanitize_charge_lines
from stabler.api._landed_charge_types import (
	CHARGE_TYPES,
	canonical_charge_type,
	is_known_charge_type,
	is_vat_charge_type,
	resolve_charge_type,
)
from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

_ROOT = Path(__file__).resolve().parents[1]
_LANGS = ("en", "ru", "uz", "uzc", "tr")


def tearDownModule():
	"""The fakes below are process-wide -- hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _load_tender():
	"""`api.tender` against the handful of Frappe names its landed readers touch.

	Same harness as `test_landed_charge_currency._load_tender`; copied rather
	than imported because a borrowed loader borrows the sandbox too, and only the
	OWNING module's `tearDownModule` runs (see `test_module_sandbox_hygiene`).
	"""
	_SANDBOX.evict(
		"stabler.api.tender",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"stabler.api.approvals",
		"stabler.api._common",
		"stabler.api._bid_package",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user="buyer@example.com")
	frappe.db = types.SimpleNamespace(has_column=lambda *_a, **_k: False)
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.get_roles = lambda _user=None: []
	frappe.has_permission = lambda *_a, **_k: True
	frappe.get_list = lambda *_a, **_k: []
	frappe.get_all = lambda *_a, **_k: []
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.getdate = lambda value: value
	utils.add_months = lambda value, months: value
	utils.cint = lambda value=0: int(float(value or 0))
	utils.today = lambda: "2026-09-03"
	utils.now = lambda: "2026-09-03 09:00:00"
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})
	for name, attrs in (
		("stabler.api.approvals", {"_assert_company_scope": lambda _c: None}),
		("stabler.api._common", {"_require_company": lambda _c: None}),
		(
			"stabler.api._bid_package",
			{
				"assemble_bid_package": lambda *_a, **_k: {},
				"build_bid_docx": lambda *_a, **_k: b"",
			},
		),
		("stabler.api.organization", {"_can_access_module": lambda *_a, **_k: True}),
		("stabler.api.purchasing", {"tender_quotations": lambda _d: {"rows": []}}),
		("stabler.stabler.doctype.stabler_settings.stabler_settings", {"module_map_for": lambda _c: {}}),
	):
		mod = types.ModuleType(name)
		for attr, value in attrs.items():
			setattr(mod, attr, value)
		_SANDBOX.install({name: mod})
	return importlib.import_module("stabler.api.tender")


# The two lists as they stood on 2026-09-03, with the canonical key each one
# means. This table IS the decision: every value that can be on disk today, and
# where it lands. A row removed from the alias table fails here by name.
_PO_BOARD_TYPES = {
	"transport": "transport",
	"customs": "customs",
	"certification": "certification",
	"insurance": "insurance",
	"storage": "storage",
	"declarant": "declarant",
	"legal": "legal",
	"broker": "declarant",  # the declarant IS the broker; two names, one cost
	"loading": "storage",  # loading/unloading is terminal handling
	"bank": "bank",
	"other": "other",
}

_QUOTATION_EDITOR_TYPES = {
	"Freight": "transport",
	"Customs Duty": "customs",
	"Handling & Terminal": "storage",
	"Insurance": "insurance",
	"VAT": "other",  # not a type at all — see TestLegacyVatIsStillExcluded
	"Other": "other",
}


class TestOneListForBothEditors(unittest.TestCase):
	"""The nine keys, in the order the decision names them."""

	def test_the_list_is_the_nine_types_the_council_decided(self):
		# WHAT WOULD MAKE THIS FAIL: a tenth type, a rename, or a reordering.
		# The order is the order the two <select>s render, so it is a UI decision
		# and not an implementation detail.
		self.assertEqual(
			[c["key"] for c in CHARGE_TYPES],
			[
				"transport",
				"customs",
				"declarant",
				"certification",
				"insurance",
				"storage",
				"bank",
				"legal",
				"other",
			],
		)

	def test_vat_is_not_one_of_the_types(self):
		# ADR-606: VAT is the `is_recoverable_vat` FLAG, because a VAT line is not
		# a different kind of cost -- it is a cost that is recoverable, which is
		# what decides whether it capitalizes (IAS 2 §11).
		self.assertNotIn("vat", [c["key"] for c in CHARGE_TYPES])

	def test_every_label_is_english(self):
		# Implementation code is English-first (CLAUDE.md); the SPA translates
		# these through `t()` at render time.
		for entry in CHARGE_TYPES:
			with self.subTest(key=entry["key"]):
				self.assertTrue(entry["label"].strip())
				self.assertTrue(entry["label"].isascii(), entry["label"])


class TestEveryStoredValueLands(unittest.TestCase):
	"""Both old lists, value by value. Nothing may fall off the map."""

	def test_every_po_board_type_maps_to_its_canonical_key(self):
		for stored, expected in _PO_BOARD_TYPES.items():
			with self.subTest(stored=stored):
				self.assertEqual(canonical_charge_type(stored), expected)

	def test_every_quotation_editor_type_maps_to_its_canonical_key(self):
		for stored, expected in _QUOTATION_EDITOR_TYPES.items():
			with self.subTest(stored=stored):
				self.assertEqual(canonical_charge_type(stored), expected)

	def test_matching_is_case_insensitive_and_ignores_padding(self):
		# The two lists disagreed about case ("Freight" vs "transport"), and
		# hand-edited JSON disagrees about whitespace. Neither is a new type.
		# One expected key per input, deliberately: this assertion read
		# `assertIn(..., ("transport", "customs"))` and passed just as happily
		# with "FREIGHT" resolving to customs -- which is the one thing a
		# case-folding test exists to catch.
		cases = {
			"FREIGHT": "transport",
			"freight": "transport",
			"  Freight  ": "transport",
			"Customs DUTY": "customs",
			"\tBROKER\n": "declarant",
		}
		for stored, expected in cases.items():
			with self.subTest(stored=stored):
				self.assertEqual(canonical_charge_type(stored), expected)

	def test_the_servers_own_empty_sentinel_lands_on_other(self):
		# `raw_charge_line` writes "General" when a line names no type at all
		# (_landed.py:57). It is not an unknown string; it is this module's own.
		self.assertEqual(canonical_charge_type("General"), "other")
		self.assertEqual(canonical_charge_type(""), "other")
		self.assertEqual(canonical_charge_type(None), "other")
		# Empty is not a RECOGNISED value, though, and the difference is not
		# academic: write paths gate on `is_known_charge_type`, so answering True
		# for "" let a whitespace-only `type` persist as "" rather than "other".
		# WHAT WOULD MAKE THIS FAIL: putting "" back in the alias table.
		self.assertFalse(is_known_charge_type(""))
		self.assertFalse(is_known_charge_type("   "))
		self.assertTrue(is_known_charge_type("General"))


class TestAnUnknownTypeKeepsItsText(unittest.TestCase):
	"""`other`, plus the words the officer actually wrote."""

	def test_an_unknown_string_lands_on_other_and_is_handed_back(self):
		# WHAT WOULD MAKE THIS FAIL: returning just "other". Quotation lines are
		# free text on disk -- `test_landed_ranking` alone carries "Local
		# Delivery" and "Freight & Customs" -- and a rename that silently drops
		# the officer's own words leaves a line reading "Other" and nothing else.
		self.assertEqual(resolve_charge_type("Local Delivery"), ("other", "Local Delivery"))

	def test_a_known_value_has_nothing_left_over(self):
		# The leftover text is what the editor puts in the description box. It
		# must be empty for a value the table recognises, or every legacy line
		# grows a description saying "Freight".
		self.assertEqual(resolve_charge_type("Freight"), ("transport", ""))
		self.assertEqual(resolve_charge_type("General"), ("other", ""))

	def test_the_valued_shape_carries_both(self):
		_total, clean, _has = parse_landed_charges([{"charge_type": "Local Delivery", "amount": 100.0}])
		self.assertEqual(clean[0]["charge_type"], "Local Delivery")  # as stored
		self.assertEqual(clean[0]["charge_type_canonical"], "other")
		self.assertEqual(clean[0]["charge_type_unmapped"], "Local Delivery")


class TestLegacyVatIsStillExcluded(unittest.TestCase):
	"""IAS 2 §11 survives the rename, or the rename costs money.

	`_landed.py:136` recognised VAT BY NAME. Deleting "VAT" from the type list
	without an alias would have made every stored VAT line an ordinary charge:
	recoverable input tax capitalized into the landed cost of the goods,
	inflating the delivered total of exactly those vendors who broke VAT out as
	its own line, and moving which bid wins the tender.
	"""

	def _total_of(self, charge_type):
		total, clean, _has = parse_landed_charges(
			[{"charge_type": charge_type, "amount": 300.0}, {"charge_type": "Freight", "amount": 1000.0}]
		)
		return total, clean[0]

	def test_a_stored_vat_line_never_enters_the_capitalized_total(self):
		for stored in ("VAT", "vat", "Value Added Tax", "НДС"):
			with self.subTest(stored=stored):
				total, line = self._total_of(stored)
				self.assertEqual(total, 1000.0)
				self.assertEqual(line["capitalized_amount"], 0.0)

	def test_the_alias_forces_the_flag_that_does_the_excluding(self):
		# The exclusion is no longer "the name is VAT" -- it is the flag. The
		# alias sets it, so the line arrives at the editor with the Recoverable
		# VAT checkbox ticked and stays excluded when it is saved back as `other`.
		# WHAT WOULD MAKE THIS FAIL: mapping VAT to `other` without the flag.
		_total, line = self._total_of("VAT")
		self.assertTrue(line["is_recoverable_vat"])
		self.assertEqual(line["charge_type_canonical"], "other")
		self.assertTrue(is_vat_charge_type("VAT"))
		self.assertFalse(is_vat_charge_type("Freight"))

	def test_a_non_vat_line_is_not_flagged_by_accident(self):
		_total, line = self._total_of("Freight")
		self.assertFalse(line["is_recoverable_vat"])

	def test_the_valued_line_says_whether_the_STORED_type_was_vat(self):
		# The editor has to be able to tell "ticked because the officer ticked
		# it" from "ticked because the stored spelling is a VAT alias", and it
		# may not keep an alias table of its own to do it -- one list, on the
		# server, is the whole ADR. So the fact rides on the valued line beside
		# `charge_type_canonical`, and it is the STORED spelling's fact alone:
		# an ordinary line the officer merely ticked is not a VAT line.
		# WHAT WOULD MAKE THIS FAIL: setting it from the merged `is_vat`.
		_total, line = self._total_of("VAT")
		self.assertTrue(line["charge_type_is_vat"])

		_total, plain = parse_landed_charges(
			[{"charge_type": "Freight", "amount": 300.0, "is_recoverable_vat": True}]
		)[:2]
		self.assertTrue(plain[0]["is_recoverable_vat"])
		self.assertFalse(plain[0]["charge_type_is_vat"])

	def test_un_ticking_the_box_actually_lowers_nothing_and_raises_the_total(self):
		# The review's P1, closed on the server's side. The editor answers an
		# un-tick on a legacy VAT line by writing the canonical key into the
		# stored one -- because the server forces the flag back on for any line
		# still SPELLED as VAT, so sending "VAT" with the box cleared is an edit
		# that silently does not happen: the modal shows 1300 while
		# `base_landed_total` stays 1000 and the box is ticked again on reopen.
		# This is that saved shape, read back.
		# WHAT WOULD MAKE THIS FAIL: the editor leaving `charge_type` as "VAT".
		untouched, _clean, _has = parse_landed_charges(
			[
				{"charge_type": "VAT", "amount": 300.0, "is_recoverable_vat": False},
				{"charge_type": "Freight", "amount": 1000.0},
			]
		)
		self.assertEqual(untouched, 1000.0, "a line still spelled VAT is still VAT")

		total, clean, _has = parse_landed_charges(
			[
				{"charge_type": "other", "amount": 300.0, "is_recoverable_vat": False},
				{"charge_type": "Freight", "amount": 1000.0},
			]
		)
		self.assertEqual(total, 1300.0)
		self.assertFalse(clean[0]["is_recoverable_vat"])
		self.assertFalse(clean[0]["charge_type_is_vat"])

	def test_the_valued_line_also_carries_the_flag_AS_STORED(self):
		# `is_recoverable_vat` on a valued line is the MERGED answer, which is
		# what every consumer of the read wants and what the checkbox displays.
		# It is not what the editor may send back: doing so persisted the alias
		# table's verdict into the evidence field on the next save made for an
		# unrelated reason. So the raw flag rides along verbatim, and the editor
		# hands THAT back on a line it did not edit.
		# WHAT WOULD MAKE THIS FAIL: setting it from the merged flag.
		_total, forced = parse_landed_charges([{"charge_type": "VAT", "amount": 300.0}])[:2]
		self.assertTrue(forced[0]["is_recoverable_vat"])
		self.assertFalse(forced[0]["is_recoverable_vat_stored"])

		_total, ticked = parse_landed_charges(
			[{"charge_type": "Freight", "amount": 300.0, "is_recoverable_vat": True}]
		)[:2]
		self.assertTrue(ticked[0]["is_recoverable_vat_stored"])

	def test_the_stored_flag_is_a_derivation_and_never_reaches_the_disk(self):
		# Derived keys are read-only by construction: the write path is
		# `sanitize_charge_lines`, and the RAW shape has no room for them.
		# WHAT WOULD MAKE THIS FAIL: `raw_charge_line` growing the key.
		stored = sanitize_charge_lines([{"charge_type": "VAT", "amount": 300.0}])
		self.assertNotIn("is_recoverable_vat_stored", stored[0])
		self.assertNotIn("charge_type_is_vat", stored[0])
		self.assertNotIn("charge_type_canonical", stored[0])

	def test_the_editors_four_answers_capitalize_what_they_always_did(self):
		# The four shapes the editor can now emit, read back. None of them moves
		# money: the fix is about which flag is persisted, not about what a flag
		# means. Every figure here is the one main produced for the same line.
		# WHAT WOULD MAKE THIS FAIL: any of these totals changing at all.
		for charge_type, flag, expected in (
			("VAT", False, 0.0),  # stored false, un-edited: still VAT by spelling
			("VAT", True, 0.0),
			("Freight", True, 0.0),  # hand-ticked, so excluded
			("other", False, 300.0),  # un-ticked: the type moved, and it counts
			# The fifth shape, and the one the review's P0 was about. It is
			# reachable ONLY through an officer's explicit pick in the <select>,
			# with the box visibly un-ticked as they do it: `onTypeChange`
			# retires the alias fact and puts the flag back to what the disk
			# said. Reached any other way -- a stale `charge_type_is_vat` -- it
			# is 300 capitalizing into a total the officer was shown as 0.
			("transport", False, 300.0),
		):
			with self.subTest(charge_type=charge_type, is_recoverable_vat=flag):
				total, _clean, _has = parse_landed_charges(
					[{"charge_type": charge_type, "amount": 300.0, "is_recoverable_vat": flag}]
				)
				self.assertEqual(total, expected)

	def test_only_the_spellings_that_were_vat_before_are_vat_now(self):
		# The alias table decides whether a stored line capitalizes, so widening
		# it by one plausible-looking string silently restates a company's landed
		# cost. Main matched exactly three spellings (`_landed.py:136`,
		# `charge_type.upper() in ("VAT", "VALUE ADDED TAX", "НДС")`), which
		# makes "Import VAT" an ORDINARY charge there: flagging it here drops its
		# 300.00 out of `base_landed_total` and can change which bid is cheapest.
		# An alias earns its place because the stored data meant VAT, never
		# because the words read like it.
		# WHAT WOULD MAKE THIS FAIL: any new member of `_VAT_ALIASES`.
		for stored in ("VAT", "Value Added Tax", "НДС"):
			with self.subTest(stored=stored, on_main="VAT"):
				self.assertTrue(is_vat_charge_type(stored))
				self.assertEqual(self._total_of(stored)[0], 1000.0)
		for stored in ("Import VAT", "VAT recoverable", "Freight"):
			with self.subTest(stored=stored, on_main="an ordinary charge"):
				self.assertFalse(is_vat_charge_type(stored))
				self.assertEqual(self._total_of(stored)[0], 1300.0)


class TestStoredDataIsNeverRewritten(unittest.TestCase):
	"""Store -> dump -> compare. The RAW shape is what reaches the disk."""

	def test_a_quotation_line_keeps_the_string_it_was_stored_with(self):
		for stored in ("Freight", "Customs Duty", "VAT", "General", "Local Delivery"):
			with self.subTest(stored=stored):
				line = raw_charge_line({"charge_type": stored, "amount": 10.0})
				self.assertEqual(line["charge_type"], stored)

	def test_the_whole_payload_round_trips_byte_for_byte(self):
		stored = [
			{"charge_type": "Freight", "amount": 1000.0, "description": "FOB Shanghai"},
			{"charge_type": "VAT", "amount": 300.0, "is_recoverable_vat": True},
		]
		once = json.dumps(sanitize_charge_lines(stored), ensure_ascii=False)
		twice = json.dumps(sanitize_charge_lines(json.loads(once)), ensure_ascii=False)
		self.assertEqual(once, twice)
		self.assertIn('"charge_type": "VAT"', once)

	def test_a_po_line_keeps_broker_and_loading(self):
		# These two are the ONLY stored PO values the decision renames, and
		# `_raw_landed_lines` is a write path: coercing them there would rewrite
		# the disk the first time anything re-saved the PO.
		# WHAT WOULD MAKE THIS FAIL: narrowing the membership check to the nine
		# canonical keys -- both would be stored as "other", and the cost would
		# stop being a broker cost at all.
		tender = _load_tender()
		lines = tender._raw_landed_lines(
			[{"type": "broker", "amount": 100.0}, {"type": "loading", "amount": 200.0}]
		)
		self.assertEqual([line["type"] for line in lines], ["broker", "loading"])

	def test_the_po_write_path_admits_only_what_a_po_can_store(self):
		# `_raw_landed_lines` is a WRITE path fed by a whitelisted endpoint, so
		# its membership check decides what a POST can put on disk. Asking the
		# full alias table -- which also carries the QUOTATION spellings and the
		# VAT ones -- let a caller persist `"vat"` as a PO charge type: a value
		# no board can produce, and one `lcv_math.is_vat_component` matches on a
		# substring, so the line would quietly leave the landed cost voucher. A
		# blank one fared worse and persisted as "" -- neither a type nor a
		# fallback. Main stored all of these as "other" (eleven keys), and so
		# does this: the nine, plus the two legacy keys the board itself wrote.
		# WHAT WOULD MAKE THIS FAIL: gating on `is_known_charge_type` again.
		tender = _load_tender()
		for posted in ("vat", "VAT", "freight", "Handling & Terminal", "General", "  ", "\t"):
			with self.subTest(posted=posted):
				lines = tender._raw_landed_lines([{"type": posted, "amount": 10.0}])
				self.assertEqual(lines[0]["type"], "other")

	def test_a_po_line_survives_the_editors_round_trip(self):
		# The review's P0, from the server's side. `save_po_landed_charges`
		# REPLACES the whole array, so whatever the editor hands back IS the new
		# disk. A read must therefore give the editor the stored key and the
		# editor must give it back -- if either half substitutes the canonical
		# one, opening the plan and pressing Save for any reason renames every
		# legacy line, and `api.lcv` stops recognising the charge it already
		# vouchered (its row identity is `label or type`), so the same cost is
		# posted into valuation and the GL a second time.
		tender = _load_tender()
		stored = json.dumps(
			[{"type": "broker", "label": "", "amount": 100.0}, {"type": "loading", "amount": 200.0}]
		)
		read = tender._parse_landed(stored)
		# What the editor hands back: the line it was given, minus the keys the
		# read derives (`savedLine` sends `type`, never `type_canonical`).
		derived = ("type_canonical", "amount_given", "unvalued")
		sent = [{k: v for k, v in line.items() if k not in derived} for line in read]
		dumped = json.loads(json.dumps(tender._raw_landed_lines(sent)))
		self.assertEqual([line["type"] for line in dumped], ["broker", "loading"])


class TestTheValuedShapeCanonicalisesWithoutMovingTheMoney(unittest.TestCase):
	"""The PO reader gains a key; it does not lose one, and no figure moves."""

	def setUp(self):
		self.tender = _load_tender()

	def test_a_legacy_po_line_reports_both_names(self):
		line = self.tender._parse_landed([{"type": "broker", "amount": 100.0, "actual": 90.0}])[0]
		self.assertEqual(line["type"], "broker")  # what is on disk, and what api.lcv reads
		self.assertEqual(line["type_canonical"], "declarant")  # what the editor shows
		self.assertEqual(line["amount"], 100.0)
		self.assertEqual(line["actual"], 90.0)

	def test_the_logistics_boards_freight_figure_counts_only_transport(self):
		# Zafar, 2026-09-03, once ADR-606 had landed: the logistics board's
		# freight figure counts CANONICAL transport and nothing else. `loading` is
		# terminal handling under the one list -- it resolves to `storage` -- so a
		# stored `loading` line leaves that figure. The board's number has to
		# agree with the list the officer picks from, or the board and the editor
		# mean different things by "freight".
		#
		# Behavioural, and through `_transport_figure` -- the very expression
		# `logist_board` sums, so this test cannot drift from the board. Named
		# rather than cited by line: the version of this test that shipped in
		# 80cbc19 pointed at `tender.py:2619`, which was 37 lines stale already.
		lines = self.tender._parse_landed(
			[
				{"type": "transport", "amount": 300.0},
				{"type": "loading", "amount": 200.0},
				{"type": "storage", "amount": 50.0},
				{"type": "broker", "amount": 90.0},
			]
		)
		self.assertEqual(self.tender._transport_figure(lines), 300.0)

	def test_the_freight_figure_reads_the_canonical_key_not_the_stored_one(self):
		# The stored key is still untouched on disk -- that is the ADR-606 rule,
		# asserted in TestStoredDataIsNeverRewritten. What changed is which key
		# the FIGURE asks. WHAT WOULD MAKE THIS FAIL: summing `c["type"]`, which
		# both drops a line whose stored spelling only the alias table resolves
		# and re-admits `loading`.
		lines = self.tender._parse_landed([{"type": "loading", "amount": 200.0}])
		self.assertEqual(lines[0]["type"], "loading")
		self.assertEqual(self.tender._transport_figure(lines), 0.0)

	def test_a_customs_line_is_still_a_customs_line(self):
		# Three behaviours hang off this exact string: the currency conversion
		# skip in `_parse_landed`, the refusal in `save_po_landed_charges` and
		# the recoverable-VAT figure in `po_landed_charges`.
		line = self.tender._parse_landed([{"type": "customs", "amount": 100.0}])[0]
		self.assertEqual(line["type"], "customs")
		self.assertEqual(line["type_canonical"], "customs")


class TestTheEndpointServesTheOneList(unittest.TestCase):
	"""Both editors read the list from here, so here is where it is asserted."""

	def test_the_endpoint_returns_the_nine_keys_in_order_with_labels(self):
		tender = _load_tender()
		served = tender.landed_charge_types()["charge_types"]
		self.assertEqual(served, [dict(entry) for entry in CHARGE_TYPES])

	def test_the_endpoint_hands_out_a_copy(self):
		# WHAT WOULD MAKE THIS FAIL: returning the module constant itself. Frappe
		# serialises the return value, and a mutation by any caller would edit
		# the catalogue for every later request in the same worker process.
		tender = _load_tender()
		tender.landed_charge_types()["charge_types"][0]["label"] = "mutated"
		self.assertEqual(tender.landed_charge_types()["charge_types"][0], dict(CHARGE_TYPES[0]))


class TestEveryLabelIsTranslated(unittest.TestCase):
	"""The nine labels reach the SPA from the SERVER, so the harvester never
	sees them: there is no `t("Freight / transport")` literal in any .vue file to
	scan for. Nothing else would notice them missing -- the SPA falls back to the
	English source string, so a Russian user would simply read English and no
	test would go red. This is that test."""

	def _msgids(self, lang):
		path = _ROOT / "translations" / f"{lang}.csv"
		with path.open(encoding="utf-8") as handle:
			return {row[0] for row in csv.reader(handle) if row}

	def test_every_label_ships_in_all_five_catalogues(self):
		for lang in _LANGS:
			msgids = self._msgids(lang)
			for entry in CHARGE_TYPES:
				with self.subTest(lang=lang, label=entry["label"]):
					self.assertIn(entry["label"], msgids)

	def test_removing_a_label_did_not_un_translate_another_screen(self):
		# The same rename deleted ten msgids whose last landed-charge caller was
		# gone. A msgid's callers are not all literals, though: `t()` is called
		# on VALUES too -- `ImportExpenses.vue` maps its own category list
		# through `t(c)` -- so a live caller can exist that no grep for
		# `t("Storage")` will ever find. "Storage" was one of those, and dropping
		# it left the imports expense filter rendering English in four languages
		# with nothing red to say so. Removal is safe only when EVERY caller is
		# gone, including the dynamic ones.
		# WHAT WOULD MAKE THIS FAIL: dropping any of these rows again.
		src = (_ROOT / "public" / "js" / "pages" / "imports" / "ImportExpenses.vue").read_text(
			encoding="utf-8"
		)
		listed = re.search(r"const CATEGORIES = \[(.*?)\];", src, re.S)
		self.assertIsNotNone(listed, "ImportExpenses.vue no longer lists its categories inline")
		categories = re.findall(r'"([^"]+)"', listed.group(1))
		self.assertIn("Storage", categories)
		for lang in _LANGS:
			msgids = self._msgids(lang)
			missing = [category for category in categories if category not in msgids]
			self.assertEqual(missing, [], f"{lang} lost a msgid ImportExpenses.vue still translates")
