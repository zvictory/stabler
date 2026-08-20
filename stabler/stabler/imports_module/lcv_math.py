"""Pure, frappe-free Landed Cost Voucher aggregation (critique M8 + audit §3).

Builds the LCV taxes rows from the Container Cost Lines of a GRN's Commercial
Invoice. The frappe-facing wiring (fetch cost lines, resolve the FX rate for the
GRN completion date, resolve the expense account from Stabler Settings, insert
the DRAFT LCV) lives in ``imports_module/hooks.py``; the aggregation, currency
conversion and exclusion rules live here so they can be unit-tested.

Correctness decisions carried over from the 2026-07-03 GRN gap analysis, fixing
the known bugs in the Django ``create_landed_cost_for_grn`` that must NOT be
replicated:

* **Customs Clearance Fee — full amount, never divided per container.** Cost
  lines are summed as-is; there is no per-container division.
* **No VAT capitalization.** Any component whose name contains "VAT" is
  excluded (import VAT is a recoverable input credit — IAS 2 forbids
  capitalizing it into inventory).
* **No product / CIF freight double-capitalization.** Goods value and the CIF
  freight already embedded in the supplier PI are not cost components by design
  (the Container Cost Line doctype has no such component).
* Distribution basis is a **choice**, defaulting to Amount. Stock UOM is Kg with
  conversion factor 1, so ERPNext's "Qty" basis is distribution by weight: right
  for freight, wrong for the ad-valorem charges (customs duty, excise, insurance,
  bank fees) that dominate this landed cost, where cheap-heavy items absorb far
  more than they cost. The basis is persisted on the source document and frozen
  once a voucher is submitted — see ``resolve_distribution_method``.
* Expense account is a single configurable account (Stabler Settings), never the
  hardcoded "Stock Adjustment - MSA".
"""

from __future__ import annotations

#: Fields on a Container Cost Line that name the document the cost came from.
#: A line carrying any of them was written by an attribution path; a line
#: carrying none of them was typed in by an operator. The distinction — not the
#: particular field — is what ``supersede_billed`` and ``vouchered_hand_line``
#: decide on, so a new attribution source is added HERE and both rules follow.
#: Reading only ``purchase_invoice`` would make every other source look
#: hand-typed, which supersedes the wrong side and lets the same money reach
#: stock valuation twice.
SOURCE_FIELDS = ("purchase_invoice", "import_expense")


def source_document(line) -> str:
	"""Name of the document a cost line came from, or ``""`` when hand-typed."""
	for field in SOURCE_FIELDS:
		ref = (line.get(field) or "").strip()
		if ref:
			return ref
	return ""


def is_vat_component(component) -> bool:
	"""True for any VAT component (excluded from the landed-cost build)."""
	return "vat" in str(component or "").lower()


def is_uzbekistan_customs_duty(component) -> bool:
	"""True for the Uzbekistan import-duty cost component (superseded by a GTD).

	Only the Uzbek duty is replaced by a cleared customs declaration — Iran-side
	duty stays a real landed cost, so it is deliberately not matched here.
	"""
	c = str(component or "").lower()
	return "uzbek" in c and "customs duty" in c


def _component_key(name) -> str:
	"""Fold a charge description to the identity the netting matches on.

	``capitalized_components`` reads the component out of a Landed Cost Taxes and
	Charges ``description``, which is editable Small Text on the voucher. An
	accountant who lowercases it or lets a double space in would otherwise score
	``already = 0``, and the whole declaration gets offered a second time — the
	exact double capitalization this module exists to prevent, reachable by
	editing one text box.

	Case and whitespace only. NOT a prefix or fuzzy match: "Uzbekistan Customs
	Duty Penalty" is a different charge, and folding it in would be the opposite
	failure — a genuinely new cost silently swallowed.
	"""
	return " ".join(str(name or "").split()).casefold()


def _by_component(capitalized) -> dict[str, float]:
	"""Re-key what the vouchers posted, summing descriptions that fold together."""
	out: dict[str, float] = {}
	for name, amount in (capitalized or {}).items():
		key = _component_key(name)
		if key:
			out[key] = round(out.get(key, 0.0) + float(amount or 0), 2)
	return out


