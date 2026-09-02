import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { totalsByCurrency } from "../composables/money.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(here, "..", rel), "utf8");
const crm = read("pages/tender/TenderCrm.vue");

/**
 * The Tender CRM shows each deal in the currency it was entered in.
 *
 * Reported from a live screen on 2026-09-02: a deal entered as USD 15 000
 * rendered "15 000,00 сўм". `crm_board` stamped `"currency": base_ccy` onto
 * every card, ignoring the currency the intake had stored all along. The server
 * half is pinned in tests/test_tender_crm_card_currency.py.
 *
 * The client half is the consequence. While every card claimed the company
 * currency the lane totals and the pipeline KPI were internally consistent and
 * only their LABEL was a lie; reading the deal's real currency turns them into
 * arithmetic across unlike units. Both now go through `totalsByCurrency`, whose
 * own behaviour is tested in moneyTotalsByCurrency.spec.js.
 *
 * DOM-less per vitest.config.mjs.
 */

/** Every `name(...)` call in `src`, with nested parentheses balanced. */
function callSites(src, name) {
	const out = [];
	const needle = `${name}(`;
	for (let i = src.indexOf(needle); i !== -1; i = src.indexOf(needle, i + 1)) {
		let depth = 0;
		for (let j = i + name.length; j < src.length; j++) {
			if (src[j] === "(") depth++;
			else if (src[j] === ")" && --depth === 0) {
				out.push(src.slice(i, j + 1));
				break;
			}
		}
	}
	return out;
}

describe("a deal renders in its own currency", () => {
	it("formats the card, the drawer and the lot lines from the deal's currency", () => {
		// WHAT WOULD MAKE THIS FAIL: any of these dropping back to the bare session
		// `currency`. Each is a place the same deal appears, and a deal that is USD
		// on the card and сўм in the drawer is worse than one that is wrong in both
		// — the reader cannot tell which screen to believe.
		//
		// Balanced-paren scan, not /formatMoney\([^)]*\)/: that stops at the first
		// close paren, so `formatMoney(laneTotal(l.id), currency, …)` came back as
		// `formatMoney(laneTotal(l.id)` and this test passed over the very site it
		// exists to catch. Found by writing it red first and getting green.
		const sites = callSites(crm, "formatMoney");
		const sessionOnly = sites.filter((s) => /,\s*currency(\.value)?\s*,/.test(s));
		expect(
			sessionOnly,
			`formatMoney sites still labelled with the session currency: ${sessionOnly}`
		).toEqual([]);
	});

	it("still falls back to the company currency when the deal names none", () => {
		// WHAT WOULD MAKE THIS FAIL: removing the fallback and rendering a bare
		// number for a deal saved before the picker existed. `c.currency || currency`
		// is the honest shape here: the server already resolves the fallback, and
		// this is the client agreeing with it rather than inventing a second rule.
		expect(crm).toMatch(/c\.currency \|\| currency/);
	});
});

