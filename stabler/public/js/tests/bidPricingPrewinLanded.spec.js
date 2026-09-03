import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/BidPricing.vue"), "utf8");
const board = readFileSync(resolve(here, "../pages/tender/PoControlBoard.vue"), "utf8");

/**
 * ADR-605 — where the pre-win landed figure on the bid-pricing card comes from.
 *
 * `landed_goods` defaulted from the deal's Purchase Orders, and pre-win there are
 * none: the box opened at zero and the only affordance under it read "Use POs'
 * landed: 0 · 0 PO". So the officer priced the bid from memory, at exactly the
 * moment Zafar's pre-win rule says the number has to be quick.
 *
 * The lot's sourcing decision has already named a quotation by then and that
 * quotation carries the only pre-win landed number anyone typed. Two things the
 * screen must never do: take the CHEAPEST bid (a fact about the comparison, not a
 * decision — the field sits right beside the chosen one on the same doctype), and
 * overwrite a figure the officer typed, which is what the bid was actually quoted on.
 *
 * The card renders every figure with `props.currency`, which `PoControlBoard.vue`
 * fills from `workspace.overview.currency` — `deal_intake`'s `base_ccy`, the
 * company's `default_currency`. The server-side estimate is base currency too, so
 * the two agree; that is asserted here because it is the assumption the pre-fill
 * rests on, and it is one prop away from being wrong.
 */
describe("the pre-win landed estimate is offered, not invented", () => {
	it("reads the server's estimate, never a 'cheapest' field", () => {
		// WHAT WOULD MAKE THIS FAIL: pricing off `cheapest_quotation` — the field
		// sitting right beside the chosen one on Tender Sourcing Decision. A lot's
		// winner is regularly dearer for a reason the comparison cannot see, so
		// the cheapest total is a number nobody chose.
		expect(src).toMatch(/quotation_landed_estimate/);
		// Property reads only; the word may appear in prose explaining the rule.
		expect(src.replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, "")).not.toMatch(/\bcheapest/i);
	});

	it("names the quotation the figure came from", () => {
		// WHAT WOULD MAKE THIS FAIL: a bare number. An estimate whose source is
		// not on screen cannot be checked, and the officer has no way to tell a
		// pre-win estimate from a post-win PO sum.
		expect(src).toMatch(/quotation_landed_source/);
		expect(src).toMatch(/t\("Pre-win estimate"\)/);
	});

	it("tells the officer what to do when no quotation has been chosen", () => {
		// WHAT WOULD MAKE THIS FAIL: an empty box, or "no estimate available".
		// The action is one screen away and naming it is the whole point.
		expect(src).toMatch(/t\("Select a quotation for this lot in Sourcing"\)/);
	});

	it("links to the sourcing workspace for this lot", () => {
		// WHAT WOULD MAKE THIS FAIL: naming the action without offering it, or
		// linking without the deal so the officer lands on a lot picker.
		expect(src).toMatch(/name:\s*'tender-sourcing'/);
		expect(src).toMatch(/query:\s*\{\s*deal(:|\s*\})/);
	});

	it("offers the estimate as a link rather than forcing it over a typed figure", () => {
		// The server pre-fills `landed_goods` only when the STORED field is empty.
		// WHAT WOULD MAKE THIS FAIL: `apply()` — which runs on every load and after
		// every save — writing the estimate into the input. That re-prices a bid
		// that was already quoted, on a page the officer only opened to read.
		const apply = src.slice(src.indexOf("function apply("), src.indexOf("async function load()"));
		expect(apply).not.toMatch(/landed_goods\s*=\s*[^\n;]*quotation_landed_estimate/);
		// It must still be reachable in one click, or the estimate is decoration.
		expect(src).toMatch(/function useLandedFromQuotation\(\)/);
		expect(src).toMatch(/@click\.prevent="useLandedFromQuotation"/);
	});

	it("keeps the post-win PO affordance for lots that have one", () => {
		// WHAT WOULD MAKE THIS FAIL: replacing "Use POs' landed" instead of
		// sitting beside it. Post-win the PO sum is the operational record and
		// outranks any estimate.
		expect(src).toMatch(/useLandedFromPOs/);
		expect(src).toMatch(/refs\.po_count/);
	});
});

describe("an estimate that is itself incomplete says so where it is offered", () => {
	it("shows how many charge lines carry no rate", () => {
		// ADR-605 review, item 4. Those lines are ALREADY excluded from the figure
		// beside this label, and the bid price is computed from that figure.
		// WHAT WOULD MAKE THIS FAIL: rendering the amount alone, which reads as a
		// complete estimate and is short by whatever the flagged lines hold.
		expect(src).toMatch(/refs\.quotation_landed_unvalued/);
		expect(src).toMatch(/t\("incomplete: \{count\} line\(s\) without a rate"/);
	});

	it("keeps the warning out of the way when there is nothing to warn about", () => {
		// WHAT WOULD MAKE THIS FAIL: an unconditional badge, which trains the
		// officer to ignore it on the estimates that really are short.
		expect(src).toMatch(/v-if="refs\.quotation_landed_unvalued"/);
	});
});

describe("a quotation the user may not read is not a quotation nobody picked", () => {
	it("says the estimate is gated rather than asking for a decision already made", () => {
		// ADR-605 review, item 5. The permission-denied branch must come BEFORE
		// the empty state, or a sourcing officer is told to go and select a
		// quotation that is already selected — an instruction they cannot carry
		// out, hiding the real obstacle.
		// Search the ATTRIBUTE, not the bare name: `refs.quotation_landed_denied`
		// also appears twice in <script>, above the whole template, so an index
		// taken from the plain name is always smaller than the empty state's and
		// the comparison can never fail. This assertion was written that way and
		// survived the branch being moved to the bottom of the chain.
		const denied = src.indexOf('v-else-if="refs.quotation_landed_denied"');
		const empty = src.indexOf("Select a quotation for this lot in Sourcing");
		expect(denied).toBeGreaterThan(-1);
		expect(empty).toBeGreaterThan(-1);
		expect(denied).toBeLessThan(empty);
	});

	it("names the quotation it cannot read", () => {
		// WHAT WOULD MAKE THIS FAIL: a bare "not permitted". The officer needs to
		// know WHICH record to ask for access to.
		expect(src).toMatch(
			/t\("This lot is priced from \{quotation\}, which you do not have permission to read"/,
		);
	});
});

describe("the card's currency is the one the estimate is denominated in", () => {
	it("is mounted with the workspace overview currency", () => {
		// `deal_intake` returns `default_currency` of the Company as `currency`,
		// and `_quotation_landed_estimate` sums `base_grand_total` — both company
		// currency. WHAT WOULD MAKE THIS FAIL: passing a quotation's or a sales
		// order's currency here, which would label a base-currency figure with a
		// transaction currency — the ADR-605 defect, one screen over.
		expect(board).toMatch(/<BidPricing[^>]*:currency="ccy"/);
		expect(board).toMatch(/workspace\.value\?\.overview\?\.currency/);
	});
});