def apply_gtd_customs_precedence(
	components, gtd_duty, gtd_excise, gtd_present, capitalized=None, translate=None
) -> tuple[dict, list[str]]:
	"""Let a cleared customs declaration (GTD) supersede cost-line Uzbek duty.

	When an Approved + cleared GTD exists for the CI, its ``duty_amount`` and
	``excise_amount`` (already in UZS = company currency) REPLACE any
	"Uzbekistan Customs Duty" component aggregated from the Container Cost Lines,
	so the two sources are never double-counted. VAT is never added from either
	source (recoverable input credit — see ``aggregate_components``).

	``capitalized`` is what the vouchers already posted against this receipt
	charged per component. It exists because the declaration is a standing figure,
	not a document that arrives once: a cost line is stamped with ``lcv_ref`` and
	is invisible to every later build, but the GTD is re-read on each one. Without
	netting, a second voucher offers the same customs payment again — in full —
	and submitting it capitalizes it twice into stock valuation. Only the
	declaration's OWN two components are netted; everything else is already
	protected by its stamp, and netting it here would swallow a genuinely new
	cost that happened to match an old one.

	Returns ``(new_components, warnings)``. A warning is emitted when BOTH a
	cost-line Uzbek duty AND a cleared GTD were present (the GTD won; the operator
	should confirm the cost line was not meant as a separate charge), and whenever
	a declared amount is reduced or dropped by what is already capitalized.
	"""
	t = translate or (lambda s: s)
	warnings: list[str] = []
	if not gtd_present:
		return dict(components), warnings

	out: dict[str, float] = {}
	had_cost_line_duty = False
	for comp, amt in components.items():
		if is_uzbekistan_customs_duty(comp):
			had_cost_line_duty = True
			continue  # superseded by the GTD
		out[comp] = amt

	posted = _by_component(capitalized)
	for comp, declared in (
		("Uzbekistan Customs Duty", gtd_duty),
		("Uzbekistan Excise", gtd_excise),
	):
		declared = round(float(declared or 0), 2)
		already = round(float(posted.get(_component_key(comp)) or 0), 2)
		# A charge row's ``amount`` carries no non-negative validation and the draft
		# voucher is editable, so ``already`` can arrive negative. Left alone it
		# makes ``declared - already`` EXCEED the declaration, and every branch
		# below keys on ``already > 0`` — so a negative used to fall through all of
		# them straight into the plain add. Clamp at the source: nothing capitalized
		# is the honest reading of a negative total, and it is the safe one.
		if already < 0:
			warnings.append(
				t(
					"{0}: the vouchers on this receipt total a negative {1} for this component, "
					"which cannot be what stock valuation carries. Treated as nothing capitalized "
					"and the full declaration offered — check the landed cost vouchers before submitting."
				).format(t(comp), _money(already))
			)
			already = 0.0
		remaining = round(declared - already, 2)

		if already > 0 and remaining < 0:
			# Never post the difference as a negative charge: a negative amount on
			# a Landed Cost Voucher writes a negative valuation adjustment into the
			# stock ledger of every receipt line it touches. Undoing an
			# over-capitalization means cancelling the voucher that caused it,
			# which carries a GL reversal — an operator's decision, not a silent one.
			warnings.append(
				t(
					"{0}: the customs declaration ({1}) is below the {2} already capitalized on this receipt. "
					"Nothing was added — cancel the landed cost voucher that over-charged it instead."
				).format(t(comp), _money(declared), _money(already))
			)
			continue

		if already > 0 and remaining == 0:
			warnings.append(
				t("{0}: the customs declaration ({1}) is already fully capitalized on this receipt.").format(
					t(comp), _money(declared)
				)
			)
			continue

		if already > 0:
			warnings.append(
				t(
					"{0}: {1} of the customs declaration's {2} is already capitalized on this receipt; "
					"only the remaining {3} was added."
				).format(t(comp), _money(already), _money(declared), _money(remaining))
			)

		if remaining > 0:
			out[comp] = round(out.get(comp, 0.0) + remaining, 2)

	if had_cost_line_duty:
		warnings.append(
			t(
				"Both a Uzbekistan Customs Duty cost line and a cleared customs declaration "
				"were present; the declaration's duty/excise took precedence and the cost-line "
				"duty was dropped to avoid double counting."
			)
		)
	return out, warnings


def _money(amount) -> str:
	"""Group an amount for a warning string.

	No currency symbol: this module is deliberately frappe-free and knows nothing
	about the company currency. Every amount reaching it is already in that
	currency, which the surrounding UI states.
	"""
	return "{:,.2f}".format(round(float(amount or 0), 2))


def line_company_amount(currency, amount, rates, company_currency) -> float | None:
	"""Amount of one cost line in company currency.

	Lines already in the company currency pass through untouched; everything else
	is converted with ``rates`` (the rate for the GRN completion date,
	fetched frappe-side and passed in as a map).
	"""
	amt = float(amount or 0)
	if (currency or company_currency) == company_currency:
		return round(amt, 2)
	rate = rates.get(currency)
	if not rate or rate <= 0:
		return None
	return round(amt * float(rate), 2)


