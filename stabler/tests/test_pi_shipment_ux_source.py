"""Structural guards for the sandbox-ported PI shipment UX.

The sandbox (~/msa-sandbox) settled these rules against the real book; this
file pins the port: everything delegates to _imports_rules (one math in the
whole app), over-shipment stays its own figure, and column aliases match what
the pure module actually reads.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
PURCHASING = os.path.join(_ROOT, "api", "purchasing.py")
PAGES = os.path.join(_ROOT, "public", "js", "pages", "imports")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class RollupTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "_attach_proforma_match_rollups")

	def test_delegates_to_the_rules_module(self):
		for call in ("rules.contract_index(", "rules.shipped_index(", "rules.remaining_for("):
			with self.subTest(call=call):
				self.assertIn(call, self.body)

	def test_sql_aliases_match_what_the_rules_read(self):
		# _contract_pi reads pi_name/parent; _shipped_pi reads pi_name/
		# custom_proforma_invoice. Any other alias yields an empty match key
		# and every balance silently reads zero.
		self.assertIn("AS pi_name", self.body)
		self.assertNotIn("AS proforma_invoice", self.body)

	def test_over_shipment_is_its_own_figure(self):
		self.assertIn('r["over_boxes"]', self.body)
		self.assertNotIn("max(0", self.body)

	def test_wired_into_the_list(self):
		lst = body(self.src, "list_proformas")
		self.assertIn("_attach_proforma_match_rollups(rows)", lst)


class DeviationsPageTest(unittest.TestCase):
	"""The user's actual goal: the PI is the agreement, the CI is what shipped —
	and the places they disagree must be REALLY visible, with the metrics."""

	def setUp(self):
		self.vue = read(os.path.join(PAGES, "PiCiDiscrepancies.vue"))

	def test_reads_the_shared_endpoint_not_a_rederivation(self):
		self.assertIn('call("stabler.api.imports.get_ci_pi_discrepancies"', self.vue)

	def test_shows_the_agreement_vs_shipment_metrics(self):
		for metric in (
			"matched_lines",
			"orphan_lines",
			"over_keys",
			"remaining_boxes",
			"price_docs",
			"price_agreed",
		):
			with self.subTest(metric=metric):
				self.assertIn(metric, self.vue)

	def test_rows_link_back_to_both_documents(self):
		self.assertIn("imports-commercial-invoice", self.vue)
		self.assertIn("imports-proforma", self.vue)
		self.assertNotIn('"/app', self.vue)

	def test_route_registered_and_reachable_from_the_flow_board(self):
		router = read(os.path.join(_ROOT, "public", "js", "router.js"))
		self.assertIn('"imports-discrepancies"', router)
		flow = read(os.path.join(PAGES, "ImportsFlow.vue"))
		self.assertIn("/imports/discrepancies", flow)


class PiScopedInfoTest(unittest.TestCase):
	def test_single_pi_call_carries_the_sub_cut_rows(self):
		# The PI form's sub-cut breakdown is the info rows; a whole-book call
		# still filters them (they would drown the payload).
		src = read(API)
		b = body(src, "get_ci_pi_discrepancies")
		self.assertIn('not (pi and level == "info")', b)


class SupplierScopeTest(unittest.TestCase):
	"""`list_suppliers` gained an optional imports supplier-group scope.

	Twenty call sites share this one endpoint and only four of them ask for the
	scope, so the no-argument path has to stay the query it has always been —
	otherwise a config row on one tenant silently empties the transporter and
	customs-broker pickers on every other screen. Source-text, not behavioural:
	the module imports frappe at import time and the WHERE is built inline, so
	there is nothing importable to exercise under `make test`.
	"""

	def setUp(self):
		self.body = body(read(PURCHASING), "list_suppliers")

	def test_list_suppliers_keeps_the_unfiltered_identity_path(self):
		# The seed condition is still the bare one: without a scope the query
		# filters exactly what it filtered before.
		self.assertIn('conds = ["disabled = 0"]', self.body)
		# Also pinned by test_master_read_permission.py against the source text.
		self.assertIn('has_permission("Supplier", "read")', self.body)

		lines = self.body.splitlines()
		seed = next(i for i, ln in enumerate(lines) if 'conds = ["disabled = 0"]' in ln)
		seed_indent = len(lines[seed]) - len(lines[seed].lstrip())
		predicates = [i for i, ln in enumerate(lines) if "supplier_group IN" in ln]
		self.assertTrue(predicates, "the supplier-group predicate is gone")
		for i in predicates:
			indent = len(lines[i]) - len(lines[i].lstrip())
			# Deeper than the seed => it lives under a branch, not in the trunk.
			self.assertGreater(indent, seed_indent, "the group predicate is in the trunk")
			guard = [ln for ln in lines[seed:i] if ln.strip().startswith("if ")]
			self.assertTrue(guard, "the group predicate is appended unconditionally")

	def test_group_names_are_bound_never_interpolated(self):
		# Group names come from a config row an admin types; they reach the
		# query as a parameter or not at all.
		self.assertIn("supplier_group IN %(", self.body)
		self.assertNotIn("supplier_group IN ('", self.body)
		self.assertNotIn('supplier_group IN ("', self.body)

	def test_the_client_sends_a_scope_key_not_a_group_list(self):
		# C3: a tenant's group names never travel to the browser. The argument
		# is a key the server resolves against Stabler Settings.
		self.assertIn("supplier_group_scope", self.body)
		self.assertIn("imports_supplier_groups_for", self.body)

	def test_an_unknown_scope_key_is_reported_not_swallowed(self):
		# A typo'd key must read as a failure, not as "no filter, all good".
		self.assertIn("frappe.log_error(", self.body)


class PagesTest(unittest.TestCase):
	def test_list_shows_the_sandbox_columns(self):
		lst = read(os.path.join(PAGES, "ProformaInvoices.vue"))
		for token in ("shipped_pct", "remaining_boxes", "over_boxes"):
			with self.subTest(token=token):
				self.assertIn(token, lst)
		# Over-shipment is a red badge, not folded into the remainder.
		self.assertIn("bg-red-lt", lst)

	def test_form_match_panel_uses_the_shared_endpoint(self):
		form = read(os.path.join(PAGES, "ProformaForm.vue"))
		self.assertIn('call("stabler.api.imports.get_ci_pi_discrepancies"', form)
		self.assertIn("subCuts", form)

	def test_compare_stays_removed(self):
		# The user rejected PI-vs-PI comparison; the goal is agreement-vs-
		# shipment (the deviations page). Keep the dead feature dead.
		router = read(os.path.join(_ROOT, "public", "js", "router.js"))
		self.assertNotIn("imports-proformas-compare", router)
		self.assertNotIn("compare_proformas", read(API))
		self.assertFalse(os.path.exists(os.path.join(PAGES, "ProformaCompare.vue")))


class TwoStepSmartFillContractTest(unittest.TestCase):
	"""`get_vendor_available_pi_lines` feeds a two-step modal from ONE response.

	Step 1 (pick PIs) and step 2 (allocate lines) read the same payload, so the
	shape is a contract, not an implementation detail: `proformas` is always the
	supplier's FULL open list (narrowing it would blank the picker the moment a
	narrowed load returns) and `lines` is the only thing `selected_pis` scopes.
	Source-text, like the rest of this file: the module imports frappe at import
	time, so there is nothing importable to exercise under `make test`.
	"""

	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "get_vendor_available_pi_lines")
		self.signature = self.body[: self.body.index(") -> dict:") + 1]

	def test_available_pi_lines_always_returns_both_keys(self):
		# Step 1 renders `proformas`, step 2 renders `lines`. A branch that omits
		# either key blanks one of the two steps with no error to show for it.
		dict_returns = re.findall(r"\breturn \{.*?\}", self.body, re.S)
		self.assertEqual(
			len(dict_returns),
			self.body.count("\treturn "),
			"every return in this function must be a dict literal",
		)
		self.assertGreaterEqual(len(dict_returns), 3)
		for ret in dict_returns:
			with self.subTest(ret=ret[:60]):
				self.assertIn('"proformas"', ret)
				self.assertIn('"lines"', ret)

	def test_remaining_boxes_is_never_clamped(self):
		# Over-shipment is real data, reported through over_shipped/over_boxes.
		self.assertNotIn("max(0", self.body)

	def test_selected_pis_does_not_shadow_the_local(self):
		# The function already binds a `pi_names` LOCAL that every SQL statement
		# uses as a bound parameter. A parameter of that name would shadow it and
		# silently scope the whole query to the caller's argument.
		self.assertIn("selected_pis", self.signature)
		self.assertNotIn("pi_names", self.signature)
		self.assertIn("pi_names = [", self.body)
		self.assertIn("%(pi_names)s", self.body)

	def test_the_narrowing_is_server_side_and_cannot_fall_through(self):
		# Whitelisted arguments arrive as strings over HTTP.
		self.assertIn("frappe.parse_json(selected_pis)", self.body)
		self.assertIn("isinstance(selected_pis, str)", self.body)
		# The SQL scope is derived from the intersection, not from the raw list:
		# an unknown name must not widen the query, and an empty intersection
		# must return no lines rather than falling through to all of them.
		narrowing = next(ln for ln in self.body.splitlines() if "pi_names = [" in ln)
		self.assertIn("selected", narrowing)
		after = self.body[self.body.index(narrowing) + len(narrowing) :]
		guard = after[: after.index("\n\n")]
		self.assertIn("if not pi_names:", guard)
		self.assertIn('"lines": []', guard)

	def test_include_lines_is_trailing_defaulted_and_short_circuits(self):
		# Both new arguments are trailing and defaulted, so the two existing
		# two-argument call sites keep behaving exactly as they do today.
		self.assertLess(self.signature.index("selected_pis"), self.signature.index("include_lines"))
		self.assertLess(self.signature.index("exclude_ci"), self.signature.index("selected_pis"))
		self.assertRegex(self.signature, r"include_lines[^,)]*=\s*True")
		# "0" is a non-empty string and therefore truthy — a bare `if not x`
		# would treat include_lines=0 arriving over HTTP as "include them".
		self.assertIn('"0"', self.body)
		self.assertIn('"false"', self.body)


class TwoStepSmartFillUiTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(os.path.join(PAGES, "CommercialInvoiceForm.vue"))

	def func(self, name):
		m = re.search(rf"^(?:async )?function {name}\(", self.vue, re.M)
		assert m, f"{name} not found"
		tail = self.vue[m.start() :]
		nxt = re.search(r"\n(?:async function |function |const |watch\()", tail[1:])
		return tail[: nxt.start() + 1] if nxt else tail

	def test_pi_tracking_never_asks_for_a_line_less_response(self):
		# refreshPiTracking reads ONLY `lines`; passing include_lines=false here
		# would silently empty the PI tracking table on the form.
		tracking = self.func("refreshPiTracking")
		self.assertIn("get_vendor_available_pi_lines", tracking)
		self.assertNotIn("include_lines", tracking)
		self.assertNotIn("selected_pis", tracking)

	def test_load_issues_exactly_one_request_for_the_whole_selection(self):
		# The narrowing is server-side. One press = one request, never one per PI.
		load = self.func("loadMultiPiLines")
		self.assertEqual(load.count('call("stabler.api.imports.get_vendor_available_pi_lines"'), 1)
		self.assertNotIn("Promise.all", load)
		self.assertIn("selected_pis", load)

	def test_opening_the_modal_skips_the_line_work(self):
		opener = self.func("openMultiPiSmartFill")
		self.assertIn("include_lines: false", opener)

	def test_both_steps_are_translated_and_skeletoned(self):
		for key in (
			"Step 1: Select Proforma Invoices",
			"Step 2: Allocate Line Items",
			"Load Available Lines",
			"Back to PI selection",
		):
			with self.subTest(key=key):
				self.assertIn(f't("{key}")', self.vue)
		# Step 1 loads behind SkeletonRows too — never a bare spinner.
		self.assertEqual(self.vue.count("<SkeletonRows"), 2)

	def test_changing_the_supplier_resets_both_steps(self):
		self.assertRegex(self.vue, r"watch\(\s*\(\) => form\.value\.supplier")

	def test_new_strings_land_in_all_five_languages(self):
		langs = ("en", "ru", "uz", "uzc", "tr")
		keys = (
			"Step 1: Select Proforma Invoices",
			"Step 2: Allocate Line Items",
			"Load Available Lines",
			"Back to PI selection",
			"Select All",
			"Deselect All",
			# The item-granularity split: a group header plus its contract lines.
			"Allocated",
			"{count} PI lines",
			"Contract line",
			"Shipped as this cut",
			"Indicative only — shipments are tracked per category",
			"This category pool has no boxes left.",
		)
		for lang in langs:
			csv_text = read(os.path.join(_ROOT, "translations", f"{lang}.csv"))
			for key in keys:
				with self.subTest(lang=lang, key=key):
					self.assertIn(key, csv_text)


class SmartFillLineSelectionTest(unittest.TestCase):
	"""R3: step 2 is a SELECTION screen, not an auto-fill.

	Apply must push the rows the user checked — not every row that happens to
	carry a non-zero allocation — and the summary bar the user reads before
	pressing it must be the same arithmetic Apply runs. A second, parallel
	computation is the whole bug class here: the user reads one total and gets
	another. Source-text, like the rest of this file: a .vue SFC has no unit
	harness in this repo.
	"""

	def setUp(self):
		self.vue = read(os.path.join(PAGES, "CommercialInvoiceForm.vue"))

	def func(self, name):
		m = re.search(rf"^(?:async )?function {name}\(", self.vue, re.M)
		assert m, f"{name} not found"
		tail = self.vue[m.start() :]
		nxt = re.search(r"\n(?:async function |function |const |watch\()", tail[1:])
		return tail[: nxt.start() + 1] if nxt else tail

	def const(self, name):
		m = re.search(rf"^const {name} = ", self.vue, re.M)
		assert m, f"{name} not found"
		tail = self.vue[m.start() :]
		nxt = re.search(r"\n(?:async function |function |const |watch\()", tail[1:])
		return tail[: nxt.start() + 1] if nxt else tail

	def supplier_watcher(self):
		m = re.search(r"watch\(\s*\(\) => form\.value\.supplier", self.vue)
		assert m, "the supplier watcher is gone"
		return self.vue[m.start() : self.vue.index("\n);", m.start())]

	# --- the selection itself ------------------------------------------------

	def test_apply_iterates_the_selection_not_every_available_line(self):
		# The bug this replaces: Apply walked multiPiLines and pushed anything
		# with boxes > 0, so "these three, not those seven" meant zeroing seven
		# boxes by hand.
		apply_ = self.func("applyMultiPiAllocation")
		self.assertIn("multiPiSelectedLines.value", apply_)
		self.assertNotIn("of multiPiLines.value", apply_)

	def test_the_selection_is_keyed_by_the_line_identity_not_the_index(self):
		# Array position is not stable across a reload; the row key is. Since the
		# picker splits a bundle into its contract lines, that key is now
		# multiPiRowKey (group key + the PI row's own docname), not multiPiKey.
		selected = self.const("multiPiSelectedLines")
		self.assertIn("row.key", selected)
		self.assertIn("multiPiRows.value", selected)
		self.assertNotIn("index", selected)
		self.assertIn("const multiPiRowKey = (line, child) => `${multiPiKey(line)}::${child.row}`;", self.vue)

	def test_step_two_does_not_overload_step_ones_selection_ref(self):
		# multiPiSelected is step 1's list of PI names. Reusing it would make
		# "Back" wipe the line picks, and Load wipe the PI picks.
		self.assertIn("const multiPiPickedKeys = ref([])", self.vue)
		self.assertNotIn("multiPiSelected.value.includes(multiPiKey", self.vue)

	def test_a_checked_line_with_a_zero_allocation_is_still_never_pushed(self):
		apply_ = self.func("applyMultiPiAllocation")
		self.assertIn("if (boxes > 0)", apply_)

	def test_unchecking_a_line_does_not_touch_its_typed_allocation(self):
		# Allocations live in their own map. Select All fills them now (nothing is
		# prefilled any more, so a pure selection would leave every total at 0 and
		# Apply disabled) — but the OFF branch must still drop the picks and only
		# the picks, so a user who unchecks and changes their mind gets the number
		# they typed back.
		toggle = self.func("multiPiSelectAllLines")
		off_branch = toggle.split("if (!on) {", 1)[1].split("}", 1)[0]
		self.assertNotIn("multiPiAllocations", off_branch)
		self.assertNotIn("delete multiPiAllocations", self.vue)

	# --- the summary bar -----------------------------------------------------

	def test_the_summary_and_apply_share_exactly_one_computation(self):
		# AC4: the totals the user reads must be the totals Apply pushes.
		helper = self.func("multiPiLineTotals")
		self.assertIn("* bw", helper)
		self.assertIn("agreed_rate", helper)
		# The boxes come from the plan, so the header, the summary bar and Apply
		# cannot disagree about what a row is worth.
		self.assertIn("multiPiPlan.value.byRow[row.key]", helper)

		apply_ = self.func("applyMultiPiAllocation")
		summary = self.const("multiPiSummary")
		for name, blk in (("apply", apply_), ("summary", summary)):
			with self.subTest(block=name):
				self.assertIn("multiPiLineTotals(", blk)
				# No second copy of the arithmetic in either consumer. Apply still
				# carries `rate: line.agreed_rate` — it is the MULTIPLICATION that
				# may not be duplicated, not the field.
				self.assertNotIn("* bw", blk)
				self.assertNotRegex(blk, r"\*\s*\(?\s*line\.agreed_rate")
				self.assertNotRegex(blk, r"line\.agreed_rate\s*\|\|\s*0\s*\)?\s*\*")

	def test_the_summary_applies_the_same_boxes_gate_as_apply(self):
		summary = self.const("multiPiSummary")
		self.assertIn("boxes <= 0", summary)
		self.assertIn("multiPiSelectedLines.value", summary)

	def test_the_summary_reports_all_four_figures(self):
		summary = self.const("multiPiSummary")
		for figure in ("lines", "boxes", "qty", "value"):
			with self.subTest(figure=figure):
				self.assertIn(figure, summary)
		for key in ("Lines selected", "Total boxes", "Total kg", "Total agreed value"):
			with self.subTest(key=key):
				self.assertIn(f't("{key}")', self.vue)

	def test_the_value_total_renders_in_the_documents_own_currency(self):
		# Project rule: transaction currency only, never a converted equivalent,
		# and through the file's existing formatter — not a new one.
		self.assertIn("fm(multiPiSummary.value, form.currency)", self.vue)
		self.assertNotIn('MoneyInput v-model="multiPiSummary', self.vue)

	# --- the controls --------------------------------------------------------

	def test_the_header_checkbox_carries_an_indeterminate_binding(self):
		self.assertIn("indeterminate.prop", self.vue)
		some = self.const("multiPiSomeLinesSelected")
		self.assertIn("multiPiPickedKeys.value.length", some)
		self.assertIn("multiPiAllLinesSelected.value", some)

	def test_step_two_has_its_own_select_all_pair(self):
		self.assertIn("multiPiSelectAllLines(true)", self.vue)
		self.assertIn("multiPiSelectAllLines(false)", self.vue)
		# Step 1's helper is untouched and still bound to step 1's buttons.
		self.assertIn("multiPiSelectAll(true)", self.vue)
		self.assertIn("multiPiSelectAll(false)", self.vue)

	def test_only_one_primary_button_per_footer(self):
		# CLAUDE.md: one .btn-primary per visual region. The new controls are
		# outline-secondary, so the count must not have moved.
		self.assertEqual(self.vue.count('class="btn btn-primary" :disabled="multiPiLoading'), 2)

	# --- lifecycle -----------------------------------------------------------

	def test_nothing_is_preselected_or_prefilled_when_the_lines_arrive(self):
		# The picker asks for a quantity, it does not propose one: pre-filling every
		# cut to its ceiling wrote thirteen rows the user never asked for. So the
		# lines arrive unchecked and at zero, and the user types what they want.
		load = self.func("loadMultiPiLines")
		self.assertIn("multiPiPickedKeys.value = []", load)
		self.assertNotIn("multiPiPickedKeys.value.push(key)", load)
		self.assertIn("multiPiAllocations.value[key] = 0", load)

	def test_the_line_selection_dies_with_the_supplier(self):
		self.assertIn("multiPiPickedKeys.value = []", self.supplier_watcher())

	# --- R4 regression pins (these passed before R3 too) ---------------------

	def test_the_allocation_cap_survives(self):
		# The category pool is still the authoritative ceiling; it just moved into
		# poolRemaining, because an individual row is now capped by its own
		# contract as well (maxAllocatable -> rowCeiling).
		self.assertIn("const poolRemaining = (line) => Math.max(0, line.remaining_boxes || 0);", self.vue)
		clamp = self.func("setAllocation")
		self.assertIn("Math.min(Math.max(n, 0), maxAllocatable(row))", clamp)
		# The controlled-input desync fix: a clamp onto the current value
		# re-renders nothing, so the element itself gets written back.
		self.assertIn("ev.target.value = clamped", clamp)
		self.assertIn(':max="maxAllocatable(row)"', self.vue)
		self.assertIn('@input="setAllocation(row, $event)"', self.vue)

	def test_over_shipment_is_still_signed_everywhere_but_the_input_cap(self):
		# C2: exactly one floor of 0 on remaining_boxes in the whole file.
		self.assertEqual(self.vue.count("Math.max(0, line.remaining_boxes"), 1)
		self.assertIn("line.over_shipped", self.vue)

	def test_the_pushed_row_shape_is_unchanged(self):
		apply_ = self.func("applyMultiPiAllocation")
		for field in (
			"custom_proforma_invoice: line.pi_name",
			"category: line.category",
			"item: multiPiItems.value[key]",
			"boxes: boxes",
			"box_weight_kg: bw",
			"qty: qty",
			'uom: "Kg"',
			# The contract line's own rate wins, the bundle's is the fallback: a
			# mixed bundle may price its cuts differently.
			"rate: child.agreed_rate || line.agreed_rate",
			"docs_price: child.docs_price || line.docs_price",
			"_qtyManual: true",
		):
			with self.subTest(field=field):
				self.assertIn(field, apply_)

	def test_the_sub_cut_picker_and_shipped_badges_survive(self):
		self.assertIn("multiPiItemOptions(line)", self.vue)
		self.assertIn('t("Already shipped as")', self.vue)

	def test_the_new_strings_land_in_all_five_languages(self):
		for lang in ("en", "ru", "uz", "uzc", "tr"):
			csv_text = read(os.path.join(_ROOT, "translations", f"{lang}.csv"))
			for key in ("Lines selected", "Total agreed value", "Total boxes", "Total kg"):
				with self.subTest(lang=lang, key=key):
					self.assertRegex(csv_text, rf"(?m)^{re.escape(key)},")


class SmartFillItemGranularityTest(unittest.TestCase):
	"""Step 2 offers a bundle's individual PI lines, without moving the match key.

	PI-AUG-26 books thirteen cuts under one category. The picker used to show
	one row for all of them, so "pick the products I want" was impossible. The
	fix splits the DISPLAY only: the key stays (PI, category), which is the key
	the server guard sums CI rows by, so thirteen rows carrying the same PI and
	the same verbatim category are the same thing to it as one row was.

	The failure this pins is a silent second match key growing at item level —
	measured at 19.5% CI-line coverage against the category key's 98.3%.
	"""

	def setUp(self):
		self.api = read(API)
		self.rules = read(os.path.join(_ROOT, "api", "_imports_rules.py"))
		self.vue = read(os.path.join(PAGES, "CommercialInvoiceForm.vue"))

	# --- the backend split ---------------------------------------------------

	def test_the_api_publishes_the_bundle_s_contract_lines(self):
		lines = body(self.api, "get_vendor_available_pi_lines")
		self.assertIn('"contract_lines": rules.contract_line_breakdown(entry)', lines)
		# The split lives in the pure rules module, so the endpoint stays free of
		# arithmetic and test_available_pi_lines_always_returns_both_keys holds.
		self.assertNotIn("def contract_line_breakdown", self.api)

	def test_the_split_clamps_nothing(self):
		# C2: over-shipment is real data. A max(0, …) here would hide a book that
		# already exceeded its contract.
		split = body(self.rules, "contract_line_breakdown")
		# The docstring says "no max(0, …)" in prose; check the code below it.
		code = split[split.index('"""', split.index('"""') + 3) :]
		self.assertNotIn("max(0", code)

	def test_the_split_keys_on_the_row_docname_not_the_item_code(self):
		# One PI may book the same code twice at different rates; merging them
		# would make two contract lines share one allocation box.
		split = body(self.rules, "contract_line_breakdown")
		self.assertIn('ln.get("name")', split)

	# --- the row identity ----------------------------------------------------

	def test_the_row_key_is_the_group_key_plus_the_pi_row(self):
		self.assertIn("const multiPiRowKey = (line, child) => `${multiPiKey(line)}::${child.row}`;", self.vue)
		# The GROUP key is untouched: it is what Apply writes and what the guard
		# reduces to.
		self.assertIn("const multiPiKey = (line) => `${line.pi_name}::${normKey(line.category)}`;", self.vue)

	def test_there_is_exactly_one_place_that_flattens_groups_into_rows(self):
		rows = self.vue[self.vue.index("const multiPiRows = computed(") :]
		rows = rows[: rows.index("\n});") + 4]
		self.assertIn("line.contract_lines", rows)
		self.assertEqual(self.vue.count("(line.contract_lines || []).forEach"), 1)

	# --- the double cap ------------------------------------------------------

	def test_a_row_is_capped_by_its_own_contract_and_by_the_category_pool(self):
		self.assertIn(
			'import { buildAllocationPlan, rowCeiling } from "../../composables/piAllocation.js";', self.vue
		)
		self.assertIn("const maxAllocatable = (row) => rowCeiling(", self.vue)
		self.assertIn("const multiPiPlan = computed(() => buildAllocationPlan(", self.vue)
		# Ceiling (a): the row's own contract, net of what was shipped as that cut.
		self.assertIn("function rowContractRemaining(line, child)", self.vue)
		# Ceiling (b): the category pool, which is the only figure the server checks.
		self.assertIn("pool: poolRemaining(row.line)", self.vue)

	def test_item_level_shipped_is_advisory_and_never_leaves_the_client(self):
		# Attributing a shipment to one contract line IS the 19.5% item key. It
		# may narrow a ceiling on screen; it must not come from the API as an
		# authoritative balance somebody later subtracts.
		self.assertIn("function rowShippedAsThisCut(line, child)", self.vue)
		self.assertNotIn("shipped_boxes", body(self.rules, "contract_line_breakdown"))

	def test_the_header_the_summary_and_apply_all_read_the_same_plan(self):
		for name in ("multiPiGroupAllocated", "multiPiLineTotals"):
			with self.subTest(reader=name):
				self.assertIn("multiPiPlan.value", self.vue[self.vue.index(name) :][:600])
		self.assertIn("{{ fn(multiPiGroupAllocated(line)) }} / {{ fn(poolRemaining(line)) }}", self.vue)

	# --- what Apply writes ---------------------------------------------------

	def test_apply_writes_the_group_s_pi_and_category_verbatim(self):
		apply_ = self.vue[self.vue.index("function applyMultiPiAllocation") :]
		apply_ = apply_[: apply_.index("\n}\n") + 3]
		self.assertIn("custom_proforma_invoice: line.pi_name", apply_)
		self.assertIn("category: line.category", apply_)
		# normKey is a KEY normaliser; writing it into a document field would
		# uppercase the category the guard then fails to match.
		self.assertNotIn("normKey(", apply_)

	# --- the surfaces that must not regress ----------------------------------

	def test_the_dom_ids_stay_index_based(self):
		# The group/line pair survives the flattening: multiPiRows carries both
		# indices, so the ids the QA tooling addresses are unchanged.
		self.assertIn("`multi-pi-line-${row.lineIdx}-${row.childIdx}`", self.vue)
		# A match key carries "::" and spaces — legal for <label for> but
		# unaddressable by any id selector, which the QA tooling needs.
		self.assertNotIn("`multi-pi-line-${multiPiKey", self.vue)
		self.assertNotIn("`multi-pi-line-${row.key", self.vue)

	def test_the_pool_is_a_band_above_the_table_not_a_row_in_it(self):
		# The user asked to go straight to the product lines, but the pool figures
		# are the ones the server guard enforces (and C2's over-shipment surface),
		# so they move above the table read-only instead of being dropped.
		self.assertNotIn('<tr class="fw-semibold">', self.vue)
		self.assertNotIn("multiPiToggleGroup", self.vue)
		for kept in ('t("Allocated")', "poolRemaining(line)", "line.over_shipped", 't("Already shipped as")'):
			with self.subTest(band=kept):
				self.assertIn(kept, self.vue)

	def test_the_table_iterates_the_flat_row_list(self):
		# One <tr> per contract line, straight off the single flattening point —
		# no group wrapper, so no header row can creep back in.
		self.assertIn('v-for="row in multiPiRows"', self.vue)
		self.assertNotIn('v-for="(line, lineIdx) in multiPiLines"', self.vue)

	def test_typing_a_quantity_selects_the_row_it_was_typed_into(self):
		# Nothing is preselected any more, and buildAllocationPlan plans an
		# unpicked row to 0 — so a number typed into an unchecked row would show
		# on screen and be dropped by Apply in silence. Typing IS the intent.
		clamp = self.vue[self.vue.index("function setAllocation") :]
		clamp = clamp[: clamp.index("\n}\n") + 3]
		self.assertIn("clamped > 0", clamp)
		self.assertIn("multiPiPickedKeys.value.push(key)", clamp)

	def test_the_split_did_not_add_a_third_skeleton_or_a_manual_stripe(self):
		self.assertEqual(self.vue.count("<SkeletonRows"), 2)
		self.assertNotIn("table-striped", self.vue)


if __name__ == "__main__":
	unittest.main()