describe("lane totals and the KPI never add two currencies", () => {
	it("computes lane totals per currency", () => {
		// WHAT WOULD MAKE THIS FAIL: the `reduce((sum, c) => sum + c.contract_value)`
		// coming back. A lane holding one USD deal and one UZS deal would print their
		// numeric sum under the company's symbol — the exact figure the screenshot
		// that opened this reported, one level up.
		expect(crm).toMatch(/laneTotals\s*=[\s\S]{0,200}totalsByCurrency\(/);
		expect(
			/\.reduce\(\(sum, c\) => sum \+ \(c\.contract_value/.test(crm),
			"the folding reduce is back"
		).toBe(false);
	});

	it("computes the pipeline KPI per currency", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the KPI on the old reduce while fixing
		// the lanes. The strip sums EVERY open deal, so it is the single most likely
		// place for two currencies to meet, and it is the first number on the page.
		const kpi = crm.slice(crm.indexOf("const kpis = computed"), crm.indexOf('key: "policy"'));
		expect(kpi).toMatch(/totalsByCurrency\(/);
		expect(
			/reduce\(\(s, c\) => s \+ \(c\.contract_value/.test(kpi),
			"the folding reduce is back"
		).toBe(false);
	});

	it("imports the shared helper rather than growing a fourth copy", () => {
		// WHAT WOULD MAKE THIS FAIL: reimplementing the grouping in this file.
		// money.js says of its own precision rule that it is "the single source of
		// truth" — three screens had each written their own copy of the UZS
		// fraction-digit ternary and two of the three were wrong. This is the same
		// rule about the same thing.
		expect(crm).toMatch(
			/import \{[^}]*\btotalsByCurrency\b[^}]*\} from "\.\.\/\.\.\/composables\/money\.js"/
		);
	});

	it("renders one line per currency, keyed so Vue does not reuse them", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering only the first entry, or a v-for with
		// no key. A lane with two currencies would show one of them with no sign that
		// the other exists, which reads as a complete total and is not.
		const lane = crm.slice(
			crm.indexOf("crm-col-sum"),
			crm.indexOf("</div>", crm.indexOf("crm-col-sum"))
		);
		expect(lane).toMatch(/v-for="tot in laneTotals\(l\.id\)"/);
		expect(lane).toMatch(/:key="tot\.ccy"/);
		expect(lane).toMatch(/formatMoney\(\s*tot\.total,\s*tot\.ccy/);
	});

	it("stacks the lines instead of running them together", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving .crm-col-sum as an inline span. Two
		// adjacent spans render with no separator — "15 000,00 $123 000,00 сўм" —
		// which reads as one number and is the defect this change exists to remove,
		// reintroduced as a layout accident rather than an arithmetic one.
		const rule = crm.slice(
			crm.indexOf(".crm-col-sum {"),
			crm.indexOf("}", crm.indexOf(".crm-col-sum {"))
		);
		expect(rule).toMatch(/flex-direction:\s*column/);
	});

	it("agrees with the helper on the screenshot's own numbers", () => {
		// WHAT WOULD MAKE THIS FAIL: nothing in this file — this is the helper, run
		// on the two deals from the report (CRM-DEAL-2026-00107 at 15 000 and
		// -00108 at 123 000). It is here to record what the page should now print
		// where it printed "138 000,00 сўм": two lines, if the two deals are in two
		// currencies, and one if they are not.
		const mixed = [
			{ currency: "USD", contract_value: 15_000 },
			{ currency: "UZS", contract_value: 123_000 },
		];
		expect(totalsByCurrency(mixed, { amount: (c) => c.contract_value })).toEqual([
			{ ccy: "USD", total: 15_000 },
			{ ccy: "UZS", total: 123_000 },
		]);
		const same = mixed.map((c) => ({ ...c, currency: "UZS" }));
		expect(totalsByCurrency(same, { amount: (c) => c.contract_value })).toEqual([
			{ ccy: "UZS", total: 138_000 },
		]);
	});
});

describe("the assignment survives a reload", () => {
	it("binds the picker to a field the board actually sends", () => {
		// WHAT WOULD MAKE THIS FAIL: the server dropping assigned_to from the card
		// payload again. assign_tender always saved it; the card never carried it,
		// so the picker showed the choice until the next load and "— Unassigned —"
		// after it. The user re-assigns, and re-assigning cannot fix a missing read.
		//
		// The client binding only. That the SERVER sends it is
		// tests/test_tender_crm_card_currency.py, which scopes the search to
		// crm_board's own body — searching all of tender.py from here was vacuous:
		// two unrelated endpoints have carried that same key for months, so deleting
		// it from the card payload left this assertion green.
		expect(crm).toMatch(/selectedDeal\.assigned_to/);
		expect(crm).toMatch(/@change="assign\(selectedDeal\.name/);
	});
});