def unvaluable_line_names(cost_lines, rates, company_currency) -> set:
	"""Names of eligible lines no rate could value — they must stay UNSTAMPED.

	``aggregate_components`` silently drops a line whose currency has no rate, so
	its money reaches no voucher. Stamping such a row with ``lcv_ref`` would then
	hide it from ``unconsumed`` forever: the cost would disappear from valuation
	permanently, with only a log line as notice. The caller stamps
	``source_rows - unvaluable_line_names(...)``.

	VAT and GTD-superseded duty are deliberately NOT here. Those are excluded on
	purpose and must never be picked up by a later voucher, so consuming them is
	the correct outcome; a missing rate is a transient data gap, not a decision.
	"""
	out = set()
	for ln in unconsumed(cost_lines):
		if is_vat_component(ln.get("cost_component") or "Other"):
			continue
		if line_company_amount(ln.get("currency"), ln.get("amount"), rates, company_currency) is None:
			out.add(ln.get("name"))
	out.discard(None)
	return out


def unconsumed(cost_lines) -> list[dict]:
	"""Cost lines eligible for a (new) LCV: included and not yet vouchered.

	Enables the multi-LCV / late-cost flow — a line consumed by an earlier LCV
	carries a non-empty ``lcv_ref`` and is skipped so an additional LCV only
	picks up the delta.
	"""
	out = []
	for ln in cost_lines:
		if not ln.get("include_in_landed_cost"):
			continue
		if (ln.get("lcv_ref") or "").strip():
			continue
		out.append(ln)
	return out


def supersede_billed(cost_lines) -> tuple[list[dict], list[str]]:
	"""Drop hand-typed lines that an attributed carrier bill already accounts for.

	Same precedence shape as ``apply_gtd_customs_precedence``: when a more
	authoritative source for a cost exists, it REPLACES the hand-typed figure
	instead of adding to it. Here the authoritative source is a document — the
	carrier's own Purchase Invoice, or the Import Expense a cash payment was
	recorded on — named on the line by one of ``SOURCE_FIELDS``.

	This is the guard for the double-count that hand-attribution made possible.
	The same freight can exist twice on one container — once typed in by an
	operator so it reaches the landed cost, once as the transporter's bill so it
	reaches A/P — and the moment the bill starts capitalizing, an unguarded
	aggregate charges that money to valuation twice.

	Scoped per ``(container, cost_component)``: a billed Freight line on one
	container says nothing about a hand-typed Freight line on another, so callers
	MUST put ``container`` on every dict. Omitting it collapses every container
	into one bucket and supersedes across containers that never met.

	Two bills of the same component on one container are both kept — they are two
	real invoices, not a duplicate. Only the hand-typed line yields.

	Returns ``(kept_lines, warnings)``; a warning names each dropped line so the
	operator can confirm it was not meant as a separate charge.
	"""
	# Keyed by (container, component) and holding the document that covers it, so
	# the warning can name what to unlink. With two possible sources "the bill"
	# is no longer a description an operator can act on.
	billed: dict[tuple, str] = {}
	for ln in cost_lines:
		source = source_document(ln)
		if source:
			billed.setdefault((ln.get("container"), ln.get("cost_component")), source)
	if not billed:
		return list(cost_lines), []

	kept: list[dict] = []
	warnings: list[str] = []
	for ln in cost_lines:
		if source_document(ln):
			kept.append(ln)
			continue
		key = (ln.get("container"), ln.get("cost_component"))
		if key in billed:
			warnings.append(
				"A hand-entered {0} cost line on container {1} was dropped: {2} already "
				"covers that component. Remove that link if the cost line was meant as a "
				"separate charge.".format(
					ln.get("cost_component") or "Other", ln.get("container") or "?", billed[key]
				)
			)
			continue
		kept.append(ln)
	return kept, warnings


