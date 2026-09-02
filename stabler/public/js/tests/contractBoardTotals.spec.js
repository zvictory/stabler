import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");

/**
 * A column total never adds two currencies (prompt 18, acceptance row C13 — the
 * package's only money-math defect, as opposed to a labelling one).
 *
 * As measured 2026-09-02 the header ran
 *   formatMoney(colTotal(s.name), currency, user.language)
 * where `colTotal` summed each card's `contract_value` — the TRANSACTION-currency
 * figure, `rounded_total or grand_total` (api/tender.py) — and `currency` is the
 * session's, i.e. the active company's default (stores/session.js:41). A column
 * holding one UZS contract and one USD contract printed their numeric sum under
 * the company's symbol. The cards beneath it were right all along: each renders
 * formatMoney(c.contract_value, c.currency, …).
 *
 * Prompt 18 left three ways out — a base-currency sum, a per-currency breakdown,
 * or no total. This is the breakdown, chosen because it converts nothing:
 * .claude/rules/10-frontend.md renders amounts in their own currency and grants
 * exactly three documented exceptions, none of them this board. In the ordinary
 * case — every contract in a column in one currency — it prints the single line
 * it printed before.
 *
 * DOM-less per vitest.config.mjs: `colTotals` is lifted from the source and run
 * for real, because "these two numbers were never added together" is a claim
 * about arithmetic.
 */

/** Lift `function colTotals()` and bind it to a fake cardsByStage. */
function liftColTotals(byStage) {
	const fn = src.match(/^function colTotals\([\s\S]*?^\}/m);
	expect(fn, "SalesOrderBoard.vue has no top-level colTotals()").not.toBeNull();
	return new Function("cardsByStage", `${fn[0]}\nreturn colTotals;`)({ value: byStage });
}

const card = (currency, contract_value) => ({ currency, contract_value });

describe("C13 — a column total never adds two currencies", () => {
	it("keeps one currency's contracts as one line", () => {
		// WHAT WOULD MAKE THIS FAIL: splitting a single-currency column into
		// several lines. The ordinary column on this board holds Uzbek state
		// contracts, all in UZS; the fix must not make the common case noisier
		// than the one it replaced.
		const colTotals = liftColTotals({
			Invoicing: [card("UZS", 2_270_000_000), card("UZS", 1_650_000_000)],
		});
		expect(colTotals("Invoicing")).toEqual([{ ccy: "UZS", total: 3_920_000_000 }]);
	});

	it("never folds two currencies into one number", () => {
		// WHAT WOULD MAKE THIS FAIL: the old `reduce((a, c) => a + c.contract_value)`.
		// 1 650 000 000 UZS plus 12 000 USD is not 1 650 012 000 of anything, and
		// the reader has no way to see that from a single formatted figure — the
		// symbol says the company's currency and the digits say neither.
		const colTotals = liftColTotals({
			Delivery: [card("UZS", 1_650_000_000), card("USD", 12_000), card("UZS", 350_000_000)],
		});
		expect(colTotals("Delivery")).toEqual([
			{ ccy: "USD", total: 12_000 },
			{ ccy: "UZS", total: 2_000_000_000 },
		]);
	});

	it("orders the lines by currency code, not by which card came first", () => {
		// WHAT WOULD MAKE THIS FAIL: returning Map insertion order. Two columns
		// holding the same currencies would then list them differently depending on
		// which contract the server happened to return first, so the reader cannot
		// compare two columns by position — and the order would change under them
		// when an unrelated contract is added.
		const colTotals = liftColTotals({
			A: [card("USD", 1), card("EUR", 2), card("UZS", 3)],
			B: [card("UZS", 3), card("USD", 1), card("EUR", 2)],
		});
		expect(colTotals("A").map((x) => x.ccy)).toEqual(["EUR", "USD", "UZS"]);
		expect(colTotals("B")).toEqual(colTotals("A"));
	});

	it("prints nothing for an empty column rather than a zero", () => {
		// WHAT WOULD MAKE THIS FAIL: returning [{ccy: <session currency>, total: 0}].
		// Five of the seven default stages are empty on the seed; a row of "0 сўм"
		// headers asserts a currency for columns that contain no money at all.
		const colTotals = liftColTotals({ New: [], Paid: undefined });
		expect(colTotals("New")).toEqual([]);
		expect(colTotals("Paid")).toEqual([]);
		expect(colTotals("NoSuchStage")).toEqual([]);
	});

	it("does not silently label an unknown currency as the company's", () => {
		// WHAT WOULD MAKE THIS FAIL: a `c.currency || currency.value` fallback. A
		// card the server sent without a currency would be added to the company's
		// pile — the exact substitution this row exists to remove, reintroduced as
		// a defensive default. formatMoney falls back to a bare number for an
		// unknown code (money.js:175-179), so the figure still renders; it just
		// does not claim a unit nobody established.
		const colTotals = liftColTotals({ New: [card("UZS", 100), card("", 7)] });
		expect(colTotals("New")).toEqual([
			{ ccy: "", total: 7 },
			{ ccy: "UZS", total: 100 },
		]);
	});

	it("formats each line in its own currency, never the session's", () => {
		// WHAT WOULD MAKE THIS FAIL: keeping `currency` — the session ref — as the
		// second argument to formatMoney in the header. That single token is the
		// whole defect: it is what made a transaction-currency sum look like a
		// company-currency total.
		const header = src.slice(
			src.indexOf("colTotals(s.name)"),
			src.indexOf("</span>", src.indexOf("colTotals(s.name)"))
		);
		expect(header).toMatch(/formatMoney\(\s*tot\.total,\s*tot\.ccy/);
		expect(header).not.toMatch(/formatMoney\([^)]*\bcurrency\b\s*,/);
	});

	it("no longer reads the session currency at all", () => {
		// WHAT WOULD MAKE THIS FAIL: pulling `currency` back out of the session
		// store. Stronger than checking the one call site: with the binding gone,
		// there is no company-currency label in this component for a future edit to
		// reach for, and lint fails the moment one is destructured and unused.
		const destructured = src.match(/const \{([^}]*)\} = storeToRefs\(session\);/);
		expect(destructured, "the session destructure has moved").not.toBeNull();
		expect(destructured[1]).not.toMatch(/\bcurrency\b/);
	});

	it("leaves each card showing its own currency", () => {
		// WHAT WOULD MAKE THIS FAIL: "fixing" the mismatch by converting the cards
		// to one currency instead. The cards were never wrong, and converting them
		// would need a live rate and a fourth exception to the currency rule.
		expect(src).toMatch(/formatMoney\(c\.contract_value, c\.currency, user\.language\)/);
	});
});
