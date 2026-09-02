import { describe, expect, it } from "vitest";
import { totalsByCurrency } from "../composables/money.js";

/**
 * Adding two amounts is only defined when they are in the same currency.
 *
 * Three screens sum a list of records that each carry their own currency: the
 * contract board's column headers (prompt 18, C13), and the Tender CRM's lane
 * headers and pipeline KPI. Each had grown the same `reduce((a, c) => a + …)`
 * and labelled the result with the SESSION currency — the active company's
 * default — so a lane holding one USD deal and one UZS deal printed their
 * numeric sum under the company's symbol: a figure that is neither, wearing the
 * name of one of them.
 *
 * The CRM's version was hidden until 2026-09-02 because `crm_board` stamped the
 * base currency onto every card regardless of what the deal was entered in, so
 * the sums were internally consistent and only the LABEL was a lie. Reading the
 * deal's real currency is what turned it into arithmetic.
 *
 * This lives in money.js, beside moneyFractionDigits, for the reason that file
 * already states: "the single source of truth". Three copies of a money rule is
 * how the UZS fraction-digit ternary got two of its three copies wrong.
 */

const deal = (currency, value) => ({ currency, value });

describe("totalsByCurrency", () => {
	it("keeps one currency's rows as one total", () => {
		// WHAT WOULD MAKE THIS FAIL: splitting a single-currency list into several
		// lines. That is the ordinary case on every one of the three screens, and
		// the fix must not make it noisier than the single line it replaced.
		expect(totalsByCurrency([deal("UZS", 123_000), deal("UZS", 15_000)])).toEqual([
			{ ccy: "UZS", total: 138_000 },
		]);
	});

	it("never folds two currencies into one number", () => {
		// WHAT WOULD MAKE THIS FAIL: the plain reduce coming back. $15,000 plus
		// 123,000,000 so'm is not 123,015,000 of anything, and a reader given one
		// formatted figure cannot see that — the symbol names one currency and the
		// digits name neither.
		expect(totalsByCurrency([deal("USD", 15_000), deal("UZS", 123_000), deal("USD", 500)])).toEqual([
			{ ccy: "USD", total: 15_500 },
			{ ccy: "UZS", total: 123_000 },
		]);
	});

	it("orders by currency code, not by which row came first", () => {
		// WHAT WOULD MAKE THIS FAIL: returning Map insertion order. Two lanes
		// holding the same currencies would list them differently depending on which
		// deal the server happened to return first, so the reader cannot compare two
		// lanes by position — and the order would shift under them when an unrelated
		// deal is added.
		const a = totalsByCurrency([deal("USD", 1), deal("EUR", 2), deal("UZS", 3)]);
		const b = totalsByCurrency([deal("UZS", 3), deal("USD", 1), deal("EUR", 2)]);
		expect(a.map((x) => x.ccy)).toEqual(["EUR", "USD", "UZS"]);
		expect(b).toEqual(a);
	});

	it("prints nothing for an empty list rather than a zero", () => {
		// WHAT WOULD MAKE THIS FAIL: returning [{ccy: <something>, total: 0}]. Most
		// lanes and columns on both screens are empty; a row of "0 сўм" headers
		// asserts a currency for lanes that hold no money at all.
		expect(totalsByCurrency([])).toEqual([]);
		expect(totalsByCurrency(null)).toEqual([]);
		expect(totalsByCurrency(undefined)).toEqual([]);
	});

	it("does not invent a currency for a row that has none", () => {
		// WHAT WOULD MAKE THIS FAIL: defaulting a missing currency to the company's.
		// That is the exact substitution this helper exists to remove, reintroduced
		// as a defensive fallback. formatMoney falls back to a bare number for an
		// unknown code (money.js formatMoney's catch), so the figure still renders —
		// it just does not claim a unit nobody established.
		expect(totalsByCurrency([deal("UZS", 100), deal("", 7), deal(undefined, 3)])).toEqual([
			{ ccy: "", total: 10 },
			{ ccy: "UZS", total: 100 },
		]);
	});

	it("reads whichever field names the amount", () => {
		// WHAT WOULD MAKE THIS FAIL: hardcoding one screen's field name. The three
		// callers spell it differently — `contract_value` on both boards, and the
		// CRM's KPI sums the same field off a different shape — so the accessor is
		// the caller's to name. Passing it in beats three near-copies of the helper.
		const rows = [
			{ currency: "USD", contract_value: 4 },
			{ currency: "USD", contract_value: 6 },
		];
		expect(totalsByCurrency(rows, { amount: (r) => r.contract_value })).toEqual([
			{ ccy: "USD", total: 10 },
		]);
	});

	it("treats a missing or unparseable amount as nothing, not as NaN", () => {
		// WHAT WOULD MAKE THIS FAIL: adding the raw field. One row with a null
		// amount would turn the whole currency's total into NaN, and formatMoney
		// renders a non-finite number as "—" — so a single incomplete deal would
		// blank the lane total for every complete one beside it.
		expect(totalsByCurrency([deal("USD", null), deal("USD", 5), deal("USD", undefined)])).toEqual([
			{ ccy: "USD", total: 5 },
		]);
	});
});