def vouchered_hand_line(cost_lines, container, cost_component) -> str | None:
	"""Voucher that already capitalized a hand-typed *cost_component* on *container*.

	Returns the ``lcv_ref`` of the first line that matches, or ``None``.

	``supersede_billed`` is the same precedence rule applied at voucher-build
	time, and it can only drop a hand-typed guess that is still a candidate.
	Once a Landed Cost Voucher has consumed that guess the line carries an
	``lcv_ref``, ``unconsumed`` skips it forever, and a bill linked afterwards
	inserts a second line for the same money that the next voucher capitalizes
	again — the same cost in stock valuation twice, with no warning anywhere.
	This is the read the link path uses to refuse writing that second line.

	Only hand-typed lines count. A line naming a document in ``SOURCE_FIELDS`` is
	another document's money, and two carriers on one leg are two real costs, not
	a duplicate — exactly the case ``supersede_billed`` also keeps.

	Matched on the exact component, never a family: ``Freight`` (the sea leg)
	and ``Cross-Border Transport`` (the trucking leg) are different real costs
	that one container routinely carries both of. Widening the match would trade
	a visible over-capitalization for a silent under-capitalization, and a
	vouchered line never comes back.
	"""
	for ln in cost_lines:
		if ln.get("container") != container:
			continue
		if not ln.get("include_in_landed_cost"):
			continue
		if source_document(ln):
			continue
		if ln.get("cost_component") != cost_component:
			continue
		ref = (ln.get("lcv_ref") or "").strip()
		if ref:
			return ref
	return None


def aggregate_components(cost_lines, rates, company_currency, translate=None) -> tuple[dict, list[str]]:
	"""Aggregate eligible cost lines into ``{component: company_amount}`` (>0).

	Excludes VAT components; sums full amounts (no clearance-fee division).

	``translate`` is how a warning that reaches a user gets into their language
	without dragging frappe into this module: callers on an API boundary pass
	``frappe._``, and the *template* — not the interpolated sentence — is the
	catalog key, so it is looked up before ``.format`` fills in the currency.
	Callers that only log (the build path) leave it out and get English.
	"""
	t = translate or (lambda s: s)
	agg: dict[str, float] = {}
	warnings: list[str] = []
	unvaluable: dict[str, list[str]] = {}
	for ln in unconsumed(cost_lines):
		comp = ln.get("cost_component") or "Other"
		if is_vat_component(comp):
			continue
		amt = line_company_amount(ln.get("currency"), ln.get("amount"), rates, company_currency)
		if amt is None:
			# One warning per currency, not per line: a CI with twelve USD freight
			# lines and no rate is one problem, not twelve alerts on the screen.
			unvaluable.setdefault(str(ln.get("currency")), []).append(comp)
			continue
		if amt == 0:
			continue
		agg[comp] = round(agg.get(comp, 0.0) + amt, 2)

	for currency, comps in sorted(unvaluable.items()):
		warnings.append(
			t(
				"Could not value {0} in {1}: no known exchange rate, so it is excluded from the voucher."
			).format(", ".join(sorted(set(comps))), currency)
		)

	components = {k: v for k, v in agg.items() if v > 0}
	return components, warnings


#: Distribution bases a user may choose. ERPNext v15 types
#: ``Landed Cost Voucher.distribute_charges_based_on`` as
#: ``Literal["Qty", "Amount", "Distribute Manually"]``; "Distribute Manually" is
#: deliberately NOT offered, because ERPNext refuses to submit such a voucher
#: with more than one charge row (``landed_cost_voucher.py`` ``on_submit``) and a
#: landed cost build here routinely carries several.
DISTRIBUTION_METHODS = ("Qty", "Amount")

#: Everything ERPNext itself stores in that field. A voucher created in the Desk
#: may legitimately carry "Distribute Manually", and the freeze rule has to read
#: such a basis back faithfully even though nobody may choose it here.
ERPNEXT_DISTRIBUTION_METHODS = ("Qty", "Amount", "Distribute Manually")

#: Value, not weight, is the honest default: stock UOM is Kg at conversion factor
#: 1, so "Qty" distributes by weight, and on the real product mix that pushes far
#: more of the ad-valorem charges (customs duty, excise, insurance, bank fees)
#: onto cheap-heavy items than they are worth. Freight is the case that wants
#: weight, which is why "Qty" stays selectable rather than being removed.
DEFAULT_DISTRIBUTION_METHOD = "Amount"


def normalize_distribution_method(value, allowed=ERPNEXT_DISTRIBUTION_METHODS):
	"""Canonical spelling of *value*, or ``None`` when it names no known basis.

	Case and surrounding whitespace only — the stored value has to reach ERPNext
	spelled exactly as its Select options are, and "amount" from a hand-written
	API call is the same instruction as "Amount". Anything else is rejected rather
	than guessed: a basis this module does not recognize must never be passed
	through to a voucher.
	"""
	text = " ".join(str(value or "").split())
	if not text:
		return None
	for method in allowed:
		if text.casefold() == method.casefold():
			return method
	return None


