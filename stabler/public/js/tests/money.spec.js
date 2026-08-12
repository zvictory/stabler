import { describe, expect, it } from "vitest";

import {
	balanceState,
	formatCompactMoney,
	formatMoney,
	moneyEpsilon,
} from "../composables/money.js";

// Grouping separators come from ICU, and ICU changes them between Node releases
// (ru-RU has shipped both U+00A0 and U+202F). Pinning the exact code point would
// make these tests fail on a Node upgrade without any contract having changed.
// What the rule actually promises is "grouped by a space", so normalise the
// space and assert that.
// (escaped, not literal: ESLint's no-irregular-whitespace rightly objects to a
// raw NBSP in source, and you cannot tell the two apart by eye anyway.)
const norm = (s) => s.replace(/[\u00a0\u202f]/g, " ");

describe("formatMoney — the display half of the money-input contract", () => {
	// ~/.claude/rules/money-input.md fixes these four groupings by name. They are
	// not cosmetic: a Turkish user reading "20.820" as twenty-thousand and a
	// Russian user reading it as twenty-point-eight-two is the failure mode.
	it.each([
		["en", "$20,820.00"],
		["ru", "20 820,00 $"],
		["uz", "20 820,00 $"],
		["uzc", "20 820,00 $"],
		["tr", "$20.820,00"],
	])("groups 20820 the way %s users write it", (language, expected) => {
		expect(norm(formatMoney(20820, "USD", language))).toBe(expected);
	});

	it("treats uz and uzc as ru — Uzbek has no separate CLDR grouping in use here", () => {
		expect(formatMoney(20820, "USD", "uz")).toBe(formatMoney(20820, "USD", "ru"));
		expect(formatMoney(20820, "USD", "uzc")).toBe(formatMoney(20820, "USD", "ru"));
	});

	it("falls back to en-US for a language the SPA does not ship", () => {
		expect(formatMoney(20820, "USD", "de")).toBe(formatMoney(20820, "USD", "en"));
	});

	// The tiyin left circulation in 1994. Showing "38 000 000,00 сўм" is not a
	// rounding nicety, it is two digits of noise on every UZS figure in the app.
	it("prints UZS as a whole number with the native сўм suffix", () => {
		expect(norm(formatMoney(38000000, "UZS", "ru"))).toBe("38 000 000 сўм");
		expect(formatMoney(38000000, "UZS", "en")).toBe("38,000,000 сўм");
	});

	it("rounds UZS rather than truncating it", () => {
		expect(formatMoney(1000.6, "UZS", "en")).toBe("1,001 сўм");
	});

	// USDT is not ISO 4217, so Intl throws on it. The override exists precisely so
	// the crypto-settlement rows do not fall through to the bare toFixed() path.
	it("prints USDT with 2 decimals and a suffix, without Intl throwing", () => {
		expect(formatMoney(1234.5, "USDT", "en")).toBe("1,234.50 USDT");
	});

	it("degrades to a plain 2-decimal number for an unknown currency code", () => {
		expect(formatMoney(1234.5, "XYZQ", "en")).toBe("1234.50");
	});

	// An em dash, never "0.00" and never "NaN": a missing balance and a zero
	// balance mean different things to an accountant.
	it.each([[null], [undefined], [""], ["abc"], [NaN], [Infinity]])(
		"renders %p as an em dash, not as a number",
		(value) => {
			expect(formatMoney(value, "USD", "en")).toBe("—");
		}
	);

	it("renders a real zero as zero", () => {
		expect(formatMoney(0, "USD", "en")).toBe("$0.00");
	});

	it("accepts the numeric strings Frappe returns from the REST layer", () => {
		expect(formatMoney("20820", "USD", "en")).toBe("$20,820.00");
	});
});

describe("formatCompactMoney — dashboard tiles", () => {
	it("compacts in the reader's own language", () => {
		expect(formatCompactMoney(38000000, "USD", "en")).toBe("$38M");
		expect(norm(formatCompactMoney(38000000, "USD", "ru"))).toBe("38 млн $");
	});

	it("keeps the UZS suffix override in compact form too", () => {
		expect(norm(formatCompactMoney(38000000, "UZS", "ru"))).toBe("38 млн сўм");
	});

	it("renders an empty value as an em dash, same as formatMoney", () => {
		expect(formatCompactMoney(null, "USD", "en")).toBe("—");
	});
});

describe("balanceState — who owes whom", () => {
	// The sign convention is the whole point: positive = the party owes us,
	// negative = they paid ahead. Flipping it mislabels every party card.
	it("reads a positive balance as the party owing us", () => {
		expect(balanceState(1500)).toEqual({ state: "owes", abs: 1500 });
	});

	it("reads a negative balance as a prepayment, reported as a positive amount", () => {
		expect(balanceState(-1500)).toEqual({ state: "prepaid", abs: 1500 });
	});

	// Half a cent. Float arithmetic over hundreds of GL rows leaves dust like
	// 0.0000000001; without the threshold every settled party shows as "owes".
	it("treats sub-half-cent dust as settled and zeroes it out", () => {
		expect(balanceState(0.004)).toEqual({ state: "settled", abs: 0 });
		expect(balanceState(-0.004)).toEqual({ state: "settled", abs: 0 });
		expect(balanceState(0)).toEqual({ state: "settled", abs: 0 });
	});

	it("does not swallow half a cent and above", () => {
		expect(balanceState(0.006).state).toBe("owes");
	});

	it.each([[null], [undefined], [""], ["abc"]])("treats %p as settled", (value) => {
		expect(balanceState(value)).toEqual({ state: "settled", abs: 0 });
	});
});

describe("moneyEpsilon — how close counts as equal", () => {
	// These numbers must match `money_epsilon()` in stabler/api/_money.py exactly.
	// The client blocks "Pay Remaining" before the request, the server blocks it
	// again on arrival; if the two thresholds disagree, one of them lies to the
	// user — either a rejected payment the server would have taken, or a form
	// that submits only to throw.
	it("is half a cent for two-decimal currencies", () => {
		expect(moneyEpsilon("USD")).toBe(0.005);
		expect(moneyEpsilon("EUR")).toBe(0.005);
	});

	it("is half a so'm for UZS, which has no fractional unit", () => {
		// A hardcoded 0.01 here rejected legitimate whole-so'm payments.
		expect(moneyEpsilon("UZS")).toBe(0.5);
	});

	it("defaults to half a cent when the currency is unknown or missing", () => {
		expect(moneyEpsilon()).toBe(0.005);
		expect(moneyEpsilon("")).toBe(0.005);
	});
});