def validate_distribution_method(value) -> str:
	"""Canonical form of a *selectable* basis, or ``ValueError``.

	The set here is narrower than what ERPNext accepts (see
	``DISTRIBUTION_METHODS``). Raises rather than falling back to a default: this
	is the guard on an explicit user choice, and silently storing something other
	than what was asked for is how a voucher ends up on a basis nobody picked.
	Callers on a frappe boundary catch this and re-raise it translated.
	"""
	method = normalize_distribution_method(value, DISTRIBUTION_METHODS)
	if method is None:
		raise ValueError(
			"Unknown landed cost distribution method: {0!r}. Expected one of: {1}.".format(
				value, ", ".join(DISTRIBUTION_METHODS)
			)
		)
	return method


#: Only a SUBMITTED voucher freezes the distribution basis. A draft has capitalized
#: nothing for a later charge to net against, and a cancelled one has already given
#: back what it capitalized (``release_cost_lines_for_lcv`` clears ``lcv_ref``), so
#: its lines return to the next build. Named and tested here rather than living only
#: inside the SQL predicate, so widening it to "anything not cancelled" — the obvious
#: wrong guess — fails a test instead of quietly locking every draft.
LOCKING_DOCSTATUS = 1


def locks_distribution(docstatus) -> bool:
	"""Whether a voucher in this docstatus freezes the basis for later vouchers."""
	try:
		return int(docstatus) == LOCKING_DOCSTATUS
	except (TypeError, ValueError):
		return False


def resolve_distribution_method(persisted, locked_method=None, default=DEFAULT_DISTRIBUTION_METHOD) -> str:
	"""The basis the next voucher must be built on.

	Precedence: ``locked_method`` (the basis of a submitted voucher already
	standing against these receipts) → ``persisted`` (what the operator chose on
	the source document) → ``default``.

	The lock wins over a later choice because ``apply_gtd_customs_precedence``
	nets a late customs declaration against what earlier vouchers already
	capitalized. Those amounts were spread on the first voucher's basis, so
	posting the remainder on a different one distributes a correction over a
	distribution it does not match — item-level valuations that no longer add up
	to the money actually spent, with nothing on either voucher saying why.

	A locked basis is honored even when it is one this module would not offer
	(a "Distribute Manually" voucher entered in the Desk): reporting the frozen
	basis truthfully is the point, and a caller that quietly substituted a
	different one would reintroduce exactly the incoherence above. ``persisted``
	is read against the offered set only, so a stored value nobody may choose is
	treated as no choice at all.
	"""
	locked = normalize_distribution_method(locked_method)
	if locked:
		return locked
	chosen = normalize_distribution_method(persisted, DISTRIBUTION_METHODS)
	if chosen:
		return chosen
	return normalize_distribution_method(default) or DEFAULT_DISTRIBUTION_METHOD


def build_lcv_payload(
	*,
	company,
	purchase_receipts,
	components,
	expense_account,
	distribute_based_on="Qty",
	receipt_document_type="Purchase Receipt",
):
	"""Build the DRAFT Landed Cost Voucher dict.

	``purchase_receipts`` is a list of submitted PR names; ``components`` is the
	``{component: amount}`` map from ``aggregate_components``. Returns ``None``
	when there is nothing to voucher (no PRs or no costs). ``docstatus`` is never
	set — the accountant reviews and submits (valuation repost caution).

	``distribute_based_on`` is what every caller should resolve with
	``resolve_distribution_method`` and pass explicitly. The "Qty" default is the
	historical behavior and is kept only so a caller not yet moved over builds
	what it built before instead of silently changing basis; it is NOT the system
	default, which is ``DEFAULT_DISTRIBUTION_METHOD``.

	``receipt_document_type`` names the kind of document the charge capitalizes
	onto. ERPNext takes a Purchase Receipt, a Stock Entry or a Purchase Invoice,
	and accepts the invoice on the single condition that it updates stock
	(``validate_receipt_documents``). This was a literal, which made the whole
	builder unusable wherever the stock document is an ``update_stock`` invoice
	rather than a receipt — the CI → invoice route, which is every import on msa.
	It defaults to "Purchase Receipt" so the truck-receipt route keeps building
	exactly what it built before.
	"""
	if not purchase_receipts or not components:
		return None
	return {
		"doctype": "Landed Cost Voucher",
		"company": company,
		"distribute_charges_based_on": distribute_based_on,
		"purchase_receipts": [
			{"receipt_document_type": receipt_document_type, "receipt_document": pr}
			for pr in purchase_receipts
		],
		"taxes": [
			{"expense_account": expense_account, "description": comp, "amount": amt}
			for comp, amt in components.items()
		],
	}
